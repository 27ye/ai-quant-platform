"""Safety checks for the opt-in real-data validation CLI (no live I/O)."""

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.app.core.config import Settings
from scripts import validate_ai_analysis as runner


def test_default_validation_does_not_enable_mysql():
    args = runner.parse_args([])
    assert args.stock_code == "600519"
    assert args.mysql is False


def test_invalid_stock_is_rejected_before_side_effects(monkeypatch, capsys):
    def forbidden(*args):
        pytest.fail("must not call providers or create databases")

    monkeypatch.setattr(runner, "validate_mysql", forbidden)
    assert runner.main(["--mysql", "--stock-code", "bad"]) == 1
    assert '"business_code": 40001' in capsys.readouterr().err


def test_raw_upstream_exception_is_never_printed(monkeypatch, capsys):
    async def failing(stock_code):
        raise RuntimeError("password=secret API_KEY=secret https://user:secret@db")

    monkeypatch.setattr(runner, "validate", failing)
    assert runner.main([]) == 1
    output = capsys.readouterr()
    assert "secret" not in output.err + output.out
    assert "RuntimeError" in output.err


def test_memory_mode_does_not_create_a_database(monkeypatch):
    calls = []

    async def validate(stock_code):
        calls.append(stock_code)

    monkeypatch.setattr(runner, "validate", validate)
    monkeypatch.setattr(runner, "create_acceptance_database", lambda *_: pytest.fail("unexpected DB"))
    assert runner.main([]) == 0
    assert calls == ["600519"]


def test_nonlocal_mysql_is_rejected_before_connection(monkeypatch):
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *_: pytest.fail("unexpected connection"))
    with pytest.raises(runner.AcceptanceError, match="127.0.0.1:3307"):
        runner.create_acceptance_database(Settings(_env_file=None, mysql_host="remote.invalid"))


@pytest.mark.parametrize("existing", [None, "already_there"])
def test_mysql_creation_is_isolated_and_never_reuses_or_deletes(monkeypatch, capsys, existing):
    import sqlalchemy

    server = MagicMock()
    connection = server.begin.return_value.__enter__.return_value
    identity_result = MagicMock()
    identity_result.one.return_value = ("8.0.41", 3307)
    schema_result = MagicMock()
    schema_result.scalar.return_value = existing
    create_result = MagicMock()
    connection.execute.side_effect = [identity_result, schema_result, create_result]
    engine_calls = []

    def create_engine(url, **kwargs):
        engine_calls.append(url)
        return server

    monkeypatch.setattr(sqlalchemy, "create_engine", create_engine)
    settings = Settings(_env_file=None, mysql_host="127.0.0.1",
                        mysql_port=3307, mysql_database="ai_quant",
                        mysql_password="secret-do-not-print")
    if existing:
        with pytest.raises(runner.AcceptanceError, match="already exists"):
            runner.create_acceptance_database(settings)
        assert connection.execute.call_count == 2
    else:
        name = runner.create_acceptance_database(settings)
        assert name.startswith("ai_quant_v1_acceptance_")
        assert connection.execute.call_count == 3
        sql = str(connection.execute.call_args.args[0])
        assert sql == f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"
    assert engine_calls[0].database is None
    assert settings.mysql_database == "ai_quant"
    assert server.dispose.call_count == 1
    assert "secret-do-not-print" not in capsys.readouterr().out
    assert all("DROP" not in str(call.args[0]) for call in connection.execute.call_args_list)


def test_mysql_validation_refuses_an_already_imported_backend(monkeypatch):
    monkeypatch.setitem(runner.sys.modules, "backend.app.db.session", object())
    with pytest.raises(runner.AcceptanceError, match="fresh process"):
        runner.validate_mysql("600519")


def test_llm_probe_is_explicitly_not_stock_acceptance(monkeypatch, capsys):
    class Client:
        model_name = "test-model"

        async def complete_json(self, messages):
            return '{"ok":true}'

    monkeypatch.setattr(runner, "make_llm_client", Client)
    assert runner.main(["--llm-only"]) == 0
    assert '"stock_pipeline_verified": false' in capsys.readouterr().out


def test_llm_probe_rejects_nonmatching_json(monkeypatch):
    class Client:
        async def complete_json(self, messages):
            return '{}'

    monkeypatch.setattr(runner, "make_llm_client", Client)
    with pytest.raises(runner.AcceptanceError):
        asyncio.run(runner.validate_llm_connection())


def test_frozen_dir_requires_mysql_or_serve(capsys):
    assert runner.main(["--frozen-dir", "frozen"]) == 1
    assert "--frozen-dir requires --mysql or --serve" in capsys.readouterr().err


@pytest.mark.parametrize("directory", [None, "frozen"])
def test_serve_explicitly_selects_live_or_frozen(monkeypatch, directory):
    calls = []
    monkeypatch.setattr(runner, "serve_acceptance", lambda *args: calls.append(args))
    args = ["--serve"] + (["--frozen-dir", directory] if directory else [])
    assert runner.main(args) == 0
    assert calls == [(directory, None)]


def test_metadata_without_frozen_is_rejected(capsys):
    assert runner.main(["--metadata", "metadata.json"]) == 1
    assert "--metadata requires --frozen-dir" in capsys.readouterr().err


def test_occupied_http_port_refuses_database_creation(monkeypatch):
    monkeypatch.delitem(runner.sys.modules, "backend.app.db.session", raising=False)
    listener = MagicMock()
    listener.bind.side_effect = OSError("port occupied")
    wrapper = MagicMock()
    wrapper.__enter__.return_value = listener
    monkeypatch.setattr(runner.socket, "socket", lambda *_: wrapper)
    monkeypatch.setattr(runner, "create_acceptance_database", lambda *_: pytest.fail("unexpected database"))
    with pytest.raises(runner.AcceptanceError, match="port 8000"):
        runner.serve_acceptance(None, None)


def test_existing_database_names_are_refused_before_connection():
    from sqlalchemy.engine import URL
    engine = MagicMock()
    engine.url = URL.create("mysql+pymysql", host="127.0.0.1", port=3307, database="ai_quant")
    with pytest.raises(runner.AcceptanceError, match="isolation"):
        runner.verify_database_identity(engine, "ai_quant")
    engine.connect.assert_not_called()


@pytest.mark.parametrize("identity", [
    ("8.0.41", 3307, "ai_quant_v1_acceptance_20260910_010203_123456"),
    ("10.3.7-MariaDB", 3307, "ai_quant_v1_acceptance_20260910_010203_123456"),
    ("8.0.41", 3306, "ai_quant_v1_acceptance_20260910_010203_123456"),
    ("8.0.41", 3307, "ai_quant"),
])
def test_actual_identity_is_checked_before_migration(identity):
    from sqlalchemy.engine import URL
    name = "ai_quant_v1_acceptance_20260910_010203_123456"
    engine = MagicMock()
    engine.url = URL.create("mysql+pymysql", host="127.0.0.1", port=3307, database=name)
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.one.return_value = identity
    if identity == ("8.0.41", 3307, name):
        runner.verify_database_identity(engine, name)
    else:
        with pytest.raises(runner.AcceptanceError, match="identity check"):
            runner.verify_database_identity(engine, name)
    assert str(connection.execute.call_args.args[0]) == "SELECT VERSION(), @@port, DATABASE()"


def test_acceptance_headers_preserve_response():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from datetime import date

    for package in (None, SimpleNamespace(start_date=date(2024, 1, 2), end_date=date(2025, 1, 2))):
        app = FastAPI()
        app.get("/health")(lambda: {"code": 0})
        runner.install_acceptance_headers(app, package)
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.json() == {"code": 0}
        assert response.headers["X-Acceptance-Mode"] == ("frozen" if package else "live")
        if package:
            assert response.headers["X-Acceptance-Start"] == "2024-01-02"
            assert response.headers["X-Acceptance-End"] == "2025-01-02"
        else:
            assert "X-Acceptance-Start" not in response.headers

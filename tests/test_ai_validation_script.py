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
    with pytest.raises(runner.AcceptanceError, match="localhost"):
        runner.create_acceptance_database(Settings(_env_file=None, mysql_host="remote.invalid"))


@pytest.mark.parametrize("existing", [None, "already_there"])
def test_mysql_creation_is_isolated_and_never_reuses_or_deletes(monkeypatch, capsys, existing):
    import sqlalchemy

    server = MagicMock()
    connection = server.begin.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = existing
    engine_calls = []

    def create_engine(url, **kwargs):
        engine_calls.append(url)
        return server

    monkeypatch.setattr(sqlalchemy, "create_engine", create_engine)
    settings = Settings(_env_file=None, mysql_host="127.0.0.1",
                        mysql_database="ai_quant", mysql_password="secret-do-not-print")
    if existing:
        with pytest.raises(runner.AcceptanceError, match="already exists"):
            runner.create_acceptance_database(settings)
        assert connection.execute.call_count == 1
    else:
        name = runner.create_acceptance_database(settings)
        assert name.startswith("ai_quant_v1_acceptance_")
        assert connection.execute.call_count == 2
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

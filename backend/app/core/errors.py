class ApplicationError(RuntimeError):
    code = 50000
    message = "internal server error"
    status_code = 500

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.message)


class InvalidParameterError(ApplicationError):
    code = 40001
    message = "invalid parameter"
    status_code = 400


class StockNotFoundError(ApplicationError):
    code = 40002
    message = "stock not found"
    status_code = 404


class CatalogNotSyncedError(ApplicationError):
    """V2 B1 ``50006``: search needs the local catalog, which was never synced.

    The live-provider fallback this replaces could not work: a full-market spot
    snapshot needs far longer than the provider's bounded retry budget (measured
    ~34 s for 5915 rows against a 4 s budget), so every cold-start search ended in
    ``50001`` after ~4.7 s having achieved nothing. A distinct, retryable code lets
    the client say "catalog is initialising" instead of guessing at a timeout.
    """

    code = 50006
    message = "stock catalog not synced"
    status_code = 503


class InsufficientStockDataError(ApplicationError):
    code = 40003
    message = "insufficient stock data"
    status_code = 422


class ReportNotFoundError(ApplicationError):
    code = 40006
    message = "report not found"
    status_code = 404


class DataProviderError(ApplicationError):
    code = 50001
    message = "data provider error"
    status_code = 502


class QuantCalculationError(ApplicationError):
    code = 50003
    message = "quant calculation error"
    status_code = 500


class DatabaseOperationError(ApplicationError):
    code = 50002
    message = "database error"
    status_code = 500


class BacktestNotFoundError(ApplicationError):
    """V2: unknown ``backtest_id`` (distinct from "stock not found")."""

    code = 40005
    message = "backtest not found"
    status_code = 404


class BacktestError(ApplicationError):
    """V2 ``50004``: the backtest engine cannot serve this request.

    Raised when a ``v2_windowed`` request arrives while C's windowed entry points
    (``resolve_backtest_request`` / ``validate_backtest_window`` /
    ``run_backtest_request``) are not importable. Running the old V1 core and
    labelling its output ``v2_windowed`` would misreport the window semantics, so
    the request fails explicitly and **nothing is persisted**.
    """

    code = 50004
    message = "backtest error"
    status_code = 500

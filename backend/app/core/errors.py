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

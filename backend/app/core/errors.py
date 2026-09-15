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
    code = 40005
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

class ApplicationError(RuntimeError):
    code = 50000
    message = "internal server error"
    status_code = 500

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.message)


class StockNotFoundError(ApplicationError):
    code = 40002
    message = "stock not found"
    status_code = 404


class InsufficientStockDataError(ApplicationError):
    code = 40003
    message = "insufficient stock data"
    status_code = 422


class DatabaseOperationError(ApplicationError):
    code = 50002
    message = "database error"
    status_code = 500

class BrasileiraoError(Exception):
    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


class ConfigurationError(BrasileiraoError):
    pass


class DataIngestionError(BrasileiraoError):
    pass


class ExternalAPIError(DataIngestionError):
    pass


class RateLimitExceededError(DataIngestionError):
    pass


class DataValidationError(BrasileiraoError):
    pass


# TODO(fase-6): agregar ModelError cuando empecemos entrenamiento

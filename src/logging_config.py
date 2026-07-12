import logging

from src.config import Settings

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_CONSOLE_HANDLER_NAME = "brasileirao_console"

_NOISY_LOGGERS = ("urllib3", "sqlalchemy.engine")


def setup_logging(level: str | None = None) -> None:
    resolved_level = (level or Settings().log_level).upper()

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)

    has_console_handler = any(
        getattr(handler, "name", None) == _CONSOLE_HANDLER_NAME for handler in root_logger.handlers
    )
    if not has_console_handler:
        handler = logging.StreamHandler()
        handler.name = _CONSOLE_HANDLER_NAME
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root_logger.addHandler(handler)

    for logger_name in _NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

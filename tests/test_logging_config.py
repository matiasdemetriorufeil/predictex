import logging

from src.config import Settings
from src.logging_config import setup_logging


def test_setup_logging_sets_level_from_settings():
    setup_logging()

    expected_level = logging.getLevelName(Settings().log_level.upper())
    assert logging.getLogger().level == expected_level


def test_info_visible_debug_not_at_info_level(caplog):
    setup_logging("INFO")

    logger = logging.getLogger("tests.logging_config_check")
    caplog.clear()
    logger.info("info visible message")
    logger.debug("debug hidden message")

    assert "info visible message" in caplog.text
    assert "debug hidden message" not in caplog.text

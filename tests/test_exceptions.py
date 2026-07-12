import pytest

from src.exceptions import (
    BrasileiraoError,
    ConfigurationError,
    DataIngestionError,
    DataValidationError,
    ExternalAPIError,
    RateLimitExceededError,
)


@pytest.mark.parametrize(
    "exception_class",
    [
        ConfigurationError,
        DataIngestionError,
        ExternalAPIError,
        RateLimitExceededError,
        DataValidationError,
    ],
)
def test_exception_is_instance_of_base_error(exception_class):
    assert isinstance(exception_class("boom"), BrasileiraoError)


def test_context_is_stored_and_accessible():
    context = {"status_code": 429, "source": "football-data.org"}
    error = RateLimitExceededError("quota exceeded", context=context)

    assert error.context == context


def test_context_defaults_to_empty_dict():
    error = DataValidationError("invalid data")

    assert error.context == {}

import pytest
from sqlalchemy import text

from src.db import engine


@pytest.mark.integration
def test_can_connect_and_select_1():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1

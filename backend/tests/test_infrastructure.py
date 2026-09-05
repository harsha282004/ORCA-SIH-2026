"""Integration tests requiring real infrastructure (PostgreSQL/PostGIS/Redis).

Run explicitly with:  pytest -m integration
Excluded from the default test run with: pytest -m "not integration"
"""
import pytest

from app.services.cache import check_redis
from app.services.database import check_database, check_postgis


@pytest.mark.integration
def test_database_connectivity() -> None:
    result = check_database()
    assert result["status"] == "healthy", result.get("error")


@pytest.mark.integration
def test_postgis_available() -> None:
    result = check_postgis()
    assert result["status"] == "healthy", result.get("error")
    assert result.get("version")


@pytest.mark.integration
def test_redis_connectivity() -> None:
    result = check_redis()
    assert result["status"] == "healthy", result.get("error")

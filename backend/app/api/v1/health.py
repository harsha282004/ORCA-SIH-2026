"""Readiness endpoint — GET /api/v1/health/ready.

Actually checks PostgreSQL, PostGIS, and Redis on every call. Never
returns a fabricated "healthy" value: each dependency's status reflects a
real probe performed for this request.
"""
from fastapi import APIRouter, Response, status

from app.services.cache import check_redis
from app.services.database import check_database, check_postgis

router = APIRouter()


@router.get("/health/ready")
def readiness(response: Response) -> dict:
    database_result = check_database()
    postgis_result = check_postgis()
    redis_result = check_redis()

    dependencies = {
        "database": database_result["status"],
        "postgis": postgis_result["status"],
        "redis": redis_result["status"],
    }
    all_healthy = all(value == "healthy" for value in dependencies.values())

    if not all_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if all_healthy else "not_ready",
        "dependencies": dependencies,
        "details": {
            "database": database_result,
            "postgis": postgis_result,
            "redis": redis_result,
        },
    }

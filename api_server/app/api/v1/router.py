from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.access import router as access_router
from app.api.v1.documents import router as documents_router
from app.api.v1.jobs import router as jobs_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(access_router)
router.include_router(documents_router)
router.include_router(jobs_router)

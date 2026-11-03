from fastapi import APIRouter

from app.api.v1.routes.audit import router as audit_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.staff import router as staff_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(staff_router, prefix="/staff", tags=["staff"])
api_router.include_router(audit_router, prefix="/audit-events", tags=["audit"])

from fastapi import APIRouter

from app.api.v1.routes.audit import router as audit_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.contacts import router as contacts_router
from app.api.v1.routes.files import router as files_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.owners import router as owners_router
from app.api.v1.routes.properties import router as properties_router
from app.api.v1.routes.reference_data import router as reference_data_router
from app.api.v1.routes.staff import router as staff_router
from app.api.v1.routes.units import router as units_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(staff_router, prefix="/staff", tags=["staff"])
api_router.include_router(audit_router, prefix="/audit-events", tags=["audit"])
api_router.include_router(reference_data_router, tags=["reference data"])
api_router.include_router(contacts_router, prefix="/contacts", tags=["contacts"])
api_router.include_router(properties_router, prefix="/properties", tags=["properties"])
api_router.include_router(owners_router, prefix="/properties", tags=["property owners"])
api_router.include_router(units_router, prefix="/properties", tags=["units"])
api_router.include_router(files_router, prefix="/properties", tags=["media and documents"])

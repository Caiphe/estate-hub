from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.auth.constants import CSRF_HEADER_NAME
from app.auth.http import register_auth_exception_handlers
from app.core.config import settings
from app.core.database import engine
from app.core.errors import register_exception_handlers
from app.core.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from app.core.redis import redis_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="EstateHub API",
        description="Property sales, lettings, and management API",
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.add_middleware(RequestIdMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", CSRF_HEADER_NAME, REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    register_exception_handlers(application)
    register_auth_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()

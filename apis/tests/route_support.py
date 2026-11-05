"""Enumerate the application's API routes with their full paths.

FastAPI 0.162 keeps each included router as one ``_IncludedRouter`` entry in
``app.routes`` instead of copying its routes, so a plain ``isinstance(route, APIRoute)``
walk finds nothing. This walks included routers and joins their prefixes. If FastAPI
changes this structure the walk raises instead of silently returning nothing.
"""

from collections.abc import Iterable, Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute


def iter_api_routes(app: FastAPI) -> Iterator[tuple[str, APIRoute]]:
    found = list(_walk(app.routes, ""))
    if not found:
        raise AssertionError("No API routes found: the route walk no longer matches FastAPI.")
    yield from found


def _walk(routes: Iterable[BaseRoute], prefix: str) -> Iterator[tuple[str, APIRoute]]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif hasattr(route, "original_router"):
            context = getattr(route, "include_context")  # noqa: B009
            nested = getattr(route, "original_router")  # noqa: B009
            yield from _walk(nested.routes, prefix + (context.prefix or ""))

"""FastAPI composition root: mounts GraphQL (reseller + operator) + HTTP (webhooks, health).

Security headers (SECURITY-04) are applied to all responses. Tenant/roles come from
`container.identity` — the header stub in the memory profile and whenever Keycloak/Entra
isn't configured, real JWT verification (Keycloak or Entra, ADR-0023) once it is
(`composition._resolve_identity_provider`).
CORS is restricted to `Settings.cors_allowed_origins` (SEC-08) — the UI is a separate
origin (Front Door in Azure, the Vite dev server locally),
not same-origin with the API.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter

from src.api.graphql.context import GraphQLContext
from src.api.graphql.operator.schema import build_operator_schema
from src.api.graphql.reseller.schema import build_reseller_schema
from src.api.http import health, webhooks
from src.composition import build_container
from src.shared.config import get_settings

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' https://cdn.jsdelivr.net; "
        "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "img-src 'self' https://fastapi.tiangolo.com"
    ),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


async def _build_context(request: Request) -> GraphQLContext:
    container = request.app.state.container
    principal = container.identity.authenticate(request.headers)
    if principal is None:
        # Reject unauthenticated calls (SEC-08) — raised here, before GraphQL execution
        # starts, so an invalid/expired/missing token is a clean 401, not a GraphQL
        # response with a partial/empty result a caller could mistake for "no data".
        raise HTTPException(status_code=401, detail="missing or invalid credentials")
    return GraphQLContext(container=container, tenant_id=principal.tenant_id, roles=principal.roles)


def create_app() -> FastAPI:
    app = FastAPI(title="ERP & Supply Chain Order Portal", version="0.2.0")
    app.state.container = build_container()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_allowed_origins,
        # auth is a Bearer header, not cookies — no credentials mode needed
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(
        GraphQLRouter(build_reseller_schema(), context_getter=_build_context),
        prefix="/graphql/reseller",
    )
    app.include_router(
        GraphQLRouter(build_operator_schema(), context_getter=_build_context),
        prefix="/graphql/operator",
    )
    app.include_router(webhooks.router)
    app.include_router(health.router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    return app


app = create_app()

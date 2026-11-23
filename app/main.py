from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.session import SessionLocal

setup_logging()
settings = get_settings()

# NOTE: The provisioning scheduler is intentionally NOT started here. Running it
# inside the API web process would spawn one scheduler per Uvicorn worker/instance,
# causing parallel provisioning and multiple initial passwords for the same user.
# Provisioning runs as a dedicated worker instead:
#   one-shot:  python -m app.scripts.provision_users
#   periodic:  python -m app.scripts.provision_worker


def docs_urls(enabled: bool) -> dict:
    """Swagger, ReDoc i OpenAPI sema postoje samo kad su izricito ukljuceni."""
    if enabled:
        return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


app = FastAPI(title=settings.app_name, **docs_urls(settings.api_docs_enabled))

# Zaglavlja koja reverse proxy dodaje; njihovo prisustvo znaci da zahtev dolazi spolja.
PROXY_HEADERS = (b"x-forwarded-for", b"x-forwarded-prefix", b"x-forwarded-proto", b"x-real-ip", b"forwarded")

SECURITY_HEADERS = (
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)


class SecurityHeadersMiddleware:
    """Dodaje osnovna bezbednosna zaglavlja na svaki HTTP odgovor."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers.extend((k, v) for k, v in SECURITY_HEADERS if k not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class ForwardedPrefixMiddleware:
    """Postavlja root_path iz X-Forwarded-Prefix (za /docs iza proxy-ja sa prefiksom)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            for k, v in scope["headers"]:
                if k == b"x-forwarded-prefix":
                    scope["root_path"] = v.decode().rstrip("/")
                    break
        await self.app(scope, receive, send)


app.add_middleware(ForwardedPrefixMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

register_exception_handlers(app)
app.include_router(api_router)


def is_proxied(request: Request) -> bool:
    return any(name in PROXY_HEADERS for name, _ in request.scope.get("headers", []))


@app.get("/health", include_in_schema=False, response_model=None)
def health(request: Request) -> dict | JSONResponse:
    # Kroz proxy (spolja) se ponasa kao nepostojeca ruta, osim ako je HEALTH_PUBLIC=true.
    if not settings.health_public and is_proxied(request):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    db_ok = True
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1 FROM DUAL"))
        finally:
            db.close()
    except Exception:
        db_ok = False

    return {"status": "ok" if db_ok else "degraded"}

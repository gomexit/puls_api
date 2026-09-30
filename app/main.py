from fastapi import FastAPI
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
app = FastAPI(title=settings.app_name)


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

register_exception_handlers(app)
app.include_router(api_router)


@app.get("/health")
def health() -> dict:
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

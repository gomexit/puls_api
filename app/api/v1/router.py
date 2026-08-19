from fastapi import APIRouter

from app.api.v1 import (
    admin_ideas,
    admin_notifications,
    admin_surveys,
    auth,
    ideas,
    notifications,
    push,
    surveys,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(ideas.router)
api_router.include_router(admin_ideas.router)
api_router.include_router(surveys.router)
api_router.include_router(admin_surveys.router)
api_router.include_router(notifications.router)
api_router.include_router(admin_notifications.router)
api_router.include_router(push.router)

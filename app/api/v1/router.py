from fastapi import APIRouter

from app.api.v1 import (
    admin_audit,
    admin_configuration,
    admin_dashboard,
    admin_ideas,
    admin_notifications,
    admin_survey_results,
    admin_surveys,
    admin_users,
    app_version,
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
api_router.include_router(admin_survey_results.router)
api_router.include_router(admin_users.router)
api_router.include_router(notifications.router)
api_router.include_router(admin_notifications.router)
api_router.include_router(push.router)
api_router.include_router(admin_dashboard.router)
api_router.include_router(admin_audit.router)
api_router.include_router(admin_configuration.router)
api_router.include_router(app_version.router)

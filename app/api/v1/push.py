from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_current_context
from app.schemas.push import (
    PushTokenDeleteResponse,
    PushTokenRegisterRequest,
    PushTokenRegisterResponse,
)
from app.services.push_token_service import PushTokenService

router = APIRouter(prefix="/push", tags=["Push"])


def get_push_token_service(db: Session = Depends(get_db)) -> PushTokenService:
    return PushTokenService(db)


@router.put("/token", response_model=PushTokenRegisterResponse)
def register_token(
    payload: PushTokenRegisterRequest,
    context: AuthContext = Depends(get_current_context),
    service: PushTokenService = Depends(get_push_token_service),
) -> PushTokenRegisterResponse:
    # Korisnik i uredjaj iskljucivo iz Bearer sesije (AuthContext), ne iz payload-a.
    service.register(
        context.korisnik, context.sesija.uredjaj_id, payload.fcm_token, payload.app_version
    )
    return PushTokenRegisterResponse(registered=True)


@router.delete("/token", response_model=PushTokenDeleteResponse)
def delete_token(
    context: AuthContext = Depends(get_current_context),
    service: PushTokenService = Depends(get_push_token_service),
) -> PushTokenDeleteResponse:
    # Deaktivira token samo trenutnog korisnika i trenutnog uredjaja.
    service.deactivate_current_device(context.korisnik, context.sesija.uredjaj_id)
    return PushTokenDeleteResponse(deactivated=True)

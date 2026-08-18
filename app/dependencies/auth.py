from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import InvalidSessionError, PhoneConfirmationRequiredError, PasswordChangeRequiredError
from app.db.session import engine, get_db
from app.models.korisnicka_sesija import KorisnickaSesija
from app.models.korisnik import Korisnik
from app.services.auth_service import AuthService
from app.services.sms_service import get_sms_provider

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    korisnik: Korisnik
    sesija: KorisnickaSesija


def get_auth_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AuthService:
    return AuthService(db, sms_provider=get_sms_provider(settings.sms_provider, engine=engine))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_current_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise InvalidSessionError()

    korisnik, sesija = auth_service.authenticate_token(credentials.credentials)
    return AuthContext(korisnik=korisnik, sesija=sesija)


def get_current_user(context: AuthContext = Depends(get_current_context)) -> Korisnik:
    """Allows access for users still in the first-login flow (password change / phone confirm)."""
    return context.korisnik


def get_current_ready_user(context: AuthContext = Depends(get_current_context)) -> Korisnik:
    """Requires the first-login flow to be fully completed. Use for all non-auth endpoints."""
    korisnik = context.korisnik
    if korisnik.obavezna_promena_lozinke == "D":
        raise PasswordChangeRequiredError()
    if korisnik.telefon_potvrdjen == "N":
        raise PhoneConfirmationRequiredError()
    return korisnik

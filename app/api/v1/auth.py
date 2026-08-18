from fastapi import APIRouter, Depends, Request

from app.dependencies.auth import AuthContext, get_auth_service, get_current_context, get_current_user
from app.models.korisnik import Korisnik
from app.repositories.korisnik_repository import KorisnikRepository
from app.schemas.auth import (
    ChangePasswordRequest,
    ConfirmPhoneRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ResetPasswordRequest,
)
from app.schemas.common import MessageResponse
from app.schemas.user import CurrentUserRaspored, CurrentUserResponse, UserSummary
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])

# Oracle PULS_KORISNICKE_SESIJE.KORISNICKI_AGENT is VARCHAR2(500); truncate the
# incoming header so an oversized User-Agent can never raise a DB error / HTTP 500.
USER_AGENT_MAX = 500


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    if ua is None:
        return None
    return ua[:USER_AGENT_MAX]


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    result = auth_service.login(
        platni_broj=payload.platni_broj,
        lozinka=payload.lozinka,
        uredjaj_id=payload.uredjaj_id,
        naziv_uredjaja=payload.naziv_uredjaja,
        ip_adresa=_client_ip(request),
        korisnicki_agent=_user_agent(request),
    )
    korisnik = result.korisnik
    return LoginResponse(
        access_token=result.token,
        user=UserSummary(
            id=korisnik.id,
            platni_broj=korisnik.platni_broj,
            ime=korisnik.ime,
            prezime=korisnik.prezime,
            broj_telefona=korisnik.broj_telefona,
        ),
        obavezna_promena_lozinke=korisnik.obavezna_promena_lozinke == "D",
        telefon_potvrdjen=korisnik.telefon_potvrdjen == "D",
    )


@router.get("/me", response_model=CurrentUserResponse)
def get_me(
    korisnik: Korisnik = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> CurrentUserResponse:
    korisnik_repository = KorisnikRepository(auth_service.db)
    uloge = korisnik_repository.get_active_role_codes(korisnik.id)
    raspored = korisnik_repository.get_primary_active_raspored(korisnik.id)

    return CurrentUserResponse(
        id=korisnik.id,
        platni_broj=korisnik.platni_broj,
        ime=korisnik.ime,
        prezime=korisnik.prezime,
        broj_telefona=korisnik.broj_telefona,
        status_zaposlenja=korisnik.status_zaposlenja,
        status_naloga=korisnik.status_naloga,
        obavezna_promena_lozinke=korisnik.obavezna_promena_lozinke == "D",
        telefon_potvrdjen=korisnik.telefon_potvrdjen == "D",
        uloge=uloge,
        raspored=(
            CurrentUserRaspored(
                orgjed_sifra=raspored.orgjed_sifra, radno_mesto_sifra=raspored.radno_mesto_sifra
            )
            if raspored
            else None
        ),
    )


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    korisnik: Korisnik = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    auth_service.change_password(
        korisnik, payload.trenutna_lozinka, payload.nova_lozinka, payload.potvrda_nove_lozinke
    )
    return MessageResponse(message="Lozinka je uspešno promenjena.")


@router.post("/confirm-phone", response_model=MessageResponse)
def confirm_phone(
    payload: ConfirmPhoneRequest,
    korisnik: Korisnik = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    auth_service.confirm_phone(korisnik, payload.broj_telefona)
    return MessageResponse(message="Broj telefona je potvrđen.")


@router.post("/logout", response_model=MessageResponse)
def logout(
    context: AuthContext = Depends(get_current_context),
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    auth_service.logout(context.korisnik, context.sesija)
    return MessageResponse(message="Uspešno ste odjavljeni.")


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    auth_service.forgot_password(payload.platni_broj, ip_adresa=_client_ip(request))
    return MessageResponse(
        message="Ako nalog postoji i ispunjava uslove, kod za reset lozinke je poslat."
    )


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    auth_service.reset_password(
        platni_broj=payload.platni_broj,
        kod=payload.kod,
        nova_lozinka=payload.nova_lozinka,
        potvrda_nove_lozinke=payload.potvrda_nove_lozinke,
        ip_adresa=_client_ip(request),
    )
    return MessageResponse(message="Lozinka je uspešno resetovana.")

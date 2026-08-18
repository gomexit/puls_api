import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.phone import is_valid_local_mobile_phone
from app.core.exceptions import (
    AccountDisabledError,
    AccountInactiveError,
    AccountLockedError,
    InvalidCredentialsError,
    InvalidResetCodeError,
    InvalidSessionError,
    ResetCodeExpiredError,
    SessionExpiredError,
)
from app.core.security import (
    generate_reset_code,
    generate_session_token,
    hash_reset_code,
    hash_session_token,
)
from app.models.korisnicka_sesija import KorisnickaSesija
from app.models.korisnik import Korisnik
from app.repositories.audit_repository import AuditRepository
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.korisnik_repository import KorisnikRepository
from app.repositories.reset_password_repository import ResetPasswordRepository
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.configuration_service import ConfigurationService
from app.services.password_service import PasswordService
from app.services.sms_service import SmsProvider

MAX_LOGIN_ATTEMPTS_KEY = "MAX_NEUSPESNIH_PRIJAVA"
RESET_CODE_TTL_KEY = "TRAJANJE_RESET_KODA_MIN"

REVOKE_REASON_NEW_LOGIN = "NOVA_PRIJAVA"
REVOKE_REASON_LOGOUT = "LOGOUT"
REVOKE_REASON_PASSWORD_RESET = "RESET_LOZINKE"

# Safe, non-sensitive reason codes recorded in the audit "detalji" field.
FAIL_REASON_UNKNOWN_USER = "NEPOSTOJECI_KORISNIK"
FAIL_REASON_INACTIVE = "NEAKTIVAN_ZAPOSLENI"
FAIL_REASON_DISABLED = "ONEMOGUCEN_NALOG"
FAIL_REASON_LOCKED = "ZAKLJUCAN_NALOG"
FAIL_REASON_BAD_PASSWORD = "POGRESNA_LOZINKA"


class LoginResult:
    def __init__(self, token: str, sesija: KorisnickaSesija, korisnik: Korisnik):
        self.token = token
        self.sesija = sesija
        self.korisnik = korisnik


class AuthService:
    """Owns the AUTH transaction boundary: each public method commits on success
    and rolls back on any failure, so partial state is never persisted."""

    def __init__(
        self,
        db: Session,
        sms_provider: SmsProvider,
        korisnik_repository: KorisnikRepository | None = None,
        session_repository: SessionRepository | None = None,
        reset_repository: ResetPasswordRepository | None = None,
        configuration_service: ConfigurationService | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.settings = get_settings()

        self.korisnik_repository = korisnik_repository or KorisnikRepository(db)
        self.session_repository = session_repository or SessionRepository(db)
        self.reset_repository = reset_repository or ResetPasswordRepository(db)
        self.configuration_service = configuration_service or ConfigurationService(
            ConfigurationRepository(db)
        )
        self.password_service = PasswordService(self.configuration_service)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )
        self.sms_provider = sms_provider

    def login(
        self,
        platni_broj: str,
        lozinka: str,
        uredjaj_id: str,
        naziv_uredjaja: str | None,
        ip_adresa: str | None,
        korisnicki_agent: str | None,
    ) -> LoginResult:
        # Transaction boundaries are explicit: every failure path persists its own
        # audit via _record_failed_login (which commits), so a rejected login is
        # always recorded even though it raises 401/403. The success path performs
        # all mutations in one transaction and commits once at the end.
        korisnik = self.korisnik_repository.get_by_platni_broj(platni_broj)
        if korisnik is None:
            self._record_failed_login(None, platni_broj, ip_adresa, FAIL_REASON_UNKNOWN_USER)
            raise InvalidCredentialsError()

        if korisnik.status_zaposlenja != "AKTIVAN":
            self._record_failed_login(korisnik.id, platni_broj, ip_adresa, FAIL_REASON_INACTIVE)
            raise AccountInactiveError()

        if korisnik.status_naloga != "OMOGUCEN":
            self._record_failed_login(korisnik.id, platni_broj, ip_adresa, FAIL_REASON_DISABLED)
            raise AccountDisabledError()

        if korisnik.zakljucan == "D":
            self._record_failed_login(korisnik.id, platni_broj, ip_adresa, FAIL_REASON_LOCKED)
            raise AccountLockedError()

        if korisnik.lozinka_hash is None or not self.password_service.verify(
            lozinka, korisnik.lozinka_hash
        ):
            self._register_failed_attempt(korisnik, platni_broj, ip_adresa)
            raise InvalidCredentialsError()

        try:
            korisnik.broj_neuspesnih_prijava = 0
            korisnik.datum_poslednje_prijave = datetime.datetime.now()

            self.session_repository.revoke_active_sessions_for_user(
                korisnik.id, REVOKE_REASON_NEW_LOGIN
            )
            self.audit_service.log(
                AuditAction.SESIJA_OPOZVANA_NOVOM_PRIJAVOM,
                korisnik_id=korisnik.id,
                platni_broj=platni_broj,
                ip_adresa=ip_adresa,
            )

            token = generate_session_token()
            sesija = self.session_repository.create_session(
                korisnik_id=korisnik.id,
                token_hash=hash_session_token(token),
                uredjaj_id=uredjaj_id,
                naziv_uredjaja=naziv_uredjaja,
                ttl_days=self.settings.session_ttl_days,
                ip_adresa=ip_adresa,
                korisnicki_agent=korisnicki_agent,
            )

            self.audit_service.log(
                AuditAction.LOGIN_USPESAN,
                korisnik_id=korisnik.id,
                platni_broj=platni_broj,
                ip_adresa=ip_adresa,
            )

            self.db.commit()
            return LoginResult(token=token, sesija=sesija, korisnik=korisnik)
        except Exception:
            self.db.rollback()
            raise

    def _record_failed_login(
        self, korisnik_id: int | None, platni_broj: str, ip_adresa: str | None, razlog: str
    ) -> None:
        """Persist a LOGIN_NEUSPESAN audit entry in its own committed transaction.

        Kept separate from the success path so a rejected login is durably recorded
        without leaving partial state behind."""
        try:
            self.audit_service.log(
                AuditAction.LOGIN_NEUSPESAN,
                korisnik_id=korisnik_id,
                platni_broj=platni_broj,
                ip_adresa=ip_adresa,
                detalji=razlog,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _register_failed_attempt(
        self, korisnik: Korisnik, platni_broj: str, ip_adresa: str | None
    ) -> None:
        try:
            max_attempts = self.configuration_service.get_int(
                MAX_LOGIN_ATTEMPTS_KEY, self.settings.max_login_attempts_fallback
            )
            korisnik.broj_neuspesnih_prijava = (korisnik.broj_neuspesnih_prijava or 0) + 1

            self.audit_service.log(
                AuditAction.LOGIN_NEUSPESAN,
                korisnik_id=korisnik.id,
                platni_broj=platni_broj,
                ip_adresa=ip_adresa,
                detalji=FAIL_REASON_BAD_PASSWORD,
            )

            if korisnik.broj_neuspesnih_prijava >= max_attempts:
                korisnik.zakljucan = "D"
                korisnik.datum_zakljucavanja = datetime.datetime.now()
                self.audit_service.log(
                    AuditAction.NALOG_ZAKLJUCAN,
                    korisnik_id=korisnik.id,
                    platni_broj=platni_broj,
                    ip_adresa=ip_adresa,
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def authenticate_token(self, token: str) -> tuple[Korisnik, KorisnickaSesija]:
        token_hash = hash_session_token(token)
        sesija = self.session_repository.get_by_token_hash(token_hash)

        if sesija is None or sesija.aktivna != "D":
            raise InvalidSessionError()

        if sesija.datum_isteka is not None and sesija.datum_isteka <= datetime.datetime.now():
            self.session_repository.revoke_session(sesija, "ISTEKLA")
            self.db.commit()
            raise SessionExpiredError()

        korisnik = self.korisnik_repository.get_by_id(sesija.korisnik_id)
        if korisnik is None:
            raise InvalidSessionError()

        if (
            korisnik.status_zaposlenja != "AKTIVAN"
            or korisnik.status_naloga != "OMOGUCEN"
            or korisnik.zakljucan == "D"
        ):
            self.session_repository.revoke_session(sesija, "NALOG_NIJE_VISE_VALIDAN")
            self.db.commit()
            raise InvalidSessionError()

        self._maybe_touch_activity(sesija)
        return korisnik, sesija

    def _maybe_touch_activity(self, sesija: KorisnickaSesija) -> None:
        throttle = datetime.timedelta(minutes=5)
        now = datetime.datetime.now()
        if sesija.poslednja_aktivnost is None or now - sesija.poslednja_aktivnost > throttle:
            self.session_repository.touch_activity(sesija)
            self.db.commit()

    def change_password(
        self, korisnik: Korisnik, trenutna_lozinka: str, nova_lozinka: str, potvrda_nove_lozinke: str
    ) -> None:
        try:
            if korisnik.lozinka_hash is None or not self.password_service.verify(
                trenutna_lozinka, korisnik.lozinka_hash
            ):
                raise InvalidCredentialsError("Trenutna lozinka nije ispravna.")

            self.password_service.validate_new_password(
                nova_lozinka, potvrda_nove_lozinke, korisnik.lozinka_hash
            )

            korisnik.lozinka_hash = self.password_service.hash(nova_lozinka)
            korisnik.obavezna_promena_lozinke = "N"
            korisnik.datum_promene_lozinke = datetime.datetime.now()
            korisnik.broj_neuspesnih_prijava = 0

            self.audit_service.log(
                AuditAction.PROMENA_LOZINKE, korisnik_id=korisnik.id, platni_broj=korisnik.platni_broj
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def confirm_phone(self, korisnik: Korisnik, broj_telefona: str) -> None:
        try:
            action = (
                AuditAction.PROMENA_TELEFONA
                if korisnik.broj_telefona and korisnik.broj_telefona != broj_telefona
                else AuditAction.POTVRDA_TELEFONA
            )

            korisnik.broj_telefona = broj_telefona
            korisnik.telefon_potvrdjen = "D"
            korisnik.datum_potvrde_telefona = datetime.datetime.now()

            self.audit_service.log(action, korisnik_id=korisnik.id, platni_broj=korisnik.platni_broj)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def logout(self, korisnik: Korisnik, sesija: KorisnickaSesija) -> None:
        try:
            self.session_repository.revoke_session(sesija, REVOKE_REASON_LOGOUT)
            self.audit_service.log(
                AuditAction.LOGOUT, korisnik_id=korisnik.id, platni_broj=korisnik.platni_broj
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def forgot_password(self, platni_broj: str, ip_adresa: str | None) -> None:
        try:
            korisnik = self.korisnik_repository.get_by_platni_broj(platni_broj)
            if (
                korisnik is None
                or korisnik.status_zaposlenja != "AKTIVAN"
                or korisnik.status_naloga != "OMOGUCEN"
                or not is_valid_local_mobile_phone(korisnik.broj_telefona)
            ):
                # Silently no-op to avoid revealing account existence, still commit (no changes made).
                self.db.commit()
                return

            # Send the SMS BEFORE deactivating the previous code or persisting a new
            # one. If delivery fails, the existing valid code stays usable and no new
            # (undelivered) code is presented as active.
            code = generate_reset_code()
            sent = self.sms_provider.send_sms(
                korisnik.broj_telefona, f"Vaš kod za reset lozinke za PULS je: {code}"
            )
            if not sent:
                self.audit_service.log(
                    AuditAction.ZAHTEV_RESET_LOZINKE_GRESKA,
                    korisnik_id=korisnik.id,
                    platni_broj=platni_broj,
                    ip_adresa=ip_adresa,
                    detalji="SMS sa reset kodom nije poslat.",
                )
                self.db.commit()
                return

            self.reset_repository.deactivate_active_for_user(korisnik.id)
            ttl_minutes = self.configuration_service.get_int(
                RESET_CODE_TTL_KEY, self.settings.reset_code_ttl_min_fallback
            )
            self.reset_repository.create(
                korisnik_id=korisnik.id,
                kod_hash=hash_reset_code(code),
                ttl_minutes=ttl_minutes,
                ip_adresa=ip_adresa,
            )

            self.audit_service.log(
                AuditAction.ZAHTEV_RESET_LOZINKE,
                korisnik_id=korisnik.id,
                platni_broj=platni_broj,
                ip_adresa=ip_adresa,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def reset_password(
        self,
        platni_broj: str,
        kod: str,
        nova_lozinka: str,
        potvrda_nove_lozinke: str,
        ip_adresa: str | None,
    ) -> None:
        try:
            korisnik = self.korisnik_repository.get_by_platni_broj(platni_broj)
            if (
                korisnik is None
                or korisnik.status_zaposlenja != "AKTIVAN"
                or korisnik.status_naloga != "OMOGUCEN"
            ):
                raise InvalidResetCodeError()

            reset = self.reset_repository.get_active_for_user(korisnik.id)
            if reset is None:
                raise InvalidResetCodeError()

            if reset.broj_pokusaja is not None and reset.broj_pokusaja >= self.settings.reset_code_max_attempts:
                raise InvalidResetCodeError()

            if reset.datum_isteka is not None and reset.datum_isteka <= datetime.datetime.now():
                raise ResetCodeExpiredError()

            if hash_reset_code(kod) != reset.kod_hash:
                self.reset_repository.increment_attempts(reset)
                self.db.commit()
                raise InvalidResetCodeError()

            self.password_service.validate_new_password(nova_lozinka, potvrda_nove_lozinke)

            korisnik.lozinka_hash = self.password_service.hash(nova_lozinka)
            korisnik.datum_promene_lozinke = datetime.datetime.now()
            korisnik.obavezna_promena_lozinke = "N"
            korisnik.broj_neuspesnih_prijava = 0
            korisnik.zakljucan = "N"
            korisnik.datum_zakljucavanja = None

            self.reset_repository.mark_used(reset)

            self.session_repository.revoke_active_sessions_for_user(
                korisnik.id, REVOKE_REASON_PASSWORD_RESET
            )

            self.audit_service.log(
                AuditAction.RESET_LOZINKE,
                korisnik_id=korisnik.id,
                platni_broj=platni_broj,
                ip_adresa=ip_adresa,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

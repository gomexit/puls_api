"""Admin USERS modul: lista/detalj korisnika + poslovne akcije (lock/unlock/
deactivate/reset-password). Owns the transaction boundary (commit/rollback).

Mutacije zakljucavaju red preko SELECT FOR UPDATE. Response se sastavlja PRE
commit-a (posle commit-a nema DB upita). Audit actor je uvek acting ADMIN, nikad
target korisnik."""

import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    AdminSelfActionNotAllowedError,
    SmsDeliveryFailedError,
    UserNotFoundError,
    ValidationBusinessError,
)
from app.core.phone import is_valid_local_mobile_phone
from app.core.security import generate_temporary_password, hash_password
from app.db.session import engine
from app.models.korisnik import (
    STATUS_NALOGA_OMOGUCEN,
    STATUS_NALOGA_ONEMOGUCEN,
    STATUS_ZAPOSLENJA_AKTIVAN,
    Korisnik,
)
from app.repositories.admin_users_repository import AdminUsersRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.push_token_repository import PushTokenRepository
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.sms_service import SmsProvider, get_sms_provider

REVOKE_REASON_ADMIN_LOCK = "ADMIN_LOCK"
REVOKE_REASON_ADMIN_UNLOCK = "ADMIN_UNLOCK"
REVOKE_REASON_ADMIN_DEACTIVATE = "ADMIN_DEACTIVATE"
REVOKE_REASON_ADMIN_PASSWORD_RESET = "ADMIN_PASSWORD_RESET"


class AdminUsersService:
    def __init__(
        self,
        db: Session,
        sms_provider: SmsProvider | None = None,
        repository: AdminUsersRepository | None = None,
        session_repository: SessionRepository | None = None,
        push_token_repository: PushTokenRepository | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.repo = repository or AdminUsersRepository(db)
        self.session_repo = session_repository or SessionRepository(db)
        self.push_token_repo = push_token_repository or PushTokenRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )
        self.sms_provider = sms_provider or get_sms_provider(self.settings.sms_provider, engine=engine)

    # ---------------------------------------------------------------- citanje
    def list_users(
        self,
        page: int,
        page_size: int,
        search: str | None,
        status_zaposlenja: str | None,
        status_naloga: str | None,
        zakljucan: bool | None,
        uloga: str | None,
    ) -> dict:
        items, total = self.repo.list_users(
            search, status_zaposlenja, status_naloga, zakljucan, uloga, page, page_size
        )
        views = self._to_out_batch(items)
        return {
            "items": views,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": page * page_size < total,
        }

    def get_user(self, user_id: int) -> dict:
        korisnik = self.repo.get_by_id(user_id)
        if korisnik is None:
            raise UserNotFoundError()
        return self._to_out_batch([korisnik])[0]

    def _to_out_batch(self, korisnici: list[Korisnik]) -> list[dict]:
        ids = [k.id for k in korisnici]
        roles = self.repo.batch_active_role_codes(ids)
        rasporedi = self.repo.batch_primary_active_rasporedi(ids)
        views = []
        for k in korisnici:
            raspored = rasporedi.get(k.id)
            views.append(
                {
                    "id": k.id,
                    "platni_broj": k.platni_broj,
                    "ime": k.ime,
                    "prezime": k.prezime,
                    "broj_telefona": k.broj_telefona,
                    "status_zaposlenja": k.status_zaposlenja,
                    "status_naloga": k.status_naloga,
                    "zakljucan": k.zakljucan == "D",
                    "broj_neuspesnih_prijava": k.broj_neuspesnih_prijava or 0,
                    "obavezna_promena_lozinke": k.obavezna_promena_lozinke == "D",
                    "telefon_potvrdjen": k.telefon_potvrdjen == "D",
                    "datum_poslednje_prijave": k.datum_poslednje_prijave,
                    "datum_sinhronizacije": k.datum_sinhronizacije,
                    "orgjed_sifra": raspored.orgjed_sifra if raspored else None,
                    "radno_mesto_sifra": raspored.radno_mesto_sifra if raspored else None,
                    "uloge": sorted(roles.get(k.id, [])),
                }
            )
        return views

    def _to_out(self, korisnik: Korisnik) -> dict:
        return self._to_out_batch([korisnik])[0]

    # --------------------------------------------------------------- mutacije
    def _load_target_or_raise(self, actor: Korisnik, user_id: int) -> Korisnik:
        target = self.repo.get_by_id_for_update(user_id)
        if target is None:
            raise UserNotFoundError()
        if target.id == actor.id:
            raise AdminSelfActionNotAllowedError()
        return target

    def lock(self, actor: Korisnik, user_id: int) -> dict:
        try:
            target = self._load_target_or_raise(actor, user_id)
            # Sesije/FCM tokeni se opozivaju/deaktiviraju UVEK (i ako je korisnik vec
            # zakljucan) - moguce je da su nastali NAKON prethodnog lock-a. Promena
            # glavnog stanja (ZAKLJUCAN/DATUM) i audit idu samo kada se stanje stvarno menja.
            self.session_repo.revoke_active_sessions_for_user(target.id, REVOKE_REASON_ADMIN_LOCK)
            self.push_token_repo.deactivate_all_for_user(target.id)
            if target.zakljucan != "D":
                target.zakljucan = "D"
                target.datum_zakljucavanja = datetime.datetime.now()
                self.audit_service.log(
                    AuditAction.ADMIN_USER_LOCKED,
                    korisnik_id=actor.id,
                    platni_broj=actor.platni_broj,
                    tip_entiteta="KORISNIK",
                    entitet_id=str(target.id),
                )
            result = self._to_out(target)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def unlock(self, actor: Korisnik, user_id: int) -> dict:
        try:
            target = self._load_target_or_raise(actor, user_id)
            # Krajnje stanje se UVEK postavlja (npr. korisnik moze imati neuspesne
            # pokusaje ili DATUM_ZAKLJUCAVANJA a da ZAKLJUCAN vec bude 'N'). Audit
            # ide samo ako se bar jedno od polja stvarno promenilo.
            changed = (
                target.zakljucan != "N"
                or target.datum_zakljucavanja is not None
                or (target.broj_neuspesnih_prijava or 0) != 0
            )
            target.zakljucan = "N"
            target.datum_zakljucavanja = None
            target.broj_neuspesnih_prijava = 0
            if changed:
                self.audit_service.log(
                    AuditAction.ADMIN_USER_UNLOCKED,
                    korisnik_id=actor.id,
                    platni_broj=actor.platni_broj,
                    tip_entiteta="KORISNIK",
                    entitet_id=str(target.id),
                )
            result = self._to_out(target)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def deactivate(self, actor: Korisnik, user_id: int) -> dict:
        try:
            target = self._load_target_or_raise(actor, user_id)
            # Sesije/FCM tokeni se opozivaju/deaktiviraju UVEK, cak i ako je nalog
            # vec onemogucen (mogli su nastati nakon prethodne deaktivacije). Promena
            # STATUS_NALOGA i audit idu samo kada se stanje stvarno menja.
            self.session_repo.revoke_active_sessions_for_user(target.id, REVOKE_REASON_ADMIN_DEACTIVATE)
            self.push_token_repo.deactivate_all_for_user(target.id)
            if target.status_naloga != STATUS_NALOGA_ONEMOGUCEN:
                # STATUS_ZAPOSLENJA se NIKADA ne dira ovde - njime upravlja Oracle HR procedura.
                target.status_naloga = STATUS_NALOGA_ONEMOGUCEN
                self.audit_service.log(
                    AuditAction.ADMIN_USER_DEACTIVATED,
                    korisnik_id=actor.id,
                    platni_broj=actor.platni_broj,
                    tip_entiteta="KORISNIK",
                    entitet_id=str(target.id),
                )
            result = self._to_out(target)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def reset_password(self, actor: Korisnik, user_id: int) -> dict:
        # Jedna try/rollback granica za: SELECT FOR UPDATE, self/not-found proveru,
        # validaciju preduslova i SMS poziv. Bilo koja necommitovana greska u ovom
        # bloku (uklj. izuzetak SMS providera) mora pozvati rollback.
        try:
            target = self._load_target_or_raise(actor, user_id)
            if (
                target.status_zaposlenja != STATUS_ZAPOSLENJA_AKTIVAN
                or target.status_naloga != STATUS_NALOGA_OMOGUCEN
            ):
                raise ValidationBusinessError(
                    "Reset lozinke je dozvoljen samo za aktivnog zaposlenog sa omogućenim nalogom."
                )
            if not is_valid_local_mobile_phone(target.broj_telefona):
                raise ValidationBusinessError("Korisnik nema validan broj telefona za slanje SMS-a.")

            # Generisi privremenu lozinku i pokusaj SMS PRE bilo kakve izmene stanja.
            temporary_password = generate_temporary_password()
            message = f"Vaša nova privremena lozinka za PULS je: {temporary_password}"
            sms_sent = self.sms_provider.send_sms(target.broj_telefona, message)
        except Exception:
            self.db.rollback()
            raise

        if not sms_sent:
            # SMS nije uspeo: ne diraj hash/sesije/tokene. Upisi i commituj SAMO
            # bezbedan failure audit (bez lozinke/SMS sadrzaja). Bez rollback-a posle
            # uspesnog commit-a.
            try:
                self.audit_service.log(
                    AuditAction.ADMIN_USER_PASSWORD_RESET_FAILED,
                    korisnik_id=actor.id,
                    platni_broj=actor.platni_broj,
                    tip_entiteta="KORISNIK",
                    entitet_id=str(target.id),
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            raise SmsDeliveryFailedError()

        try:
            # Tek nakon uspesnog SMS-a upisuj hash i resetuj stanje naloga.
            target.lozinka_hash = hash_password(temporary_password)
            target.obavezna_promena_lozinke = "D"
            target.broj_neuspesnih_prijava = 0
            target.zakljucan = "N"
            target.datum_zakljucavanja = None
            self.session_repo.revoke_active_sessions_for_user(
                target.id, REVOKE_REASON_ADMIN_PASSWORD_RESET
            )
            self.push_token_repo.deactivate_all_for_user(target.id)
            self.audit_service.log(
                AuditAction.ADMIN_USER_PASSWORD_RESET,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="KORISNIK",
                entitet_id=str(target.id),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"message": "Nova privremena lozinka je poslata korisniku SMS porukom."}

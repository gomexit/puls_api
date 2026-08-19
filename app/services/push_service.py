"""Logika push worker-a: obrada PENDING isporuka i slanje kroz FcmProvider.

Push je DODATNI kanal - Oracle Inbox ostaje izvor istine. SENT znaci samo da je
FCM prihvatio poruku (nije potvrda dostave uredjaju). Token/tajne se ne loguju."""

import datetime
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.security import hash_push_token
from app.models.push import (
    PUSH_STATUS_FAILED,
    PUSH_STATUS_PENDING,
    PUSH_STATUS_SENT,
    PUSH_STATUS_SKIPPED,
)
from app.repositories.korisnik_repository import KorisnikRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.push_delivery_repository import PushDeliveryRepository
from app.repositories.push_token_repository import PushTokenRepository
from app.repositories.session_repository import SessionRepository
from app.services.fcm_provider import (
    SEND_INVALID_TOKEN,
    SEND_OK,
    SEND_TRANSIENT,
    FcmProvider,
)

logger = logging.getLogger("puls.push")

# Ako korisnik jos nema (validan) token, isporuka ostaje PENDING i proba se ponovo
# kasnije (npr. posle registracije tokena) - bez trosenja pokusaja.
NO_TOKEN_BACKOFF_MIN = 30
# Gornja granica eksponencijalnog backoff-a za transient/error greske.
MAX_BACKOFF_MIN = 60
# FCM dozvoljava TTL najvise 28 dana (2.419.200s). Podrazumevani rok obavestenja
# je 30 dana, pa se TTL poslat provideru ogranicava na ovaj max - DATUM_ISTEKA
# samog obavestenja se NE menja, samo se TTL poruke krati.
FCM_MAX_TTL_SECONDS = 28 * 24 * 60 * 60


def _retry_backoff(attempts: int) -> datetime.timedelta:
    return datetime.timedelta(minutes=min(MAX_BACKOFF_MIN, 2 ** max(0, attempts - 1)))


class PushDeliveryWorker:
    def __init__(
        self,
        db: Session,
        fcm_provider: FcmProvider,
        max_attempts: int,
        delivery_repository: PushDeliveryRepository | None = None,
        token_repository: PushTokenRepository | None = None,
        notification_repository: NotificationRepository | None = None,
        korisnik_repository: KorisnikRepository | None = None,
        session_repository: SessionRepository | None = None,
        now_fn: Callable[[], datetime.datetime] = datetime.datetime.now,
    ):
        self.db = db
        self.fcm = fcm_provider
        self.max_attempts = max_attempts
        self.delivery_repo = delivery_repository or PushDeliveryRepository(db)
        self.token_repo = token_repository or PushTokenRepository(db)
        self.notif_repo = notification_repository or NotificationRepository(db)
        self.korisnik_repo = korisnik_repository or KorisnikRepository(db)
        self.session_repo = session_repository or SessionRepository(db)
        self._now = now_fn

    def process_batch(self, batch_size: int) -> dict:
        """Preuzmi do batch_size PENDING redova i obradi svaki. Greska jedne poruke
        (rollback + log) ne zaustavlja ostale. Commit po poruci."""
        now = self._now()
        batch = self.delivery_repo.claim_ready_batch(now, batch_size)
        summary = {
            "processed": 0, "sent": 0, "retry": 0, "failed": 0, "skipped": 0,
            "no_token": 0, "no_session": 0,
        }
        for red in batch:
            # Sacuvaj ID-jeve PRE obrade/rollback-a. Session.rollback() ekspajruje
            # ORM instance - naknadni pristup atributima (npr. u logger pozivu ispod)
            # bi pokrenuo NOV DB upit i mogao prekinuti ceo batch. Loguj SAMO ove
            # vec sacuvane primitivne vrednosti, nikad atribute objekta posle rollback-a.
            delivery_id = red.id
            notification_id = red.obavestenje_id
            try:
                outcome = self._process_one(red)
                self.db.commit()
                summary["processed"] += 1
                summary[outcome] = summary.get(outcome, 0) + 1
            except Exception:
                self.db.rollback()
                # Bezbedan log: samo ID-jevi (sacuvani gore), bez tokena/telefona/sadrzaja.
                logger.exception(
                    "Push isporuka nije obradjena (delivery_id=%s, notification_id=%s)",
                    delivery_id, notification_id,
                )
        return summary

    def _process_one(self, red) -> str:
        now = self._now()

        # 1) Obavestenje mora biti trenutno dostupno (PUBLISHED, u periodu).
        #    Isteklo/arhivirano -> SKIPPED (bez FCM poziva).
        obav = self.notif_repo.get_available_notification(red.obavestenje_id, now)
        if obav is None:
            return self._skip(red, now, "NOTIF_UNAVAILABLE")

        # 2) Korisnik mora biti aktivan/omogucen/nezakljucan i i dalje primalac.
        korisnik = self.korisnik_repo.get_by_id(red.korisnik_id)
        if (
            korisnik is None
            or korisnik.status_zaposlenja != "AKTIVAN"
            or korisnik.status_naloga != "OMOGUCEN"
            or korisnik.zakljucan == "D"
        ):
            return self._skip(red, now, "USER_INACTIVE")
        if not self.notif_repo.recipient_exists(red.obavestenje_id, red.korisnik_id):
            return self._skip(red, now, "NOT_RECIPIENT")

        # 3) Aktivan token. Ako ga nema -> ostaje PENDING (proba kasnije, bez trosenja pokusaja).
        token = self.token_repo.get_active_for_user(red.korisnik_id)
        if token is None:
            red.datum_sledeceg_pokusaja = now + datetime.timedelta(minutes=NO_TOKEN_BACKOFF_MIN)
            red.datum_poslednjeg_pokusaja = now
            red.poslednji_error_code = "NO_TOKEN"
            red.status = PUSH_STATUS_PENDING
            return "no_token"

        # 3b) Token uredjaja mora imati aktivnu, neisteklu sesiju (npr. logout na tom
        # uredjaju posle registracije tokena ostavlja "sirotu" token bez validne sesije).
        # Ako nema validne sesije: deaktiviraj token, NE salji FCM, ostavi PENDING
        # (bez trosenja pokusaja) - nova prijava/registracija tokena omogucava slanje kasnije.
        if not self.session_repo.has_active_session_for_device(red.korisnik_id, token.uredjaj_id, now):
            self.token_repo.deactivate_user_device(red.korisnik_id, token.uredjaj_id)
            red.datum_sledeceg_pokusaja = now + datetime.timedelta(minutes=NO_TOKEN_BACKOFF_MIN)
            red.datum_poslednjeg_pokusaja = now
            red.poslednji_error_code = "NO_ACTIVE_SESSION"
            red.status = PUSH_STATUS_PENDING
            return "no_session"

        # 4) TTL = preostalo vreme do isteka (ogranicen na FCM max 28 dana); ne salji
        # ako je vec proslo. DATUM_ISTEKA samog obavestenja se NE menja.
        remaining_seconds = 0
        if obav.datum_isteka is not None:
            remaining_seconds = int((obav.datum_isteka - now).total_seconds())
        if remaining_seconds <= 0:
            return self._skip(red, now, "EXPIRED")
        ttl_seconds = min(remaining_seconds, FCM_MAX_TTL_SECONDS)

        data = {
            "notification_id": str(obav.id),
            "title": obav.naslov or "",
            "body": obav.kratak_tekst or "",
            "category": obav.kategorija_sifra or "",
        }

        result = self.fcm.send(token.fcm_token, data, ttl_seconds)

        if result.status == SEND_OK:
            red.status = PUSH_STATUS_SENT
            red.datum_slanja = now
            red.datum_poslednjeg_pokusaja = now
            red.broj_pokusaja = (red.broj_pokusaja or 0) + 1
            red.poslednji_error_code = None
            return "sent"

        if result.status == SEND_INVALID_TOKEN:
            # Deaktiviraj token; isporuka ostaje PENDING (moze posle re-registracije).
            self.token_repo.deactivate_token_hash(hash_push_token(token.fcm_token))
            red.datum_sledeceg_pokusaja = now + datetime.timedelta(minutes=NO_TOKEN_BACKOFF_MIN)
            red.datum_poslednjeg_pokusaja = now
            red.poslednji_error_code = (result.error_code or "INVALID_TOKEN")[:100]
            red.status = PUSH_STATUS_PENDING
            return "no_token"

        # Transient/error -> retry uz backoff; posle max pokusaja -> FAILED.
        red.broj_pokusaja = (red.broj_pokusaja or 0) + 1
        red.datum_poslednjeg_pokusaja = now
        red.poslednji_error_code = (result.error_code or result.status)[:100]
        if red.broj_pokusaja >= self.max_attempts:
            red.status = PUSH_STATUS_FAILED
            red.datum_sledeceg_pokusaja = None
            return "failed"
        red.status = PUSH_STATUS_PENDING
        red.datum_sledeceg_pokusaja = now + _retry_backoff(red.broj_pokusaja)
        return "retry" if result.status == SEND_TRANSIENT else "retry"

    def _skip(self, red, now, code: str) -> str:
        red.status = PUSH_STATUS_SKIPPED
        red.datum_poslednjeg_pokusaja = now
        red.datum_sledeceg_pokusaja = None
        red.poslednji_error_code = code[:100]
        return "skipped"

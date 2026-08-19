import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import hash_push_token
from app.models.push import PushToken


class PushTokenRepository:
    """Pristup PULS_PUSH_TOKENI. Pun FCM token se NE loguje; za pretragu/jedinstvenost
    koristi se SHA-256 hash. Ne vraca token u nijedan API response."""

    def __init__(self, db: Session):
        self.db = db

    def get_active_for_user(self, korisnik_id: int) -> PushToken | None:
        stmt = select(PushToken).where(
            PushToken.korisnik_id == korisnik_id, PushToken.aktivan == "D"
        )
        return self.db.execute(stmt).scalars().first()

    def _get_for_user_device(self, korisnik_id: int, uredjaj_id: str) -> PushToken | None:
        stmt = select(PushToken).where(
            PushToken.korisnik_id == korisnik_id, PushToken.uredjaj_id == uredjaj_id
        )
        return self.db.execute(stmt).scalars().first()

    def upsert(self, korisnik_id: int, uredjaj_id: str, fcm_token: str, app_version: str | None) -> PushToken:
        """Registruje/azurira token za (korisnik, uredjaj). Prvo deaktivira sve druge
        tokene korisnika (jedan aktivan uredjaj) i sve redove sa istim TOKEN_HASH
        (isti fizicki uredjaj kod drugog korisnika), pa reaktivira/kreira ovaj."""
        now = datetime.datetime.now()
        token_hash = hash_push_token(fcm_token)

        # 1) Deaktiviraj sve ostale aktivne tokene ovog korisnika (drugi uredjaji).
        self.db.execute(
            update(PushToken)
            .where(
                PushToken.korisnik_id == korisnik_id,
                PushToken.uredjaj_id != uredjaj_id,
                PushToken.aktivan == "D",
            )
            .values(aktivan="N", datum_deaktivacije=now, datum_izmene=now)
        )
        # 2) Deaktiviraj isti token registrovan drugde (isti fizicki uredjaj, drugi nalog).
        self.db.execute(
            update(PushToken)
            .where(
                PushToken.token_hash == token_hash,
                PushToken.korisnik_id != korisnik_id,
                PushToken.aktivan == "D",
            )
            .values(aktivan="N", datum_deaktivacije=now, datum_izmene=now)
        )

        existing = self._get_for_user_device(korisnik_id, uredjaj_id)
        if existing is not None:
            existing.fcm_token = fcm_token
            existing.token_hash = token_hash
            existing.app_version = app_version
            existing.aktivan = "D"
            existing.datum_deaktivacije = None
            existing.datum_izmene = now
            existing.datum_poslednje_registracije = now
            self.db.flush()
            return existing

        token = PushToken(
            korisnik_id=korisnik_id,
            uredjaj_id=uredjaj_id,
            fcm_token=fcm_token,
            token_hash=token_hash,
            aktivan="D",
            app_version=app_version,
            datum_kreiranja=now,
            datum_poslednje_registracije=now,
        )
        self.db.add(token)
        self.db.flush()
        return token

    def deactivate_user_device(self, korisnik_id: int, uredjaj_id: str) -> int:
        now = datetime.datetime.now()
        res = self.db.execute(
            update(PushToken)
            .where(
                PushToken.korisnik_id == korisnik_id,
                PushToken.uredjaj_id == uredjaj_id,
                PushToken.aktivan == "D",
            )
            .values(aktivan="N", datum_deaktivacije=now, datum_izmene=now)
        )
        return res.rowcount or 0

    def deactivate_all_for_user(self, korisnik_id: int) -> int:
        now = datetime.datetime.now()
        res = self.db.execute(
            update(PushToken)
            .where(PushToken.korisnik_id == korisnik_id, PushToken.aktivan == "D")
            .values(aktivan="N", datum_deaktivacije=now, datum_izmene=now)
        )
        return res.rowcount or 0

    def deactivate_token_hash(self, token_hash: str) -> int:
        """Deaktivira token po hash-u (npr. FCM prijavi unregistered/invalid token)."""
        now = datetime.datetime.now()
        res = self.db.execute(
            update(PushToken)
            .where(PushToken.token_hash == token_hash, PushToken.aktivan == "D")
            .values(aktivan="N", datum_deaktivacije=now, datum_izmene=now)
        )
        return res.rowcount or 0

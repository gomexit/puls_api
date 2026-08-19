import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.korisnicka_sesija import KorisnickaSesija


class SessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_token_hash(self, token_hash: str) -> KorisnickaSesija | None:
        stmt = select(KorisnickaSesija).where(KorisnickaSesija.token_hash == token_hash)
        return self.db.execute(stmt).scalar_one_or_none()

    def has_active_session_for_device(
        self, korisnik_id: int, uredjaj_id: str, now: datetime.datetime
    ) -> bool:
        """True ako korisnik ima AKTIVNA='D' sesiju za dati uredjaj koja jos nije
        istekla. Push worker koristi ovo da ne salje FCM uredjaju koji vise nema
        vazecu sesiju (npr. logout na tom uredjaju posle registracije tokena)."""
        stmt = select(func.count()).select_from(KorisnickaSesija).where(
            KorisnickaSesija.korisnik_id == korisnik_id,
            KorisnickaSesija.uredjaj_id == uredjaj_id,
            KorisnickaSesija.aktivna == "D",
            or_(KorisnickaSesija.datum_isteka.is_(None), KorisnickaSesija.datum_isteka > now),
        )
        return int(self.db.execute(stmt).scalar_one()) > 0

    def revoke_active_sessions_for_user(self, korisnik_id: int, razlog: str) -> None:
        now = datetime.datetime.now()
        stmt = (
            update(KorisnickaSesija)
            .where(KorisnickaSesija.korisnik_id == korisnik_id, KorisnickaSesija.aktivna == "D")
            .values(aktivna="N", datum_ponistavanja=now, razlog_ponistavanja=razlog)
        )
        self.db.execute(stmt)

    def create_session(
        self,
        korisnik_id: int,
        token_hash: str,
        uredjaj_id: str,
        naziv_uredjaja: str | None,
        ttl_days: int,
        ip_adresa: str | None,
        korisnicki_agent: str | None,
    ) -> KorisnickaSesija:
        now = datetime.datetime.now()
        sesija = KorisnickaSesija(
            korisnik_id=korisnik_id,
            token_hash=token_hash,
            uredjaj_id=uredjaj_id,
            naziv_uredjaja=naziv_uredjaja,
            aktivna="D",
            datum_izdavanja=now,
            datum_isteka=now + datetime.timedelta(days=ttl_days),
            poslednja_aktivnost=now,
            ip_adresa=ip_adresa,
            korisnicki_agent=korisnicki_agent,
            datum_kreiranja=now,
        )
        self.db.add(sesija)
        self.db.flush()
        return sesija

    def revoke_session(self, sesija: KorisnickaSesija, razlog: str) -> None:
        sesija.aktivna = "N"
        sesija.datum_ponistavanja = datetime.datetime.now()
        sesija.razlog_ponistavanja = razlog

    def touch_activity(self, sesija: KorisnickaSesija) -> None:
        sesija.poslednja_aktivnost = datetime.datetime.now()

"""Read/write pristup PULS_ANKETA_AUTOMATIKA + upit za kvalifikovane kandidate
(PULS_KORISNICI) za onboarding dodelu ankete. Prati stil SystemEventRepository/
SurveyRepository."""

import datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.anketa_ucesce import AnketaAutomatika, AnketaUcesce
from app.models.korisnik import (
    STATUS_NALOGA_OMOGUCEN,
    STATUS_ZAPOSLENJA_AKTIVAN,
    Korisnik,
)


class OnboardingAutomationRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- Pravila (PULS_ANKETA_AUTOMATIKA) ---
    def list_all(self) -> list[AnketaAutomatika]:
        return list(
            self.db.execute(select(AnketaAutomatika).order_by(AnketaAutomatika.id)).scalars().all()
        )

    def get(self, automatika_id: int) -> AnketaAutomatika | None:
        return self.db.get(AnketaAutomatika, automatika_id)

    def get_by_survey_id(self, anketa_id: int) -> AnketaAutomatika | None:
        stmt = select(AnketaAutomatika).where(AnketaAutomatika.anketa_id == anketa_id)
        return self.db.execute(stmt).scalars().first()

    def get_for_update(self, automatika_id: int) -> AnketaAutomatika | None:
        stmt = (
            select(AnketaAutomatika)
            .where(AnketaAutomatika.id == automatika_id)
            .with_for_update()
        )
        return self.db.execute(stmt).scalars().first()

    def find_active_rules(self) -> list[AnketaAutomatika]:
        stmt = select(AnketaAutomatika).where(AnketaAutomatika.aktivna == "D").order_by(
            AnketaAutomatika.id
        )
        return list(self.db.execute(stmt).scalars().all())

    def add(self, automatika: AnketaAutomatika) -> AnketaAutomatika:
        self.db.add(automatika)
        self.db.flush()
        return automatika

    # --- Kandidati (PULS_KORISNICI), jedan upit bez N+1 ---
    def find_qualified_candidates(
        self, pravilo: AnketaAutomatika, now: datetime.datetime
    ) -> list[Korisnik]:
        """Korisnici koji su AKTIVAN/OMOGUCEN, imaju DATUM_ZAPOSLENJA >=
        DATUM_PRIMENE_OD pravila, cije DATUM_ZAPOSLENJA+DANI_OD_ZAPOSLENJA prozor
        [dostupnost, dostupnost+rok_dana) sadrzi 'now' (kalendarski dan, TRUNC), i za
        koje JOS NE POSTOJI PULS_ANKETA_UCESCA red za ovu anketu (korelisani NOT EXISTS
        umesto N+1 poziva existing_participation_exists po kandidatu)."""
        today = now.date()
        milestone_offset = datetime.timedelta(days=pravilo.dani_od_zaposlenja)
        window_len = datetime.timedelta(days=pravilo.rok_dana)
        already_participates = (
            select(AnketaUcesce.id)
            .where(
                AnketaUcesce.anketa_id == pravilo.anketa_id,
                AnketaUcesce.korisnik_id == Korisnik.id,
            )
            .correlate(Korisnik)
        )
        stmt = select(Korisnik).where(
            Korisnik.status_zaposlenja == STATUS_ZAPOSLENJA_AKTIVAN,
            Korisnik.status_naloga == STATUS_NALOGA_OMOGUCEN,
            Korisnik.datum_zaposlenja.is_not(None),
            Korisnik.datum_zaposlenja >= pravilo.datum_primene_od,
            Korisnik.datum_zaposlenja + milestone_offset <= today,
            Korisnik.datum_zaposlenja + milestone_offset + window_len > today,
            sa.not_(already_participates.exists()),
        )
        return list(self.db.execute(stmt).scalars().all())

    def existing_participation_exists(self, anketa_id: int, korisnik_id: int) -> bool:
        stmt = select(AnketaUcesce.id).where(
            AnketaUcesce.anketa_id == anketa_id, AnketaUcesce.korisnik_id == korisnik_id
        )
        return self.db.execute(stmt).scalars().first() is not None

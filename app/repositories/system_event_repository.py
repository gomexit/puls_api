"""Read/write pristup PULS_SISTEMSKI_DOGADJAJI + read-only resolucija resursa
(anketa/ciklus/ideja) i primalaca za sistemski notification worker."""

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.anketa import (
    ANKETA_STATUS_ACTIVE,
    ANKETA_STATUS_SCHEDULED,
    UCESCE_SUBMITTED,
    Anketa,
)
from app.models.anketa_ucesce import AnketaUcesce
from app.models.idea_ciklus import CIKLUS_STATUS_AKTIVAN, IdeaCiklus
from app.models.ideja import Ideja
from app.models.korisnik import Korisnik
from app.models.sistemski_dogadjaj import DOGADJAJ_STATUS_PENDING, SistemskiDogadjaj


class SystemEventRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ enqueue
    def enqueue_if_absent(
        self,
        kljuc: str,
        tip: str,
        resurs_id: int | None,
        vrednost: str | None,
        now: datetime.datetime,
    ) -> bool:
        """Idempotentan upis: True ako je nov dogadjaj kreiran, False ako
        DOGADJAJ_KLJUC vec postoji. BEZ commit-a - poziva se unutar transakcije
        poslovne operacije (ili worker discovery transakcije)."""
        existing = self.db.execute(
            select(SistemskiDogadjaj.id).where(SistemskiDogadjaj.dogadjaj_kljuc == kljuc)
        ).scalar_one_or_none()
        if existing is not None:
            return False
        self.db.add(
            SistemskiDogadjaj(
                dogadjaj_kljuc=kljuc,
                tip_dogadjaja=tip,
                resurs_id=resurs_id,
                vrednost=vrednost,
                status=DOGADJAJ_STATUS_PENDING,
                broj_pokusaja=0,
                datum_sledeceg_pokusaja=now,
                datum_kreiranja=now,
            )
        )
        self.db.flush()
        return True

    # -------------------------------------------------------------- worker: claim
    def list_ready_ids(self, now: datetime.datetime, limit: int) -> list[int]:
        stmt = (
            select(SistemskiDogadjaj.id)
            .where(
                SistemskiDogadjaj.status == DOGADJAJ_STATUS_PENDING,
                (SistemskiDogadjaj.datum_sledeceg_pokusaja.is_(None))
                | (SistemskiDogadjaj.datum_sledeceg_pokusaja <= now),
            )
            .order_by(
                SistemskiDogadjaj.datum_sledeceg_pokusaja.asc().nulls_first(),
                SistemskiDogadjaj.id.asc(),
            )
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_for_update(self, event_id: int) -> SistemskiDogadjaj | None:
        stmt = (
            select(SistemskiDogadjaj)
            .where(SistemskiDogadjaj.id == event_id)
            .with_for_update()
        )
        return self.db.execute(stmt).scalars().first()

    # -------------------------------------------------------------------- discovery
    def find_scheduled_surveys_now_active(self, now: datetime.datetime) -> list[Anketa]:
        """SCHEDULED ankete cija je DATUM_POCETKA vec prosla (vremenom postale
        efektivno dostupne, bez direktnog admin poziva na ACTIVE)."""
        stmt = select(Anketa).where(
            Anketa.status == ANKETA_STATUS_SCHEDULED,
            Anketa.datum_pocetka <= now,
            Anketa.datum_zavrsetka > now,
        )
        return list(self.db.execute(stmt).scalars().all())

    def find_surveys_expiring_within(
        self, now: datetime.datetime, window_end: datetime.datetime
    ) -> list[Anketa]:
        stmt = select(Anketa).where(
            Anketa.status.in_((ANKETA_STATUS_SCHEDULED, ANKETA_STATUS_ACTIVE)),
            Anketa.datum_pocetka <= now,
            Anketa.datum_zavrsetka > now,
            Anketa.datum_zavrsetka <= window_end,
        )
        return list(self.db.execute(stmt).scalars().all())

    def find_active_surveys_now_expired(self, now: datetime.datetime) -> list[Anketa]:
        """ACTIVE ankete cija je DATUM_ZAVRSETKA vec prosla (vremenom istekle,
        bez direktnog admin poziva na CLOSED)."""
        stmt = select(Anketa).where(
            Anketa.status == ANKETA_STATUS_ACTIVE,
            Anketa.datum_zavrsetka <= now,
        )
        return list(self.db.execute(stmt).scalars().all())

    def find_cycles_expiring_within(
        self, now: datetime.datetime, window_end: datetime.datetime
    ) -> list[IdeaCiklus]:
        stmt = select(IdeaCiklus).where(
            IdeaCiklus.status == CIKLUS_STATUS_AKTIVAN,
            IdeaCiklus.datum_zavrsetka > now,
            IdeaCiklus.datum_zavrsetka <= window_end,
        )
        return list(self.db.execute(stmt).scalars().all())

    # -------------------------------------------------------- resolucija resursa
    def get_survey(self, survey_id: int) -> Anketa | None:
        return self.db.get(Anketa, survey_id)

    def get_cycle(self, cycle_id: int) -> IdeaCiklus | None:
        return self.db.get(IdeaCiklus, cycle_id)

    def get_idea(self, idea_id: int) -> Ideja | None:
        return self.db.get(Ideja, idea_id)

    def get_ucesce(self, ucesce_id: int) -> AnketaUcesce | None:
        return self.db.get(AnketaUcesce, ucesce_id)

    def get_korisnik(self, korisnik_id: int) -> Korisnik | None:
        return self.db.get(Korisnik, korisnik_id)

    def survey_participant_ids(self, survey_id: int) -> set[int]:
        stmt = select(AnketaUcesce.korisnik_id).where(AnketaUcesce.anketa_id == survey_id)
        return set(self.db.execute(stmt).scalars().all())

    def survey_participant_ids_not_submitted(self, survey_id: int) -> set[int]:
        stmt = select(AnketaUcesce.korisnik_id).where(
            AnketaUcesce.anketa_id == survey_id, AnketaUcesce.status != UCESCE_SUBMITTED
        )
        return set(self.db.execute(stmt).scalars().all())

    def user_ids_with_idea_in_cycle(self, cycle_id: int) -> set[int]:
        stmt = select(Ideja.korisnik_id).where(Ideja.ciklus_id == cycle_id).distinct()
        return set(self.db.execute(stmt).scalars().all())

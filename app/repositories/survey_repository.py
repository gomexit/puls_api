import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.anketa import (
    ANKETA_STATUS_ARCHIVED,
    UCESCE_SUBMITTED,
    Anketa,
    AnketaTip,
)
from app.models.anketa_predaja import AnketaOdgovor, AnketaOdgovorOpcija, AnketaPredaja
from app.models.anketa_struktura import (
    AnketaCilj,
    AnketaOpcija,
    AnketaPitanje,
    AnketaSekcija,
    AnketaUslovVrednost,
)
from app.models.anketa_ucesce import AnketaNacrtOdgovor, AnketaNacrtOpcija, AnketaUcesce


class SurveyRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- Tipovi ---
    def get_type(self, sifra: str) -> AnketaTip | None:
        return self.db.get(AnketaTip, sifra)

    def list_types(self) -> list[AnketaTip]:
        return list(self.db.execute(select(AnketaTip).order_by(AnketaTip.sifra)).scalars().all())

    def add_type(self, tip: AnketaTip) -> AnketaTip:
        self.db.add(tip)
        self.db.flush()
        return tip

    # --- Anketa ---
    def get_survey(self, anketa_id: int) -> Anketa | None:
        return self.db.get(Anketa, anketa_id)

    def add_survey(self, anketa: Anketa) -> Anketa:
        self.db.add(anketa)
        self.db.flush()
        return anketa

    def list_surveys(
        self,
        status: str | None,
        tip_sifra: str | None,
        datum_od: datetime.datetime | None,
        datum_do: datetime.datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Anketa], int]:
        stmt = select(Anketa)
        if status is not None:
            stmt = stmt.where(Anketa.status == status)
        if tip_sifra is not None:
            stmt = stmt.where(Anketa.tip_sifra == tip_sifra)
        if datum_od is not None:
            stmt = stmt.where(Anketa.datum_zavrsetka >= datum_od)
        if datum_do is not None:
            stmt = stmt.where(Anketa.datum_pocetka <= datum_do)
        total = int(self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
        items = list(
            self.db.execute(
                stmt.order_by(Anketa.datum_kreiranja.desc(), Anketa.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        return items, total

    # --- Struktura (citanje) ---
    def get_sections(self, anketa_id: int) -> list[AnketaSekcija]:
        return list(
            self.db.execute(
                select(AnketaSekcija)
                .where(AnketaSekcija.anketa_id == anketa_id)
                .order_by(AnketaSekcija.redosled)
            )
            .scalars()
            .all()
        )

    def get_questions_for_survey(self, anketa_id: int) -> list[AnketaPitanje]:
        stmt = (
            select(AnketaPitanje)
            .join(AnketaSekcija, AnketaSekcija.id == AnketaPitanje.sekcija_id)
            .where(AnketaSekcija.anketa_id == anketa_id)
            .order_by(AnketaSekcija.redosled, AnketaPitanje.redosled)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_options_for_survey(self, anketa_id: int) -> list[AnketaOpcija]:
        stmt = (
            select(AnketaOpcija)
            .join(AnketaPitanje, AnketaPitanje.id == AnketaOpcija.pitanje_id)
            .join(AnketaSekcija, AnketaSekcija.id == AnketaPitanje.sekcija_id)
            .where(AnketaSekcija.anketa_id == anketa_id)
            .order_by(AnketaOpcija.pitanje_id, AnketaOpcija.redosled)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_uslov_values_for_survey(self, anketa_id: int) -> list[AnketaUslovVrednost]:
        stmt = (
            select(AnketaUslovVrednost)
            .join(AnketaPitanje, AnketaPitanje.id == AnketaUslovVrednost.pitanje_id)
            .join(AnketaSekcija, AnketaSekcija.id == AnketaPitanje.sekcija_id)
            .where(AnketaSekcija.anketa_id == anketa_id)
            .order_by(AnketaUslovVrednost.pitanje_id, AnketaUslovVrednost.redosled)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_targets(self, anketa_id: int) -> list[AnketaCilj]:
        return list(
            self.db.execute(
                select(AnketaCilj).where(AnketaCilj.anketa_id == anketa_id).order_by(AnketaCilj.id)
            )
            .scalars()
            .all()
        )

    # --- Struktura (pisanje) ---
    def add_section(self, sekcija: AnketaSekcija) -> AnketaSekcija:
        self.db.add(sekcija)
        self.db.flush()
        return sekcija

    def add_question(self, pitanje: AnketaPitanje) -> AnketaPitanje:
        self.db.add(pitanje)
        self.db.flush()
        return pitanje

    def add_option(self, opcija: AnketaOpcija) -> AnketaOpcija:
        self.db.add(opcija)
        self.db.flush()
        return opcija

    def add_uslov_value(self, vrednost: AnketaUslovVrednost) -> AnketaUslovVrednost:
        self.db.add(vrednost)
        self.db.flush()
        return vrednost

    def add_target(self, cilj: AnketaCilj) -> AnketaCilj:
        self.db.add(cilj)
        self.db.flush()
        return cilj

    def delete_structure(self, anketa_id: int) -> None:
        """Brise celu strukturu ankete (samo za DRAFT full-replace). Redosled postuje FK."""
        section_ids = select(AnketaSekcija.id).where(AnketaSekcija.anketa_id == anketa_id)
        question_ids = select(AnketaPitanje.id).where(AnketaPitanje.sekcija_id.in_(section_ids))
        # Prvo odvezi self-FK uslova da brisanje pitanja ne padne.
        self.db.execute(
            AnketaPitanje.__table__.update()
            .where(AnketaPitanje.sekcija_id.in_(section_ids))
            .values(USLOV_PITANJE_ID=None, USLOV_OPERATOR=None)
        )
        self.db.execute(
            delete(AnketaUslovVrednost).where(AnketaUslovVrednost.pitanje_id.in_(question_ids))
        )
        self.db.execute(delete(AnketaOpcija).where(AnketaOpcija.pitanje_id.in_(question_ids)))
        self.db.execute(delete(AnketaPitanje).where(AnketaPitanje.sekcija_id.in_(section_ids)))
        self.db.execute(delete(AnketaSekcija).where(AnketaSekcija.anketa_id == anketa_id))
        self.db.execute(delete(AnketaCilj).where(AnketaCilj.anketa_id == anketa_id))

    # --- Ucesce ---
    def get_ucesce(self, anketa_id: int, korisnik_id: int) -> AnketaUcesce | None:
        stmt = select(AnketaUcesce).where(
            AnketaUcesce.anketa_id == anketa_id, AnketaUcesce.korisnik_id == korisnik_id
        )
        return self.db.execute(stmt).scalars().first()

    def get_ucesce_for_update(self, anketa_id: int, korisnik_id: int) -> AnketaUcesce | None:
        stmt = (
            select(AnketaUcesce)
            .where(AnketaUcesce.anketa_id == anketa_id, AnketaUcesce.korisnik_id == korisnik_id)
            .with_for_update()
        )
        return self.db.execute(stmt).scalars().first()

    def add_ucesce(self, ucesce: AnketaUcesce) -> AnketaUcesce:
        self.db.add(ucesce)
        self.db.flush()
        return ucesce

    def existing_participant_ids(self, anketa_id: int) -> set[int]:
        stmt = select(AnketaUcesce.korisnik_id).where(AnketaUcesce.anketa_id == anketa_id)
        return set(self.db.execute(stmt).scalars().all())

    def list_user_surveys(self, korisnik_id: int) -> list[tuple[Anketa, AnketaUcesce]]:
        stmt = (
            select(Anketa, AnketaUcesce)
            .join(AnketaUcesce, AnketaUcesce.anketa_id == Anketa.id)
            .where(AnketaUcesce.korisnik_id == korisnik_id, Anketa.status != ANKETA_STATUS_ARCHIVED)
            .order_by(Anketa.datum_pocetka.desc(), Anketa.id.desc())
        )
        return [(row[0], row[1]) for row in self.db.execute(stmt).all()]

    def count_participants(self, anketa_id: int) -> int:
        return int(
            self.db.execute(
                select(func.count()).select_from(AnketaUcesce).where(
                    AnketaUcesce.anketa_id == anketa_id
                )
            ).scalar_one()
        )

    def count_submitted(self, anketa_id: int) -> int:
        return int(
            self.db.execute(
                select(func.count())
                .select_from(AnketaUcesce)
                .where(
                    AnketaUcesce.anketa_id == anketa_id,
                    AnketaUcesce.status == UCESCE_SUBMITTED,
                )
            ).scalar_one()
        )

    def count_questions(self, anketa_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(AnketaPitanje)
            .join(AnketaSekcija, AnketaSekcija.id == AnketaPitanje.sekcija_id)
            .where(AnketaSekcija.anketa_id == anketa_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    # --- Nacrt ---
    def get_draft_answers(self, anketa_id: int, korisnik_id: int) -> list[AnketaNacrtOdgovor]:
        stmt = select(AnketaNacrtOdgovor).where(
            AnketaNacrtOdgovor.anketa_id == anketa_id,
            AnketaNacrtOdgovor.korisnik_id == korisnik_id,
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_draft_options(self, nacrt_odgovor_ids: list[int]) -> list[AnketaNacrtOpcija]:
        if not nacrt_odgovor_ids:
            return []
        stmt = select(AnketaNacrtOpcija).where(
            AnketaNacrtOpcija.nacrt_odgovor_id.in_(nacrt_odgovor_ids)
        )
        return list(self.db.execute(stmt).scalars().all())

    def delete_draft(self, anketa_id: int, korisnik_id: int) -> None:
        answer_ids = select(AnketaNacrtOdgovor.id).where(
            AnketaNacrtOdgovor.anketa_id == anketa_id,
            AnketaNacrtOdgovor.korisnik_id == korisnik_id,
        )
        self.db.execute(
            delete(AnketaNacrtOpcija).where(AnketaNacrtOpcija.nacrt_odgovor_id.in_(answer_ids))
        )
        self.db.execute(
            delete(AnketaNacrtOdgovor).where(
                AnketaNacrtOdgovor.anketa_id == anketa_id,
                AnketaNacrtOdgovor.korisnik_id == korisnik_id,
            )
        )

    def add_draft_answer(self, odgovor: AnketaNacrtOdgovor) -> AnketaNacrtOdgovor:
        self.db.add(odgovor)
        self.db.flush()
        return odgovor

    def add_draft_option(self, opcija: AnketaNacrtOpcija) -> AnketaNacrtOpcija:
        self.db.add(opcija)
        return opcija

    # --- Predaja ---
    def add_submission(self, predaja: AnketaPredaja) -> AnketaPredaja:
        self.db.add(predaja)
        self.db.flush()
        return predaja

    def add_answer(self, odgovor: AnketaOdgovor) -> AnketaOdgovor:
        self.db.add(odgovor)
        self.db.flush()
        return odgovor

    def add_answer_option(self, opcija: AnketaOdgovorOpcija) -> AnketaOdgovorOpcija:
        self.db.add(opcija)
        return opcija

    def get_user_submission(self, anketa_id: int, korisnik_id: int) -> AnketaPredaja | None:
        stmt = select(AnketaPredaja).where(
            AnketaPredaja.anketa_id == anketa_id, AnketaPredaja.korisnik_id == korisnik_id
        )
        return self.db.execute(stmt).scalars().first()

    def get_final_answers(self, predaja_id: int) -> list[AnketaOdgovor]:
        stmt = select(AnketaOdgovor).where(AnketaOdgovor.predaja_id == predaja_id)
        return list(self.db.execute(stmt).scalars().all())

    def get_final_answer_options(self, odgovor_ids: list[int]) -> list[AnketaOdgovorOpcija]:
        if not odgovor_ids:
            return []
        stmt = select(AnketaOdgovorOpcija).where(AnketaOdgovorOpcija.odgovor_id.in_(odgovor_ids))
        return list(self.db.execute(stmt).scalars().all())
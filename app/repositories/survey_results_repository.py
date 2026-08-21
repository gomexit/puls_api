import datetime

from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.orm import Session

from app.models.anketa_predaja import AnketaOdgovor, AnketaOdgovorOpcija, AnketaPredaja
from app.models.anketa_ucesce import AnketaUcesce
from app.models.korisnik import Korisnik
from app.models.korisnik_raspored import KorisnikRaspored


class SurveyResultsRepository:
    """Read-only agregacije za admin SURVEY-RESULT modul.

    Iskljucivo FINALNE predaje/odgovore (PULS_ANKETA_PREDAJE/ODGOVORI/ODGOVOR_OPCIJE);
    nacrti (PULS_ANKETA_NACRT_*) se ovde NIKADA ne citaju.

    ANONIMNOST: statisticki upiti (ucesce_status_counts/answer_counts_by_question/
    option_choice_counts/boolean_counts/rating_value_counts) NIKADA ne selektuju
    PULS_ANKETA_PREDAJE.KORISNIK_ID niti joinuju predaju na PULS_ANKETA_UCESCA ili
    PULS_KORISNICI - AnketaPredaja se koristi SAMO da filtrira odgovore po ANKETA_ID
    (agregat), nikad da poveze pojedinacan odgovor sa identitetom."""

    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- odziv
    def ucesce_status_counts(self, survey_id: int) -> dict[str, int]:
        stmt = (
            select(AnketaUcesce.status, func.count())
            .where(AnketaUcesce.anketa_id == survey_id)
            .group_by(AnketaUcesce.status)
        )
        return {status_: int(cnt) for status_, cnt in self.db.execute(stmt).all()}

    # ------------------------------------------------------- statistika pitanja
    def answer_counts_by_question(self, survey_id: int) -> dict[int, int]:
        """Broj FINALNIH odgovora po pitanju (denominator za procente opcija)."""
        stmt = (
            select(AnketaOdgovor.pitanje_id, func.count())
            .select_from(AnketaOdgovor)
            .join(AnketaPredaja, AnketaPredaja.id == AnketaOdgovor.predaja_id)
            .where(AnketaPredaja.anketa_id == survey_id)
            .group_by(AnketaOdgovor.pitanje_id)
        )
        return {int(pid): int(cnt) for pid, cnt in self.db.execute(stmt).all()}

    def option_choice_counts(self, survey_id: int) -> dict[int, dict[int, int]]:
        """pitanje_id -> opcija_id -> broj_izbora (SINGLE_CHOICE/DROPDOWN/MULTI_CHOICE)."""
        stmt = (
            select(AnketaOdgovor.pitanje_id, AnketaOdgovorOpcija.opcija_id, func.count())
            .select_from(AnketaOdgovorOpcija)
            .join(AnketaOdgovor, AnketaOdgovor.id == AnketaOdgovorOpcija.odgovor_id)
            .join(AnketaPredaja, AnketaPredaja.id == AnketaOdgovor.predaja_id)
            .where(AnketaPredaja.anketa_id == survey_id)
            .group_by(AnketaOdgovor.pitanje_id, AnketaOdgovorOpcija.opcija_id)
        )
        result: dict[int, dict[int, int]] = {}
        for pid, oid, cnt in self.db.execute(stmt).all():
            result.setdefault(int(pid), {})[int(oid)] = int(cnt)
        return result

    def boolean_counts(self, survey_id: int) -> dict[int, dict[str, int]]:
        """pitanje_id -> {'D': broj, 'N': broj} za BOOLEAN pitanja."""
        stmt = (
            select(AnketaOdgovor.pitanje_id, AnketaOdgovor.logicka, func.count())
            .select_from(AnketaOdgovor)
            .join(AnketaPredaja, AnketaPredaja.id == AnketaOdgovor.predaja_id)
            .where(AnketaPredaja.anketa_id == survey_id, AnketaOdgovor.logicka.is_not(None))
            .group_by(AnketaOdgovor.pitanje_id, AnketaOdgovor.logicka)
        )
        result: dict[int, dict[str, int]] = {}
        for pid, logicka, cnt in self.db.execute(stmt).all():
            result.setdefault(int(pid), {})[logicka] = int(cnt)
        return result

    def rating_value_counts(self, survey_id: int) -> dict[int, dict[int, int]]:
        """pitanje_id -> {vrednost: broj} za RATING_1_5/RATING_1_10. Frekventna tabela
        je dovoljna za prosek/medijanu/min/max/raspodelu bez ucitavanja pojedinacnih redova."""
        stmt = (
            select(AnketaOdgovor.pitanje_id, AnketaOdgovor.broj, func.count())
            .select_from(AnketaOdgovor)
            .join(AnketaPredaja, AnketaPredaja.id == AnketaOdgovor.predaja_id)
            .where(AnketaPredaja.anketa_id == survey_id, AnketaOdgovor.broj.is_not(None))
            .group_by(AnketaOdgovor.pitanje_id, AnketaOdgovor.broj)
        )
        result: dict[int, dict[int, int]] = {}
        for pid, broj, cnt in self.db.execute(stmt).all():
            result.setdefault(int(pid), {})[int(broj)] = int(cnt)
        return result

    # ------------------------------------------------------- detaljni odgovori
    def list_final_submissions(
        self,
        survey_id: int,
        platni_broj: str | None,
        orgjed_sifra: str | None,
        radno_mesto_sifra: str | None,
        datum_od: datetime.datetime | None,
        datum_do: datetime.datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[AnketaPredaja, Korisnik]], int]:
        """Samo za NEANONIMNE ankete (poziva se tek posle provere anonimnosti u servisu).
        Filter po org. jedinici/radnom mestu ide preko EXISTS - jedna predaja se nikad
        ne duplira cak i kada korisnik ima vise aktivnih rasporeda koji odgovaraju filteru."""
        stmt = (
            select(AnketaPredaja, Korisnik)
            .join(Korisnik, Korisnik.id == AnketaPredaja.korisnik_id)
            .where(AnketaPredaja.anketa_id == survey_id)
        )
        if platni_broj is not None:
            stmt = stmt.where(Korisnik.platni_broj == platni_broj)
        if datum_od is not None:
            stmt = stmt.where(AnketaPredaja.datum_predaje >= datum_od)
        if datum_do is not None:
            stmt = stmt.where(AnketaPredaja.datum_predaje <= datum_do)
        if orgjed_sifra is not None or radno_mesto_sifra is not None:
            # Jedan korelisani EXISTS: ako su oba filtera prosledjena, ISTI red
            # rasporeda mora zadovoljiti oba (a ne dva nezavisna aktivna rasporeda).
            conditions = [
                KorisnikRaspored.korisnik_id == AnketaPredaja.korisnik_id,
                KorisnikRaspored.aktivan == "D",
            ]
            if orgjed_sifra is not None:
                conditions.append(KorisnikRaspored.orgjed_sifra == orgjed_sifra)
            if radno_mesto_sifra is not None:
                conditions.append(KorisnikRaspored.radno_mesto_sifra == radno_mesto_sifra)
            stmt = stmt.where(exists(select(1).where(and_(*conditions))))

        total = int(self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
        rows = self.db.execute(
            stmt.order_by(AnketaPredaja.datum_predaje.desc(), AnketaPredaja.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [(row[0], row[1]) for row in rows], total

    def get_final_answers_for_predaje(self, predaja_ids: list[int]) -> list[AnketaOdgovor]:
        if not predaja_ids:
            return []
        stmt = select(AnketaOdgovor).where(AnketaOdgovor.predaja_id.in_(predaja_ids))
        return list(self.db.execute(stmt).scalars().all())

    def get_final_answer_options_for_odgovori(self, odgovor_ids: list[int]) -> list[AnketaOdgovorOpcija]:
        if not odgovor_ids:
            return []
        stmt = select(AnketaOdgovorOpcija).where(AnketaOdgovorOpcija.odgovor_id.in_(odgovor_ids))
        return list(self.db.execute(stmt).scalars().all())

    def primary_active_rasporedi(self, korisnik_ids: list[int]) -> dict[int, KorisnikRaspored]:
        """Batch verzija KorisnikRepository.get_primary_active_raspored - jedan upit za
        celu stranicu (izbegava N+1). Bira primarni aktivni raspored po korisniku."""
        if not korisnik_ids:
            return {}
        primarni_prioritet = case((KorisnikRaspored.primarni == "D", 0), else_=1)
        stmt = (
            select(KorisnikRaspored)
            .where(KorisnikRaspored.korisnik_id.in_(korisnik_ids), KorisnikRaspored.aktivan == "D")
            .order_by(KorisnikRaspored.korisnik_id, primarni_prioritet, KorisnikRaspored.id)
        )
        result: dict[int, KorisnikRaspored] = {}
        for r in self.db.execute(stmt).scalars().all():
            if r.korisnik_id not in result:
                result[r.korisnik_id] = r
        return result

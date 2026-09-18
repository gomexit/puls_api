"""Admin SURVEY-RESULT (read-only): opsta statistika, statistika po pitanjima i
detaljni odgovori za neanonimne ankete. Bez commit-a, bez izmene baze, bez audit
zapisa (cisto citanje).

ANONIMNOST (najvaznije pravilo): statistika anonimne ankete se racuna iskljucivo
kroz SurveyResultsRepository agregatne upite koji NIKADA ne citaju
PULS_ANKETA_PREDAJE.KORISNIK_ID niti joinuju predaju na PULS_ANKETA_UCESCA/
PULS_KORISNICI. GET /responses je za anonimne ankete potpuno blokiran (409) pre
bilo kakvog citanja detaljnih podataka."""

import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AnonymousSurveyResponsesNotAvailableError,
    SurveyNotFoundError,
)
from app.models.anketa import (
    KOMP_BOOLEAN,
)
from app.repositories.survey_repository import SurveyRepository
from app.repositories.survey_results_repository import SurveyResultsRepository
from app.services.question_types import get_question_type


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _median_from_counts(value_counts: dict[int, int]) -> float | None:
    """Deterministicka medijana iz frekventne tabele {vrednost: broj}. Radi ispravno
    i za paran i za neparan ukupan broj odgovora, bez ucitavanja svakog reda pojedinacno."""
    items = sorted(value_counts.items())
    total = sum(c for _, c in items)
    if total == 0:
        return None
    mid_lo = (total + 1) // 2
    mid_hi = (total + 2) // 2  # jednako mid_lo kada je total neparan
    cum = 0
    lo_val = hi_val = None
    for value, count in items:
        cum += count
        if lo_val is None and cum >= mid_lo:
            lo_val = value
        if hi_val is None and cum >= mid_hi:
            hi_val = value
        if lo_val is not None and hi_val is not None:
            break
    return round((lo_val + hi_val) / 2, 2)


class SurveyResultsService:
    def __init__(
        self,
        db: Session,
        results_repository: SurveyResultsRepository | None = None,
        survey_repository: SurveyRepository | None = None,
    ):
        self.db = db
        self.results_repo = results_repository or SurveyResultsRepository(db)
        self.survey_repo = survey_repository or SurveyRepository(db)

    # ---------------------------------------------------------------- statistika
    def get_statistics(self, survey_id: int) -> dict:
        anketa = self.survey_repo.get_survey(survey_id)
        if anketa is None:
            raise SurveyNotFoundError()

        status_counts = self.results_repo.ucesce_status_counts(survey_id)
        # ukupno_ciljanih = broj materijalizovanih PULS_ANKETA_UCESCA redova (NE
        # ponovno izracunavanje ciljne grupe prema trenutnom stanju zaposlenih).
        ukupno = sum(status_counts.values())
        nije_zapocelo = status_counts.get("NOT_STARTED", 0)
        u_toku = status_counts.get("IN_PROGRESS", 0)
        predato = status_counts.get("SUBMITTED", 0)
        nije_predato = ukupno - predato

        odziv = {
            "ukupno_ciljanih": ukupno,
            "nije_zapocelo": nije_zapocelo,
            "u_toku": u_toku,
            "predato": predato,
            "nije_predato": nije_predato,
            "procenat_odziva": _pct(predato, ukupno),
        }

        pitanja_out = self._build_question_stats(survey_id)

        return {
            "survey_id": anketa.id,
            "naziv": anketa.naziv,
            "anonimna": anketa.is_anonimna,
            "status": anketa.status,
            "datum_pocetka": anketa.datum_pocetka,
            "datum_zavrsetka": anketa.datum_zavrsetka,
            "odziv": odziv,
            "pitanja": pitanja_out,
        }

    def _build_question_stats(self, survey_id: int) -> list[dict]:
        sections = self.survey_repo.get_sections(survey_id)
        questions = self.survey_repo.get_questions_for_survey(survey_id)
        options = self.survey_repo.get_options_for_survey(survey_id)

        sec_by_id = {s.id: s for s in sections}
        opts_by_q: dict[int, list] = {}
        for o in options:
            opts_by_q.setdefault(o.pitanje_id, []).append(o)

        answer_counts = self.results_repo.answer_counts_by_question(survey_id)
        option_counts = self.results_repo.option_choice_counts(survey_id)
        bool_counts = self.results_repo.boolean_counts(survey_id)
        rating_counts = self.results_repo.rating_value_counts(survey_id)

        pitanja_out = []
        for q in questions:
            sekcija = sec_by_id.get(q.sekcija_id)
            # Denominator za procente opcija je broj predaja koje IMAJU odgovor na OVO
            # pitanje (uslovna pitanja: manji imenilac ako ih je manje ljudi videlo).
            broj_odgovora = answer_counts.get(q.id, 0)
            item: dict = {
                "pitanje_id": q.id,
                "sekcija_id": q.sekcija_id,
                "sekcija_naziv": sekcija.naziv if sekcija else "",
                "tekst": q.tekst,
                "tip_pitanja": q.tip_pitanja,
                "sekcija_redosled": int(sekcija.redosled) if sekcija else 0,
                "pitanje_redosled": int(q.redosled),
                "broj_odgovora": broj_odgovora,
            }

            tip_def = get_question_type(q.tip_pitanja)
            item["komponenta"] = tip_def.komponenta if tip_def else None
            if tip_def is None:
                pass
            elif tip_def.ima_opcije:
                counts_for_q = option_counts.get(q.id, {})
                item["opcije"] = [
                    {
                        "opcija_id": o.id,
                        "tekst": o.tekst,
                        "broj_izbora": counts_for_q.get(o.id, 0),
                        "procenat": _pct(counts_for_q.get(o.id, 0), broj_odgovora),
                    }
                    for o in sorted(opts_by_q.get(q.id, []), key=lambda x: x.redosled)
                ]
            elif tip_def.komponenta == KOMP_BOOLEAN:
                bc = bool_counts.get(q.id, {})
                da = bc.get("D", 0)
                ne = bc.get("N", 0)
                total_bool = da + ne
                item["da"] = {"broj": da, "procenat": _pct(da, total_bool)}
                item["ne"] = {"broj": ne, "procenat": _pct(ne, total_bool)}
            elif tip_def.je_skala:
                vc = rating_counts.get(q.id, {})
                lo, hi = tip_def.raspon
                total_r = sum(vc.values())
                if total_r == 0:
                    item["prosek"] = None
                    item["medijana"] = None
                    item["minimum"] = None
                    item["maksimum"] = None
                else:
                    item["prosek"] = round(sum(v * c for v, c in vc.items()) / total_r, 2)
                    item["medijana"] = _median_from_counts(vc)
                    item["minimum"] = min(v for v, c in vc.items() if c > 0)
                    item["maksimum"] = max(v for v, c in vc.items() if c > 0)
                # Raspodela obuhvata CEO dozvoljeni raspon, uklj. vrednosti sa 0 (i kada
                # nema odgovora uopste).
                item["raspodela"] = [
                    {"vrednost": v, "broj": vc.get(v, 0), "procenat": _pct(vc.get(v, 0), total_r)}
                    for v in range(lo, hi + 1)
                ]
            # TEXT: samo zajednicka polja (broj_odgovora) - bez sirovog teksta.

            pitanja_out.append(item)
        return pitanja_out

    # ------------------------------------------------------- detaljni odgovori
    def get_responses(
        self,
        survey_id: int,
        page: int,
        page_size: int,
        platni_broj: str | None,
        orgjed_sifra: str | None,
        radno_mesto_sifra: str | None,
        datum_od: datetime.datetime | None,
        datum_do: datetime.datetime | None,
    ) -> dict:
        anketa = self.survey_repo.get_survey(survey_id)
        if anketa is None:
            raise SurveyNotFoundError()
        if anketa.is_anonimna:
            raise AnonymousSurveyResponsesNotAvailableError()

        rows, total = self.results_repo.list_final_submissions(
            survey_id, platni_broj, orgjed_sifra, radno_mesto_sifra, datum_od, datum_do, page, page_size
        )

        predaja_ids = [p.id for p, _ in rows]
        korisnik_ids = [k.id for _, k in rows]

        answers = self.results_repo.get_final_answers_for_predaje(predaja_ids)
        answers_by_predaja: dict[int, list] = {}
        for a in answers:
            answers_by_predaja.setdefault(a.predaja_id, []).append(a)

        odgovor_ids = [a.id for a in answers]
        answer_options = self.results_repo.get_final_answer_options_for_odgovori(odgovor_ids)
        opts_by_odgovor: dict[int, list[int]] = {}
        for ao in answer_options:
            opts_by_odgovor.setdefault(ao.odgovor_id, []).append(ao.opcija_id)

        questions = self.survey_repo.get_questions_for_survey(survey_id)
        q_order = {q.id: i for i, q in enumerate(questions)}
        q_type_by_id = {q.id: q.tip_pitanja for q in questions}
        options = self.survey_repo.get_options_for_survey(survey_id)
        opt_by_id = {o.id: o for o in options}
        opt_order = {o.id: o.redosled for o in options}

        rasporedi = self.results_repo.primary_active_rasporedi(korisnik_ids)

        items = []
        for predaja, korisnik in rows:
            raspored = rasporedi.get(korisnik.id)
            q_answers = sorted(
                answers_by_predaja.get(predaja.id, []),
                key=lambda a: q_order.get(a.pitanje_id, 0),
            )
            odgovori_out = []
            for a in q_answers:
                opcija_ids = sorted(
                    opts_by_odgovor.get(a.id, []),
                    key=lambda oid: opt_order.get(oid, 0),
                )
                odgovori_out.append(
                    {
                        "pitanje_id": a.pitanje_id,
                        "tip_pitanja": q_type_by_id.get(a.pitanje_id, ""),
                        "tekst": a.tekst,
                        "broj": int(a.broj) if a.broj is not None else None,
                        "logicka": (a.logicka == "D") if a.logicka is not None else None,
                        "opcije": [
                            {"opcija_id": oid, "tekst": opt_by_id[oid].tekst}
                            for oid in opcija_ids
                            if oid in opt_by_id
                        ],
                    }
                )
            items.append(
                {
                    "korisnik": {
                        "korisnik_id": korisnik.id,
                        "platni_broj": korisnik.platni_broj,
                        "ime": korisnik.ime,
                        "prezime": korisnik.prezime,
                        "orgjed_sifra": raspored.orgjed_sifra if raspored else None,
                        "radno_mesto_sifra": raspored.radno_mesto_sifra if raspored else None,
                    },
                    "datum_predaje": predaja.datum_predaje,
                    "odgovori": odgovori_out,
                }
            )

        return {
            "survey_id": survey_id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": page * page_size < total,
            "items": items,
        }

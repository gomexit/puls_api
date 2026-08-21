"""Fake SurveyResultsRepository koji racuna agregate nad FakeSurveyRepo podacima
(ista logika kao SQL upiti u SurveyResultsRepository, ali u Python-u) - koristi se
za servisne testove modula SURVEY-RESULT (bez prave Oracle baze)."""

import itertools

from app.models.anketa_predaja import AnketaOdgovor, AnketaOdgovorOpcija, AnketaPredaja
from app.models.korisnik_raspored import KorisnikRaspored
from tests.survey_fakes import FakeSurveyRepo

_ids = itertools.count(500000)


def _next_id() -> int:
    return next(_ids)


class FakeSurveyResultsRepo:
    def __init__(self, survey_repo: FakeSurveyRepo, korisnici=None, rasporedi=None):
        self.survey_repo = survey_repo
        self.korisnici = {k.id: k for k in (korisnici or [])}
        self.rasporedi: list[KorisnikRaspored] = list(rasporedi or [])

    # ---------------------------------------------------------------- odziv
    def ucesce_status_counts(self, survey_id):
        counts: dict[str, int] = {}
        for u in self.survey_repo.ucesca:
            if u.anketa_id == survey_id:
                counts[u.status] = counts.get(u.status, 0) + 1
        return counts

    def _final_answers_for_survey(self, survey_id):
        predaja_ids = {p.id for p in self.survey_repo.submissions if p.anketa_id == survey_id}
        return [a for a in self.survey_repo.answers if a.predaja_id in predaja_ids]

    # ------------------------------------------------------- statistika pitanja
    def answer_counts_by_question(self, survey_id):
        counts: dict[int, int] = {}
        for a in self._final_answers_for_survey(survey_id):
            counts[a.pitanje_id] = counts.get(a.pitanje_id, 0) + 1
        return counts

    def option_choice_counts(self, survey_id):
        answers = self._final_answers_for_survey(survey_id)
        answer_by_id = {a.id: a for a in answers}
        result: dict[int, dict[int, int]] = {}
        for ao in self.survey_repo.answer_options:
            a = answer_by_id.get(ao.odgovor_id)
            if a is None:
                continue
            per_q = result.setdefault(a.pitanje_id, {})
            per_q[ao.opcija_id] = per_q.get(ao.opcija_id, 0) + 1
        return result

    def boolean_counts(self, survey_id):
        result: dict[int, dict[str, int]] = {}
        for a in self._final_answers_for_survey(survey_id):
            if a.logicka is None:
                continue
            per_q = result.setdefault(a.pitanje_id, {})
            per_q[a.logicka] = per_q.get(a.logicka, 0) + 1
        return result

    def rating_value_counts(self, survey_id):
        result: dict[int, dict[int, int]] = {}
        for a in self._final_answers_for_survey(survey_id):
            if a.broj is None:
                continue
            per_q = result.setdefault(a.pitanje_id, {})
            v = int(a.broj)
            per_q[v] = per_q.get(v, 0) + 1
        return result

    # ------------------------------------------------------- detaljni odgovori
    def list_final_submissions(
        self, survey_id, platni_broj, orgjed_sifra, radno_mesto_sifra, datum_od, datum_do, page, page_size
    ):
        items = []
        for p in self.survey_repo.submissions:
            if p.anketa_id != survey_id or p.korisnik_id is None:
                continue
            k = self.korisnici.get(p.korisnik_id)
            if k is None:
                continue
            if platni_broj is not None and k.platni_broj != platni_broj:
                continue
            if datum_od is not None and (p.datum_predaje is None or p.datum_predaje < datum_od):
                continue
            if datum_do is not None and (p.datum_predaje is None or p.datum_predaje > datum_do):
                continue
            if orgjed_sifra is not None or radno_mesto_sifra is not None:
                # Isti red rasporeda mora zadovoljiti OBA prosledjena filtera.
                if not any(
                    r.korisnik_id == p.korisnik_id
                    and r.aktivan == "D"
                    and (orgjed_sifra is None or r.orgjed_sifra == orgjed_sifra)
                    and (radno_mesto_sifra is None or r.radno_mesto_sifra == radno_mesto_sifra)
                    for r in self.rasporedi
                ):
                    continue
            items.append((p, k))
        items.sort(key=lambda pk: (pk[0].datum_predaje, pk[0].id), reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

    def get_final_answers_for_predaje(self, predaja_ids):
        ids = set(predaja_ids)
        return [a for a in self.survey_repo.answers if a.predaja_id in ids]

    def get_final_answer_options_for_odgovori(self, odgovor_ids):
        ids = set(odgovor_ids)
        return [o for o in self.survey_repo.answer_options if o.odgovor_id in ids]

    def primary_active_rasporedi(self, korisnik_ids):
        ids = set(korisnik_ids)
        candidates = [r for r in self.rasporedi if r.korisnik_id in ids and r.aktivan == "D"]
        candidates.sort(key=lambda r: (r.korisnik_id, r.primarni != "D"))
        result: dict[int, KorisnikRaspored] = {}
        for r in candidates:
            result.setdefault(r.korisnik_id, r)
        return result


# --------------------------------------------------------------------- fabrike
def make_predaja(repo: FakeSurveyRepo, anketa_id, korisnik_id=None, anonimna="N", datum_predaje=None):
    predaja = AnketaPredaja(
        anketa_id=anketa_id, anonimna=anonimna, korisnik_id=korisnik_id, datum_predaje=datum_predaje
    )
    return repo.add_submission(predaja)


def make_odgovor(repo: FakeSurveyRepo, predaja_id, pitanje_id, tekst=None, broj=None, logicka=None):
    odgovor = AnketaOdgovor(predaja_id=predaja_id, pitanje_id=pitanje_id, tekst=tekst, broj=broj, logicka=logicka)
    return repo.add_answer(odgovor)


def make_odgovor_opcija(repo: FakeSurveyRepo, odgovor_id, opcija_id):
    return repo.add_answer_option(AnketaOdgovorOpcija(odgovor_id=odgovor_id, opcija_id=opcija_id))


def make_raspored(korisnik_id, orgjed_sifra=None, radno_mesto_sifra=None, primarni="N", aktivan="D"):
    return KorisnikRaspored(
        id=_next_id(),
        korisnik_id=korisnik_id,
        orgjed_sifra=orgjed_sifra,
        radno_mesto_sifra=radno_mesto_sifra,
        primarni=primarni,
        aktivan=aktivan,
    )

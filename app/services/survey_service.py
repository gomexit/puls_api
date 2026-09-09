import datetime
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    SurveyAlreadySubmittedError,
    SurveyNotActiveError,
    SurveyNotFoundError,
    SurveyNotTargetedError,
    ValidationBusinessError,
)
from app.models.anketa import (
    ANKETA_STATUS_ACTIVE,
    ANKETA_STATUS_ARCHIVED,
    RATING_RASPON,
    TIPOVI_JEDNA_OPCIJA,
    TIPOVI_SA_OPCIJAMA,
    TIP_BOOLEAN,
    TIP_MULTI_CHOICE,
    TIP_TEXT,
    UCESCE_IN_PROGRESS,
    UCESCE_NOT_STARTED,
    UCESCE_SUBMITTED,
    Anketa,
)
from app.models.anketa_predaja import AnketaOdgovor, AnketaOdgovorOpcija, AnketaPredaja
from app.models.anketa_ucesce import AnketaNacrtOdgovor, AnketaNacrtOpcija, AnketaUcesce
from app.models.korisnik import Korisnik
from app.repositories.audit_repository import AuditRepository
from app.repositories.survey_repository import SurveyRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.survey_visibility import AnswerValue, QuestionSpec, compute_visibility


@dataclass
class NormalizedAnswer:
    pitanje_id: int
    tekst: str | None = None
    broj: int | None = None
    logicka: bool | None = None
    opcija_ids: list[int] = field(default_factory=list)


class SurveyService:
    """Employee modul ANKETE. Owns the transaction boundary."""

    def __init__(
        self,
        db: Session,
        repository: SurveyRepository | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.repo = repository or SurveyRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )

    # --------------------------------------------------- dostupnost (obicno/automatsko)
    @staticmethod
    def _is_available(anketa: Anketa, ucesce: AnketaUcesce, now: datetime.datetime) -> bool:
        """Za automatsko ucesce (AUTOMATIKA_ID IS NOT NULL): dostupnost = per-user
        prozor [ucesce.datum_dostupnosti, ucesce.datum_isteka) I anketa mora biti
        ACTIVE (globalni period same ankete se NE proverava). Za obicno ucesce:
        identicna logika kao ranije (anketa.is_available_to_employees)."""
        if ucesce.is_automatsko:
            return anketa.status == ANKETA_STATUS_ACTIVE and ucesce.is_dostupno_sada(now)
        return anketa.is_available_to_employees(now)

    @staticmethod
    def _effective_period(anketa: Anketa, ucesce: AnketaUcesce) -> tuple[datetime.datetime, datetime.datetime]:
        """Datumi koje Android vidi kao datum_pocetka/datum_zavrsetka. Kod automatskog
        ucesca to su ucesce.datum_dostupnosti/datum_isteka (per-user prozor), inace
        anketa.datum_pocetka/datum_zavrsetka (globalni period) - ugovor prema Androidu
        se ne menja, samo izvor vrednosti."""
        if ucesce.is_automatsko:
            return ucesce.datum_dostupnosti, ucesce.datum_isteka
        return anketa.datum_pocetka, anketa.datum_zavrsetka

    # ------------------------------------------------------------------- lista
    def list_surveys(self, korisnik: Korisnik) -> tuple[list[dict], int]:
        now = datetime.datetime.now()
        pairs = self.repo.list_user_surveys(korisnik.id)
        items = []
        za_popunjavanje = 0
        for anketa, ucesce in pairs:
            available = self._is_available(anketa, ucesce, now)
            submitted = ucesce.status == UCESCE_SUBMITTED
            # Prikazi samo trenutno dostupne ili vec predate (istorija).
            # Buduce SCHEDULED (pre pocetka), istekle/CLOSED nepredate se izostavljaju;
            # DRAFT/ARCHIVED ionako ne ulaze (repo filtrira ARCHIVED, DRAFT nema ucesce).
            if not available and not submitted:
                continue
            if available and not submitted:
                za_popunjavanje += 1
            tip = self.repo.get_type(anketa.tip_sifra)
            datum_pocetka, datum_zavrsetka = self._effective_period(anketa, ucesce)
            items.append(
                {
                    "anketa": anketa,
                    "tip_naziv": tip.naziv if tip else anketa.tip_sifra,
                    "broj_pitanja": self.repo.count_questions(anketa.id),
                    "moj_status": ucesce.status,
                    "datum_pocetka": datum_pocetka,
                    "datum_zavrsetka": datum_zavrsetka,
                }
            )
        return items, za_popunjavanje

    # ---------------------------------------------------------------- detalji
    def _require_access(self, survey_id: int, korisnik: Korisnik) -> tuple[Anketa, AnketaUcesce]:
        anketa = self.repo.get_survey(survey_id)
        if anketa is None or anketa.status == ANKETA_STATUS_ARCHIVED:
            raise SurveyNotFoundError()
        ucesce = self.repo.get_ucesce(anketa.id, korisnik.id)
        if ucesce is None:
            raise SurveyNotTargetedError()
        return anketa, ucesce

    def get_detail(self, korisnik: Korisnik, survey_id: int) -> dict:
        now = datetime.datetime.now()
        anketa, ucesce = self._require_access(survey_id, korisnik)
        available = self._is_available(anketa, ucesce, now)
        if ucesce.status != UCESCE_SUBMITTED and not available:
            raise SurveyNotActiveError()

        tip = self.repo.get_type(anketa.tip_sifra)
        sections = self.repo.get_sections(anketa.id)
        questions = self.repo.get_questions_for_survey(anketa.id)
        options = self.repo.get_options_for_survey(anketa.id)
        uslov_values = self.repo.get_uslov_values_for_survey(anketa.id)

        opts_by_q: dict[int, list] = {}
        for o in options:
            opts_by_q.setdefault(o.pitanje_id, []).append(o)
        uslov_by_q: dict[int, list[str]] = {}
        for uv in uslov_values:
            uslov_by_q.setdefault(uv.pitanje_id, []).append(uv.vrednost)

        anonimna = anketa.is_anonimna
        odgovori_dostupni = not (ucesce.status == UCESCE_SUBMITTED and anonimna)
        moji_odgovori = self._build_my_answers(anketa, ucesce, korisnik, anonimna)
        datum_pocetka, datum_zavrsetka = self._effective_period(anketa, ucesce)

        return {
            "anketa": anketa,
            "tip_naziv": tip.naziv if tip else anketa.tip_sifra,
            "moj_status": ucesce.status,
            "datum_pocetka": datum_pocetka,
            "datum_zavrsetka": datum_zavrsetka,
            "datum_predaje": ucesce.datum_predaje,
            "odgovori_dostupni": odgovori_dostupni,
            "sections": sections,
            "questions": questions,
            "opts_by_q": opts_by_q,
            "uslov_by_q": uslov_by_q,
            "moji_odgovori": moji_odgovori,
        }

    def _build_my_answers(self, anketa, ucesce, korisnik, anonimna) -> list[NormalizedAnswer]:
        if ucesce.status == UCESCE_NOT_STARTED:
            return []
        if ucesce.status == UCESCE_IN_PROGRESS:
            drafts = self.repo.get_draft_answers(anketa.id, korisnik.id)
            opts = self.repo.get_draft_options([d.id for d in drafts])
            opts_by_answer: dict[int, list[int]] = {}
            for o in opts:
                opts_by_answer.setdefault(o.nacrt_odgovor_id, []).append(o.opcija_id)
            return [
                NormalizedAnswer(
                    pitanje_id=d.pitanje_id,
                    tekst=d.tekst,
                    broj=int(d.broj) if d.broj is not None else None,
                    logicka=(d.logicka == "D") if d.logicka is not None else None,
                    opcija_ids=opts_by_answer.get(d.id, []),
                )
                for d in drafts
            ]
        # SUBMITTED
        if anonimna:
            return []
        predaja = self.repo.get_user_submission(anketa.id, korisnik.id)
        if predaja is None:
            return []
        answers = self.repo.get_final_answers(predaja.id)
        opts = self.repo.get_final_answer_options([a.id for a in answers])
        opts_by_answer = {}
        for o in opts:
            opts_by_answer.setdefault(o.odgovor_id, []).append(o.opcija_id)
        return [
            NormalizedAnswer(
                pitanje_id=a.pitanje_id,
                tekst=a.tekst,
                broj=int(a.broj) if a.broj is not None else None,
                logicka=(a.logicka == "D") if a.logicka is not None else None,
                opcija_ids=opts_by_answer.get(a.id, []),
            )
            for a in answers
        ]

    # ------------------------------------------------------------------ draft
    def save_draft(self, korisnik: Korisnik, survey_id: int, odgovori) -> str:
        try:
            now = datetime.datetime.now()
            anketa, ucesce = self._require_access(survey_id, korisnik)
            if ucesce.status == UCESCE_SUBMITTED:
                raise SurveyAlreadySubmittedError()
            if not self._is_available(anketa, ucesce, now):
                raise SurveyNotActiveError()

            questions = self.repo.get_questions_for_survey(anketa.id)
            options = self.repo.get_options_for_survey(anketa.id)
            uslov_values = self.repo.get_uslov_values_for_survey(anketa.id)
            answers = self._validate_answers(questions, options, odgovori)
            visible = self._visibility(questions, uslov_values, answers)

            self.repo.delete_draft(anketa.id, korisnik.id)
            self.db.flush()
            self._store_answers_as_draft(anketa.id, korisnik.id, questions, answers, visible, now)

            if ucesce.status == UCESCE_NOT_STARTED:
                ucesce.status = UCESCE_IN_PROGRESS
                ucesce.datum_pocetka = ucesce.datum_pocetka or now
                ucesce.datum_izmene = now
            self.db.commit()
            return ucesce.status
        except Exception:
            self.db.rollback()
            raise

    def _store_answers_as_draft(self, anketa_id, korisnik_id, questions, answers, visible, now):
        q_by_id = {q.id: q for q in questions}
        for qid, av in answers.items():
            if not visible.get(qid, False):
                continue  # odgovore na skrivena pitanja ne cuvamo
            q = q_by_id[qid]
            if not _is_answered_value(q.tip_pitanja, av):
                continue
            nacrt = self.repo.add_draft_answer(
                AnketaNacrtOdgovor(
                    anketa_id=anketa_id,
                    korisnik_id=korisnik_id,
                    pitanje_id=qid,
                    tekst=av.tekst,
                    broj=av.broj,
                    logicka=_bool_to_char(av.logicka),
                    datum_kreiranja=now,
                )
            )
            for oid in av.opcija_ids:
                self.repo.add_draft_option(
                    AnketaNacrtOpcija(nacrt_odgovor_id=nacrt.id, opcija_id=oid)
                )

    # ----------------------------------------------------------------- submit
    def submit(self, korisnik: Korisnik, survey_id: int, odgovori) -> AnketaUcesce:
        try:
            now = datetime.datetime.now()
            anketa = self.repo.get_survey(survey_id)
            if anketa is None or anketa.status == ANKETA_STATUS_ARCHIVED:
                raise SurveyNotFoundError()
            # Zakljucaj red ucesca (SELECT ... FOR UPDATE) da dva paralelna submita ne prodju.
            ucesce = self.repo.get_ucesce_for_update(anketa.id, korisnik.id)
            if ucesce is None:
                raise SurveyNotTargetedError()
            if ucesce.status == UCESCE_SUBMITTED:
                raise SurveyAlreadySubmittedError()
            if not self._is_available(anketa, ucesce, now):
                raise SurveyNotActiveError()

            questions = self.repo.get_questions_for_survey(anketa.id)
            options = self.repo.get_options_for_survey(anketa.id)
            uslov_values = self.repo.get_uslov_values_for_survey(anketa.id)
            answers = self._validate_answers(questions, options, odgovori)
            visible = self._visibility(questions, uslov_values, answers)

            # Svako vidljivo obavezno pitanje mora imati odgovor.
            for q in questions:
                if q.obavezno_bool and visible.get(q.id, False):
                    av = answers.get(q.id)
                    if av is None or not _is_answered_value(q.tip_pitanja, av):
                        raise ValidationBusinessError("Niste odgovorili na sva obavezna pitanja.")

            anonimna = anketa.is_anonimna
            predaja = self.repo.add_submission(
                AnketaPredaja(
                    anketa_id=anketa.id,
                    anonimna="D" if anonimna else "N",
                    korisnik_id=None if anonimna else korisnik.id,
                    # Kod anonimne predaje DATUM_PREDAJE je NULL da se ne bi mogla
                    # povezati sa korisnikom preko preciznog timestamp-a. Ucesce i dalje
                    # cuva stvarno vreme (evidencija ucesca).
                    datum_predaje=None if anonimna else now,
                )
            )
            q_by_id = {q.id: q for q in questions}
            for qid, av in answers.items():
                if not visible.get(qid, False):
                    continue  # skriveni odgovori se ne cuvaju
                q = q_by_id[qid]
                if not _is_answered_value(q.tip_pitanja, av):
                    continue
                odg = self.repo.add_answer(
                    AnketaOdgovor(
                        predaja_id=predaja.id,
                        pitanje_id=qid,
                        tekst=av.tekst,
                        broj=av.broj,
                        logicka=_bool_to_char(av.logicka),
                    )
                )
                for oid in av.opcija_ids:
                    self.repo.add_answer_option(
                        AnketaOdgovorOpcija(odgovor_id=odg.id, opcija_id=oid)
                    )

            # Fizicki obrisi sve nacrte korisnika za ovu anketu (u istoj transakciji).
            self.repo.delete_draft(anketa.id, korisnik.id)
            ucesce.status = UCESCE_SUBMITTED
            ucesce.datum_predaje = now
            ucesce.datum_izmene = now

            # Audit: samo anketa_id i cinjenica predaje (bez predaja_id/sadrzaja/opcija).
            # Kod anonimne ankete audit NE sme sadrzati korisnik_id ni platni_broj.
            self.audit_service.log(
                AuditAction.SURVEY_SUBMITTED,
                korisnik_id=None if anonimna else korisnik.id,
                platni_broj=None if anonimna else korisnik.platni_broj,
                tip_entiteta="ANKETA",
                entitet_id=str(anketa.id),
            )
            self.db.commit()
            return ucesce
        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------- helpers (validacija)
    def _validate_answers(self, questions, options, odgovori) -> dict[int, AnswerValue]:
        q_by_id = {q.id: q for q in questions}
        opts_by_q: dict[int, set[int]] = {}
        for o in options:
            opts_by_q.setdefault(o.pitanje_id, set()).add(o.id)

        seen: set[int] = set()
        result: dict[int, AnswerValue] = {}
        for od in odgovori:
            if od.pitanje_id in seen:
                raise ValidationBusinessError("Duplirano pitanje u odgovorima.")
            seen.add(od.pitanje_id)
            q = q_by_id.get(od.pitanje_id)
            if q is None:
                raise ValidationBusinessError("Odgovor referencira pitanje van ankete.")
            av = self._validate_one(q, od, opts_by_q.get(q.id, set()))
            result[q.id] = av
        return result

    def _validate_one(self, q, od, valid_option_ids: set[int]) -> AnswerValue:
        tip = q.tip_pitanja
        opcija_ids = list(dict.fromkeys(od.opcija_ids or []))

        if tip in TIPOVI_SA_OPCIJAMA:
            if any(o not in valid_option_ids for o in opcija_ids):
                raise ValidationBusinessError("Izabrana opcija ne pripada pitanju.")
            if od.tekst or od.broj is not None or od.logicka is not None:
                raise ValidationBusinessError("Polja koja ne pripadaju tipu pitanja moraju biti prazna.")
            if opcija_ids:
                if tip in TIPOVI_JEDNA_OPCIJA and len(opcija_ids) != 1:
                    raise ValidationBusinessError("Ovo pitanje dozvoljava tačno jednu opciju.")
                if tip == TIP_MULTI_CHOICE and len(opcija_ids) < 1:
                    raise ValidationBusinessError("Izaberite najmanje jednu opciju.")
            return AnswerValue(opcija_ids=opcija_ids)

        if tip == TIP_TEXT:
            if od.broj is not None or od.logicka is not None or opcija_ids:
                raise ValidationBusinessError("TEXT pitanje koristi samo tekst.")
            tekst = od.tekst.strip() if od.tekst else None
            return AnswerValue(tekst=tekst or None)

        if tip == TIP_BOOLEAN:
            if od.tekst or od.broj is not None or opcija_ids:
                raise ValidationBusinessError("BOOLEAN pitanje koristi samo logičku vrednost.")
            return AnswerValue(logicka=od.logicka)

        if tip in RATING_RASPON:
            if od.tekst or od.logicka is not None or opcija_ids:
                raise ValidationBusinessError("RATING pitanje koristi samo broj.")
            if od.broj is not None:
                lo, hi = RATING_RASPON[tip]
                if not (lo <= od.broj <= hi):
                    raise ValidationBusinessError(f"Ocena mora biti u opsegu {lo}-{hi}.")
            return AnswerValue(broj=od.broj)

        raise ValidationBusinessError("Nepoznat tip pitanja.")

    def _visibility(self, questions, uslov_values, answers) -> dict[int, bool]:
        uslov_by_q: dict[int, list[str]] = {}
        for uv in uslov_values:
            uslov_by_q.setdefault(uv.pitanje_id, []).append(uv.vrednost)
        specs = [
            QuestionSpec(
                id=q.id,
                tip_pitanja=q.tip_pitanja,
                uslov_pitanje_id=q.uslov_pitanje_id,
                uslov_operator=q.uslov_operator,
                uslov_vrednosti=uslov_by_q.get(q.id, []),
            )
            for q in questions
        ]
        return compute_visibility(specs, answers)


def _is_answered_value(tip: str, av: AnswerValue) -> bool:
    from app.services.survey_visibility import is_answered

    return is_answered(tip, av)


def _bool_to_char(value: bool | None) -> str | None:
    if value is None:
        return None
    return "D" if value else "N"
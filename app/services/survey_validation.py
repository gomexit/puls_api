"""Strukturna validacija ankete pre izlaska iz DRAFT (obavezan checkpoint).

Radi nad vec upisanom strukturom (ucitanom iz baze). Podize ValidationBusinessError
sa jasnom porukom na srpskom na prvu gresku.
"""

from app.core.exceptions import ValidationBusinessError
from app.models.anketa import (
    CILJEVI_NEPODRZANI,
    CILJ_ORGJED,
    CILJ_PLATNI_BROJ,
    OPERATOR_IN,
    RATING_RASPON,
    TIPOVI_BEZ_OPCIJA,
    TIPOVI_SA_OPCIJAMA,
    TIP_BOOLEAN,
    TIP_TEXT,
    Anketa,
)


def _err(msg: str) -> ValidationBusinessError:
    return ValidationBusinessError(msg)


def validate_structure(repo, targeting_repo, anketa: Anketa, require_targets: bool = True) -> None:
    tip = repo.get_type(anketa.tip_sifra)
    if tip is None or tip.aktivan != "D":
        raise _err("Anketa mora imati aktivan tip.")

    if anketa.datum_zavrsetka <= anketa.datum_pocetka:
        raise _err("Datum završetka mora biti posle datuma početka.")

    sections = repo.get_sections(anketa.id)
    if not sections:
        raise _err("Anketa mora imati najmanje jednu sekciju.")

    questions = repo.get_questions_for_survey(anketa.id)  # global redosled
    if not questions:
        raise _err("Anketa mora imati najmanje jedno pitanje.")

    options = repo.get_options_for_survey(anketa.id)
    uslov_values = repo.get_uslov_values_for_survey(anketa.id)

    options_by_q: dict[int, list] = {}
    for o in options:
        options_by_q.setdefault(o.pitanje_id, []).append(o)
    uslov_by_q: dict[int, list[str]] = {}
    for uv in uslov_values:
        uslov_by_q.setdefault(uv.pitanje_id, []).append(uv.vrednost)

    q_by_id = {q.id: q for q in questions}
    order_index = {q.id: i for i, q in enumerate(questions)}

    for q in questions:
        opts = options_by_q.get(q.id, [])
        if q.tip_pitanja in TIPOVI_SA_OPCIJAMA and not opts:
            raise _err("Pitanje sa izborom mora imati ponuđene opcije.")
        if q.tip_pitanja in TIPOVI_BEZ_OPCIJA and opts:
            raise _err("Pitanje ovog tipa ne sme imati ponuđene opcije.")

        if q.uslov_pitanje_id is not None:
            control = q_by_id.get(q.uslov_pitanje_id)
            if control is None:
                raise _err("Uslov referencira nepostojeće pitanje.")
            if control.id == q.id:
                raise _err("Pitanje ne može zavisiti od samog sebe.")
            if order_index[control.id] >= order_index[q.id]:
                raise _err("Uslovno pitanje mora biti posle kontrolnog pitanja.")
            if control.tip_pitanja == TIP_TEXT:
                raise _err("Kontrolno pitanje ne sme biti tipa TEXT.")

            vrednosti = uslov_by_q.get(q.id, [])
            if q.uslov_operator == OPERATOR_IN:
                if len(vrednosti) < 1:
                    raise _err("IN uslov mora imati najmanje jednu vrednost.")
            else:  # EQUALS / NOT_EQUALS
                if len(vrednosti) != 1:
                    raise _err("EQUALS/NOT_EQUALS uslov mora imati tačno jednu vrednost.")

            _validate_condition_values(control, vrednosti, options_by_q.get(control.id, []))

    # Ciljne grupe - automatska (onboarding) anketa se dodeljuje iskljucivo kroz
    # OnboardingSurveyAssignmentService i ne mora imati ciljnu grupu (require_targets=False).
    targets = repo.get_targets(anketa.id)
    if not targets:
        if require_targets:
            raise _err("Anketa mora imati najmanje jednu ciljnu grupu.")
        return
    for t in targets:
        if t.tip_cilja in CILJEVI_NEPODRZANI:
            raise _err(
                "Ciljanje CENTRALA/MALOPRODAJA trenutno nije podržano jer ne postoji "
                "pouzdan HR podatak za razlikovanje."
            )
        if t.tip_cilja == CILJ_ORGJED and not targeting_repo.user_ids_by_orgjed(t.vrednost):
            raise _err("Ciljana organizaciona jedinica ne postoji ili nema aktivnih korisnika.")
        if t.tip_cilja == CILJ_PLATNI_BROJ and targeting_repo.user_id_by_platni_broj(t.vrednost) is None:
            raise _err("Ciljani platni broj ne postoji među aktivnim korisnicima.")


def _validate_condition_values(control, vrednosti: list[str], control_options: list) -> None:
    tip = control.tip_pitanja
    if tip in TIPOVI_SA_OPCIJAMA:
        valid_ids = {str(o.id) for o in control_options}
        for v in vrednosti:
            if v not in valid_ids:
                raise _err("Vrednost uslova ne pripada opcijama kontrolnog pitanja.")
    elif tip == TIP_BOOLEAN:
        for v in vrednosti:
            if v not in ("true", "false"):
                raise _err("Vrednost uslova za BOOLEAN mora biti 'true' ili 'false'.")
    elif tip in RATING_RASPON:
        lo, hi = RATING_RASPON[tip]
        for v in vrednosti:
            if not v.isdigit() or not (lo <= int(v) <= hi):
                raise _err(f"Vrednost uslova za ocenu mora biti broj {lo}-{hi}.")
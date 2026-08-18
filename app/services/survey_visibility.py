"""Cista logika izracunavanja vidljivosti uslovnih pitanja.

Backend uvek sam racuna vidljivost - nikada ne veruje klijentu. Odgovor
kontrolnog pitanja se normalizuje u skup string tokena, pa se primenjuje
operator uslova. Ako kontrolno pitanje nije vidljivo ili nema odgovor,
zavisno pitanje NIJE vidljivo.
"""

from dataclasses import dataclass, field

from app.models.anketa import (
    OPERATOR_EQUALS,
    OPERATOR_IN,
    OPERATOR_NOT_EQUALS,
    TIP_BOOLEAN,
    TIP_MULTI_CHOICE,
    TIP_RATING_1_5,
    TIP_RATING_1_10,
    TIP_SINGLE_CHOICE,
    TIP_DROPDOWN,
)


@dataclass
class AnswerValue:
    tekst: str | None = None
    broj: int | None = None
    logicka: bool | None = None
    opcija_ids: list[int] = field(default_factory=list)


@dataclass
class QuestionSpec:
    id: int
    tip_pitanja: str
    uslov_pitanje_id: int | None = None
    uslov_operator: str | None = None
    uslov_vrednosti: list[str] = field(default_factory=list)


def answer_tokens(tip: str, value: AnswerValue | None) -> set[str]:
    """Normalizuje odgovor u skup string tokena za poredjenje sa uslovom."""
    if value is None:
        return set()
    if tip in (TIP_SINGLE_CHOICE, TIP_DROPDOWN, TIP_MULTI_CHOICE):
        return {str(oid) for oid in value.opcija_ids}
    if tip == TIP_BOOLEAN:
        if value.logicka is None:
            return set()
        return {"true" if value.logicka else "false"}
    if tip in (TIP_RATING_1_5, TIP_RATING_1_10):
        return set() if value.broj is None else {str(value.broj)}
    # TEXT ne moze biti kontrolno pitanje.
    return set()


def is_answered(tip: str, value: AnswerValue | None) -> bool:
    if value is None:
        return False
    if tip in (TIP_SINGLE_CHOICE, TIP_DROPDOWN, TIP_MULTI_CHOICE):
        return bool(value.opcija_ids)
    if tip == TIP_BOOLEAN:
        return value.logicka is not None
    if tip in (TIP_RATING_1_5, TIP_RATING_1_10):
        return value.broj is not None
    return value.tekst is not None and value.tekst.strip() != ""


def _condition_met(operator: str, control_tokens: set[str], uslov_vrednosti: list[str]) -> bool:
    vals = set(uslov_vrednosti)
    if operator == OPERATOR_EQUALS:
        # EQUALS ima tacno jednu vrednost.
        return next(iter(vals), None) in control_tokens if vals else False
    if operator == OPERATOR_NOT_EQUALS:
        return next(iter(vals), None) not in control_tokens if vals else False
    if operator == OPERATOR_IN:
        return bool(control_tokens & vals)
    return False


def compute_visibility(
    questions: list[QuestionSpec], answers: dict[int, AnswerValue]
) -> dict[int, bool]:
    """Vraca mapu pitanje_id -> vidljivo. Rekurzivno, sa zastitom od ciklusa."""
    by_id = {q.id: q for q in questions}
    memo: dict[int, bool] = {}

    def visible(qid: int, stack: frozenset[int]) -> bool:
        if qid in memo:
            return memo[qid]
        if qid in stack:  # zastita od ciklusa (struktura ionako brani cikluse)
            return False
        q = by_id.get(qid)
        if q is None:
            return False
        if q.uslov_pitanje_id is None:
            memo[qid] = True
            return True
        control = by_id.get(q.uslov_pitanje_id)
        if control is None or not visible(control.id, stack | {qid}):
            memo[qid] = False
            return False
        control_val = answers.get(control.id)
        if not is_answered(control.tip_pitanja, control_val):
            memo[qid] = False
            return False
        tokens = answer_tokens(control.tip_pitanja, control_val)
        result = _condition_met(q.uslov_operator or "", tokens, q.uslov_vrednosti)
        memo[qid] = result
        return result

    for q in questions:
        visible(q.id, frozenset())
    return memo
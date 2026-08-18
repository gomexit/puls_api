"""Validacija admin payload-a ankete PRE upisa u bazu.

Ocekivani problemi vracaju standardni VALIDATION_ERROR (preko ValidationBusinessError),
a ne Oracle IntegrityError / HTTP 500. DRAFT sme ostati nepotpun (sekcije/pitanja/
ciljevi nisu obavezni pri kreiranju) - puna strukturna validacija je pri izlasku iz DRAFT.
"""

from app.core.exceptions import ValidationBusinessError
from app.models.anketa import (
    CILJEVI_BEZ_VREDNOSTI,
    CILJEVI_SA_VREDNOSCU,
    OPERATOR_IN,
    OPERATORI,
    TIPOVI_CILJA,
    TIPOVI_PITANJA,
    TIPOVI_SA_OPCIJAMA,
)


def _err(msg: str) -> ValidationBusinessError:
    return ValidationBusinessError(msg)


def validate_admin_survey_payload(payload) -> None:
    if payload.datum_zavrsetka <= payload.datum_pocetka:
        raise _err("Datum završetka mora biti posle datuma početka.")

    # Jedinstven redosled sekcija.
    if len({s.redosled for s in payload.sekcije}) != len(payload.sekcije):
        raise _err("Redosled sekcija mora biti jedinstven.")

    question_keys: dict[str, object] = {}
    option_keys_global: set[str] = set()
    option_keys_by_qkey: dict[str, set[str]] = {}

    for s in payload.sekcije:
        # Jedinstven redosled pitanja u sekciji.
        if len({q.redosled for q in s.pitanja}) != len(s.pitanja):
            raise _err("Redosled pitanja u sekciji mora biti jedinstven.")
        for q in s.pitanja:
            if q.tip not in TIPOVI_PITANJA:
                raise _err("Nepoznat tip pitanja.")
            if q.kljuc is not None:
                if q.kljuc in question_keys:
                    raise _err("Ključ pitanja mora biti jedinstven u zahtevu.")
                question_keys[q.kljuc] = q
                option_keys_by_qkey[q.kljuc] = set()
            # Jedinstven redosled opcija u pitanju.
            if len({o.redosled for o in q.opcije}) != len(q.opcije):
                raise _err("Redosled opcija u pitanju mora biti jedinstven.")
            for o in q.opcije:
                if o.kljuc is not None:
                    if o.kljuc in option_keys_global:
                        raise _err("Ključ opcije mora biti jedinstven u zahtevu.")
                    option_keys_global.add(o.kljuc)
                    if q.kljuc is not None:
                        option_keys_by_qkey[q.kljuc].add(o.kljuc)

    # Uslovi.
    for s in payload.sekcije:
        for q in s.pitanja:
            if q.uslov is None:
                continue
            u = q.uslov
            if u.operator not in OPERATORI:
                raise _err("Nepoznat operator uslova.")
            if u.pitanje_kljuc not in question_keys:
                raise _err("Uslov referencira nepoznato kontrolno pitanje.")
            if len(u.vrednosti) != len(set(u.vrednosti)):
                raise _err("Duple vrednosti uslova nisu dozvoljene.")
            if u.operator == OPERATOR_IN:
                if len(u.vrednosti) < 1:
                    raise _err("IN uslov mora imati najmanje jednu vrednost.")
            elif len(u.vrednosti) != 1:
                raise _err("EQUALS/NOT_EQUALS uslov mora imati tačno jednu vrednost.")

            control = question_keys[u.pitanje_kljuc]
            if control.tip in TIPOVI_SA_OPCIJAMA:
                valid_opt_keys = option_keys_by_qkey.get(u.pitanje_kljuc, set())
                for v in u.vrednosti:
                    if v not in valid_opt_keys:
                        raise _err("Opcija uslova mora pripadati navedenom kontrolnom pitanju.")

    # Ciljevi.
    seen_targets: set[tuple[str, str | None]] = set()
    for c in payload.ciljevi:
        if c.tip_cilja not in TIPOVI_CILJA:
            raise _err("Nepoznat tip cilja.")
        vrednost = c.vrednost.strip() if isinstance(c.vrednost, str) else c.vrednost
        if c.tip_cilja in CILJEVI_SA_VREDNOSCU and not vrednost:
            raise _err("Ciljevi ORGJED/PLATNI_BROJ moraju imati nepraznu vrednost.")
        if c.tip_cilja in CILJEVI_BEZ_VREDNOSTI and vrednost:
            raise _err("Ciljevi SVI/CENTRALA/MALOPRODAJA ne smeju imati vrednost.")
        key = (c.tip_cilja, vrednost if c.tip_cilja in CILJEVI_SA_VREDNOSCU else None)
        if key in seen_targets:
            raise _err("Duple ciljne grupe nisu dozvoljene.")
        seen_targets.add(key)

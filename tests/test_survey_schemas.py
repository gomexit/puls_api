"""Schema-nivo validacije: timezone ugovor, duzine VARCHAR2(100), strip kljuceva."""

import datetime

import pytest
from pydantic import ValidationError

from app.schemas.survey import (
    AdminCiljIn,
    AdminOpcijaIn,
    AdminSurveyCreateRequest,
    AdminUslovIn,
)

TZ = datetime.timezone(datetime.timedelta(hours=2))


def _base(**overrides):
    now = datetime.datetime.now()
    data = dict(
        naziv="A",
        tip_sifra="PULS",
        anonimna=False,
        datum_pocetka=now,
        datum_zavrsetka=now + datetime.timedelta(days=1),
        sekcije=[],
        ciljevi=[],
    )
    data.update(overrides)
    return data


def test_naive_dates_pass():
    AdminSurveyCreateRequest(**_base())  # ne baca


def test_aware_date_rejected():
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    with pytest.raises(ValidationError):
        AdminSurveyCreateRequest(**_base(datum_pocetka=now))


def test_mixed_naive_aware_rejected():
    now = datetime.datetime.now()
    with pytest.raises(ValidationError):
        AdminSurveyCreateRequest(
            **_base(datum_pocetka=now, datum_zavrsetka=now.replace(tzinfo=TZ) + datetime.timedelta(days=1))
        )


def test_cilj_vrednost_100_ok():
    AdminCiljIn(tip_cilja="PLATNI_BROJ", vrednost="x" * 100)


def test_cilj_vrednost_101_rejected():
    with pytest.raises(ValidationError):
        AdminCiljIn(tip_cilja="PLATNI_BROJ", vrednost="x" * 101)


def test_cilj_vrednost_stripped():
    c = AdminCiljIn(tip_cilja="PLATNI_BROJ", vrednost="  409  ")
    assert c.vrednost == "409"


def test_uslov_value_101_rejected():
    with pytest.raises(ValidationError):
        AdminUslovIn(pitanje_kljuc="q1", operator="EQUALS", vrednosti=["y" * 101])


def test_option_key_stripped_and_nonblank():
    o = AdminOpcijaIn(kljuc="  a1  ", tekst="X", redosled=1)
    assert o.kljuc == "a1"
    with pytest.raises(ValidationError):
        AdminOpcijaIn(kljuc="   ", tekst="X", redosled=1)

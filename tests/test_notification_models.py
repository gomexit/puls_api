"""Oracle kompilacija SQLAlchemy tipova za modul OBAVESTENJA (baza je EE8ISO8859P2)."""

import datetime

from sqlalchemy.dialects import oracle
from sqlalchemy.schema import CreateTable

from app.models.obavestenje import (
    OBAVESTENJE_STATUS_ARCHIVED,
    OBAVESTENJE_STATUS_DRAFT,
    OBAVESTENJE_STATUS_PUBLISHED,
    Obavestenje,
    ObavestenjeKategorija,
    ObavestenjePrimalac,
    is_valid_notification_transition,
)


def _ddl(model) -> str:
    return str(CreateTable(model.__table__).compile(dialect=oracle.dialect())).upper()


def test_kategorija_naziv_nvarchar2():
    assert '"NAZIV" NVARCHAR2(100)' in _ddl(ObavestenjeKategorija)


def test_obavestenje_unicode_columns():
    ddl = _ddl(Obavestenje)
    assert '"NASLOV" NVARCHAR2(200)' in ddl
    assert '"KRATAK_TEKST" NVARCHAR2(500)' in ddl
    assert '"SADRZAJ" NCLOB' in ddl


def test_obavestenje_controlled_columns_stay_non_unicode():
    # Kontrolisani kodovi/URL ostaju VARCHAR (Oracle dialekt: "VARCHAR(n CHAR)"),
    # tj. NISU NVARCHAR2 - Unicode ide samo u NASLOV/KRATAK_TEKST/SADRZAJ.
    ddl = _ddl(Obavestenje)
    assert '"STATUS" VARCHAR(20 CHAR)' in ddl
    assert '"AKCIJA_TIP" VARCHAR(30 CHAR)' in ddl
    assert '"AKCIJA_URL" VARCHAR(1000 CHAR)' in ddl


def test_primalac_procitano_char():
    assert '"PROCITANO" CHAR(1)' in _ddl(ObavestenjePrimalac)


def test_status_transitions():
    assert is_valid_notification_transition(OBAVESTENJE_STATUS_DRAFT, OBAVESTENJE_STATUS_PUBLISHED)
    assert is_valid_notification_transition(
        OBAVESTENJE_STATUS_PUBLISHED, OBAVESTENJE_STATUS_ARCHIVED
    )
    # Nema ponovnog objavljivanja ni vracanja unazad.
    assert not is_valid_notification_transition(
        OBAVESTENJE_STATUS_PUBLISHED, OBAVESTENJE_STATUS_PUBLISHED
    )
    assert not is_valid_notification_transition(
        OBAVESTENJE_STATUS_ARCHIVED, OBAVESTENJE_STATUS_PUBLISHED
    )


def test_is_available_rules():
    now = datetime.datetime(2026, 8, 18, 10, 0, 0)
    base = dict(
        kategorija_sifra="OPSTE",
        naslov="n",
        kratak_tekst="k",
        sadrzaj="s",
        akcija_tip="NONE",
    )
    published = Obavestenje(
        status="PUBLISHED",
        datum_objave=now - datetime.timedelta(days=1),
        datum_isteka=now + datetime.timedelta(days=1),
        **base,
    )
    assert published.is_available_to_employees(now)

    draft = Obavestenje(status="DRAFT", datum_objave=None, datum_isteka=None, **base)
    assert not draft.is_available_to_employees(now)

    future = Obavestenje(
        status="PUBLISHED",
        datum_objave=now + datetime.timedelta(days=1),
        datum_isteka=now + datetime.timedelta(days=2),
        **base,
    )
    assert not future.is_available_to_employees(now)

    expired = Obavestenje(
        status="PUBLISHED",
        datum_objave=now - datetime.timedelta(days=2),
        datum_isteka=now - datetime.timedelta(days=1),
        **base,
    )
    assert not expired.is_available_to_employees(now)

    # DDL ugovor: PUBLISHED bez datuma isteka nije dostupno.
    no_expiry = Obavestenje(
        status="PUBLISHED",
        datum_objave=now - datetime.timedelta(days=1),
        datum_isteka=None,
        **base,
    )
    assert not no_expiry.is_available_to_employees(now)

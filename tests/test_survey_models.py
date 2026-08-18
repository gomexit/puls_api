"""Oracle kompilacija SQLAlchemy tipova za modul ANKETE (baza je EE8ISO8859P2)."""

from sqlalchemy.dialects import oracle
from sqlalchemy.schema import CreateTable

from app.models.anketa import Anketa, AnketaTip
from app.models.anketa_predaja import AnketaOdgovor
from app.models.anketa_struktura import AnketaOpcija, AnketaPitanje, AnketaSekcija


def _ddl(model) -> str:
    return str(CreateTable(model.__table__).compile(dialect=oracle.dialect())).upper()


def test_tip_naziv_nvarchar2():
    assert '"NAZIV" NVARCHAR2(200)' in _ddl(AnketaTip)


def test_anketa_naziv_nvarchar2_opis_nclob():
    ddl = _ddl(Anketa)
    assert '"NAZIV" NVARCHAR2(200)' in ddl
    assert '"OPIS" NCLOB' in ddl


def test_sekcija_naziv_nvarchar2():
    assert '"NAZIV" NVARCHAR2(200)' in _ddl(AnketaSekcija)


def test_pitanje_tekst_nclob():
    assert '"TEKST" NCLOB' in _ddl(AnketaPitanje)


def test_opcija_tekst_nvarchar2():
    assert '"TEKST" NVARCHAR2(500)' in _ddl(AnketaOpcija)


def test_odgovor_tekst_nclob():
    assert '"TEKST" NCLOB' in _ddl(AnketaOdgovor)
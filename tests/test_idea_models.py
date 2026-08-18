"""Verifikuje da SQLAlchemy modeli kompajliraju u ispravne Oracle N-tipove
(baza je EE8ISO8859P2 pa korisnicki tekst mora ici u NVARCHAR2/NCLOB)."""

from sqlalchemy.dialects import oracle
from sqlalchemy.schema import CreateTable

from app.models.idea_ciklus import IdeaCiklus
from app.models.ideja import Ideja


def _oracle_ddl(model) -> str:
    return str(CreateTable(model.__table__).compile(dialect=oracle.dialect())).upper()


def test_ciklus_naziv_is_nvarchar2():
    ddl = _oracle_ddl(IdeaCiklus)
    assert '"NAZIV" NVARCHAR2(200)' in ddl


def test_ideja_naslov_is_nvarchar2():
    ddl = _oracle_ddl(Ideja)
    assert '"NASLOV" NVARCHAR2(200)' in ddl


def test_ideja_opis_is_nclob():
    ddl = _oracle_ddl(Ideja)
    assert '"OPIS" NCLOB' in ddl
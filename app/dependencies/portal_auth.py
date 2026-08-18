"""Trusted-service + acting-on-behalf-of autentikacija za ADMIN rute.

GMX Portal poziva ADMIN rute server-to-server, bez PULS login endpointa i bez
Bearer sesije korisnika. Poziv mora nositi dva zaglavlja:

    X-Service-Key:         servisni ključ GMX Portal servera (poverljivost poziva)
    X-Acting-Platni-Broj:  platni broj osobe u čije ime portal izvršava poziv

Servisni ključ sam po sebi NE daje ADMIN pristup. Osoba iz X-Acting-Platni-Broj
mora postojati u PULS bazi i imati AKTIVNU ADMIN ili HR ulogu. Uloge se uvek
čitaju iz baze (PULS_KORISNIK_ULOGE), nikada iz portala.

Redosled provera je bitan: najpre servisni ključ, pa tek onda acting identitet,
tako da pogrešan ključ uvek daje isti odgovor bez otkrivanja acting korisnika.
"""

import re
import secrets

from fastapi import Depends, Header, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, InvalidServiceCredentialsError
from app.db.session import get_db
from app.models.korisnik import (
    STATUS_NALOGA_OMOGUCEN,
    STATUS_ZAPOSLENJA_AKTIVAN,
    Korisnik,
)
from app.repositories.korisnik_repository import KorisnikRepository

ROLE_ADMIN = "ADMIN"
ROLE_HR = "HR"
ACTING_PLATNI_BROJ_MAX = 30

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

# APIKeyHeader daje Swagger security scheme za servisni ključ. auto_error=False:
# odsustvo/greška zaglavlja obrađujemo ručno da bi odgovor bio uvek isti.
service_key_scheme = APIKeyHeader(name="X-Service-Key", auto_error=False)


def _service_key_valid(configured: str | None, provided: str | None) -> bool:
    """Konstantno-vremensko poređenje. Ako ključ nije konfigurisan ili nije poslat,
    pristup se odbija. Ključ se ne trimuje i mora odgovarati tačno. Malformed ili
    non-ASCII vrednost ne sme izazvati izuzetak (poredimo bajtove, ne str)."""
    if not configured or provided is None:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), configured.encode("utf-8"))


def _validate_acting_platni_broj(value: str | None) -> str:
    """Ista pravila kao postojeći auth: trim, obavezno, max 30, bez kontrolnih znakova.
    Svaki neuspeh je generički FORBIDDEN da se ne otkriva koji platni brojevi postoje."""
    if value is None:
        raise ForbiddenError()
    value = value.strip()
    if not value:
        raise ForbiddenError()
    if len(value) > ACTING_PLATNI_BROJ_MAX:
        raise ForbiddenError()
    if _CONTROL_CHARS.search(value):
        raise ForbiddenError()
    return value


def require_portal_admin_or_hr(
    service_key: str | None = Security(service_key_scheme),
    x_acting_platni_broj: str | None = Header(default=None, alias="X-Acting-Platni-Broj"),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> Korisnik:
    # 1) Najpre servisni ključ. Isti 401 za: nema ključa / pogrešan ključ / ključ nije
    #    konfigurisan. Ne otkrivamo razlog i ne obrađujemo acting header dok ključ nije validan.
    if not _service_key_valid(settings.portal_service_key, service_key):
        raise InvalidServiceCredentialsError()

    # 2) Tek sada acting identitet. Sve dalje greške su generički FORBIDDEN (403).
    platni_broj = _validate_acting_platni_broj(x_acting_platni_broj)

    repo = KorisnikRepository(db)
    korisnik = repo.get_by_platni_broj(platni_broj)
    if korisnik is None:
        raise ForbiddenError()
    # Trenutni status i autorizacija u PULS-u. Portal je već autentikovao osobu, pa NE
    # zahtevamo Bearer sesiju, lozinka_hash, promenu lozinke ni potvrdu telefona.
    if korisnik.status_zaposlenja != STATUS_ZAPOSLENJA_AKTIVAN:
        raise ForbiddenError()
    if korisnik.status_naloga != STATUS_NALOGA_OMOGUCEN:
        raise ForbiddenError()
    if korisnik.zakljucan == "D":
        raise ForbiddenError()

    codes = set(repo.get_active_role_codes(korisnik.id))
    if not ({ROLE_ADMIN, ROLE_HR} & codes):
        raise ForbiddenError()

    return korisnik

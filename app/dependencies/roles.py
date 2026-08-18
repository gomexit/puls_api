from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError
from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.repositories.korisnik_repository import KorisnikRepository

ROLE_ADMIN = "ADMIN"
ROLE_HR = "HR"


def require_roles(*allowed_roles: str) -> Callable[..., Korisnik]:
    """Reusable dependency: dozvoljava pristup samo korisnicima sa bar jednom od
    navedenih AKTIVNIH uloga. Uloge se citaju sa backenda (PULS_KORISNIK_ULOGE),
    nikad iz request body-ja ili Android klijenta. Zahteva i potpuno zavrsen
    prvi login tok (preko get_current_ready_user)."""
    allowed = set(allowed_roles)

    def dependency(
        korisnik: Korisnik = Depends(get_current_ready_user),
        db: Session = Depends(get_db),
    ) -> Korisnik:
        codes = set(KorisnikRepository(db).get_active_role_codes(korisnik.id))
        if not (allowed & codes):
            raise ForbiddenError()
        return korisnik

    return dependency


# Admin Ideas rute: samo ADMIN ili HR.
require_admin_or_hr = require_roles(ROLE_ADMIN, ROLE_HR)
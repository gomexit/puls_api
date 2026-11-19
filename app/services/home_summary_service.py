"""Pocetni ekran "Moj kutak" (faza 0): jedan poziv vraca koje module korisnik vidi.

Brojevi novih stavki se dodaju sa svakim modulom (faze 1-5); dok modul ne postoji,
broj je 0. Servis nema upis i ne menja stanje."""

from app.core.modules import MODULES
from app.models.korisnik import Korisnik
from app.services.module_access_service import ModuleAccessService


class HomeSummaryService:
    def __init__(self, module_access: ModuleAccessService):
        self.module_access = module_access

    def summary(self, korisnik: Korisnik) -> dict:
        enabled = self.module_access.enabled_modules(korisnik)
        return {
            "moduli": [
                {
                    "kod": m.kod,
                    "naziv": m.naziv,
                    "aktivan": enabled.get(m.kod, False),
                    "broj_novih": 0,
                }
                for m in MODULES
            ]
        }

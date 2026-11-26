"""Pocetni ekran "Moj kutak" (faza 0): jedan poziv vraca koje module korisnik vidi.

Brojevi novih stavki se dodaju sa svakim modulom (badge_counters); modul bez brojaca
ili iskljucen modul ima 0. PULS IZAZOV: 1 dok aktivan kviz nije odigran. Servis nema upis i ne menja stanje."""

from collections.abc import Callable, Mapping

from app.core.modules import MODULES
from app.models.korisnik import Korisnik
from app.services.module_access_service import ModuleAccessService

# kod_modula -> funkcija koja vraca broj novih stavki za korisnika (samo za ukljucen modul).
BadgeCounter = Callable[[Korisnik], int]


class HomeSummaryService:
    def __init__(self, module_access: ModuleAccessService, badge_counters: Mapping[str, BadgeCounter] | None = None):
        self.module_access = module_access
        self.badge_counters = dict(badge_counters or {})

    def _badge(self, kod: str, aktivan: bool, korisnik: Korisnik) -> int:
        counter = self.badge_counters.get(kod)
        if not aktivan or counter is None:
            return 0
        return max(0, int(counter(korisnik)))

    def summary(self, korisnik: Korisnik) -> dict:
        enabled = self.module_access.enabled_modules(korisnik)
        return {
            "moduli": [
                {
                    "kod": m.kod,
                    "naziv": m.naziv,
                    "aktivan": enabled.get(m.kod, False),
                    "broj_novih": self._badge(m.kod, enabled.get(m.kod, False), korisnik),
                }
                for m in MODULES
            ]
        }

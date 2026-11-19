"""Ukljucivanje novih modula po korisniku (faza 0).

MODUL_<NAZIV> = ISKLJUCEN | PILOT | SVI (PULS_KONFIGURACIJA). PILOT znaci: korisnik
ima aktivan raspored u nekoj od MODUL_PILOT_ORGJED org. jedinica ili je njegov platni
broj u MODUL_PILOT_PLATNI_BROJ. Sve vrednosti se citaju jednim upitom."""

from app.core.modules import (
    MODUL_PILOT,
    MODUL_SVI,
    MODULES,
    MODULES_BY_CODE,
    PILOT_ORGJED_KEY,
    PILOT_PLATNI_BROJ_KEY,
    normalize_mode,
    parse_code_list,
)
from app.models.korisnik import Korisnik
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.module_access_repository import ModuleAccessRepository


class ModuleAccessService:
    def __init__(
        self,
        config_repository: ConfigurationRepository,
        access_repository: ModuleAccessRepository,
    ):
        self.config_repo = config_repository
        self.access_repo = access_repository

    def enabled_modules(self, korisnik: Korisnik) -> dict[str, bool]:
        """{kod_modula: ukljucen} za sve module, u redosledu MODULES."""
        keys = [m.config_key for m in MODULES] + [PILOT_ORGJED_KEY, PILOT_PLATNI_BROJ_KEY]
        values = self.config_repo.get_values(keys)
        modes = {m.kod: normalize_mode(values.get(m.config_key)) for m in MODULES}

        in_pilot: bool | None = None  # racuna se samo ako je neki modul u PILOT rezimu

        result: dict[str, bool] = {}
        for module in MODULES:
            mode = modes[module.kod]
            if mode == MODUL_SVI:
                result[module.kod] = True
            elif mode == MODUL_PILOT:
                if in_pilot is None:
                    in_pilot = self._is_pilot_user(
                        korisnik,
                        parse_code_list(values.get(PILOT_ORGJED_KEY)),
                        parse_code_list(values.get(PILOT_PLATNI_BROJ_KEY)),
                    )
                result[module.kod] = in_pilot
            else:
                result[module.kod] = False
        return result

    def is_enabled(self, korisnik: Korisnik, kod: str) -> bool:
        if kod not in MODULES_BY_CODE:
            return False
        return self.enabled_modules(korisnik)[kod]

    def _is_pilot_user(
        self, korisnik: Korisnik, pilot_orgjed: frozenset[str], pilot_platni_broj: frozenset[str]
    ) -> bool:
        if korisnik.platni_broj in pilot_platni_broj:
            return True
        if not pilot_orgjed:
            return False
        return bool(self.access_repo.active_orgjed_codes(int(korisnik.id)) & pilot_orgjed)

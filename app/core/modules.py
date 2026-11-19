"""Novi moduli PULS-a i njihovo ukljucivanje (faza 0, sql/010_osnova_module.sql).

Svaki modul ima kljuc u PULS_KONFIGURACIJA (MODUL_<NAZIV>) sa jednom od vrednosti:
  ISKLJUCEN - niko ne vidi modul (podrazumevano, i za nepoznatu vrednost)
  PILOT     - samo korisnici iz MODUL_PILOT_ORGJED / MODUL_PILOT_PLATNI_BROJ
  SVI       - svi zaposleni
Nema DB zavisnosti; citanje vrednosti radi ModuleAccessService."""

import dataclasses

MODUL_ISKLJUCEN = "ISKLJUCEN"
MODUL_PILOT = "PILOT"
MODUL_SVI = "SVI"
MODUL_REZIMI = (MODUL_ISKLJUCEN, MODUL_PILOT, MODUL_SVI)

PILOT_ORGJED_KEY = "MODUL_PILOT_ORGJED"
PILOT_PLATNI_BROJ_KEY = "MODUL_PILOT_PLATNI_BROJ"


@dataclasses.dataclass(frozen=True)
class ModuleDefinition:
    kod: str  # stabilan kod u API-ju i u aplikacijama
    config_key: str
    naziv: str


# Redosled je redosled plocica na pocetnom ekranu "Moj kutak".
MODULES: tuple[ModuleDefinition, ...] = (
    ModuleDefinition("POGODNOSTI", "MODUL_POGODNOSTI", "Moje pogodnosti"),
    ModuleDefinition("PITAJ_HR", "MODUL_PITAJ_HR", "Pitaj HR"),
    ModuleDefinition("KVIZ", "MODUL_KVIZ", "Puls izazov"),
    ModuleDefinition("IGRA", "MODUL_IGRA", "Gomex putanja"),
    ModuleDefinition("ZAHVALNICE", "MODUL_ZAHVALNICE", "Hvala, kolega!"),
)
MODULE_CODES: tuple[str, ...] = tuple(m.kod for m in MODULES)
MODULES_BY_CODE: dict[str, ModuleDefinition] = {m.kod: m for m in MODULES}


def normalize_mode(raw: str | None) -> str:
    """Nepoznata, prazna ili nedostajuca vrednost znaci ISKLJUCEN (bezbedan podrazumevani)."""
    value = (raw or "").strip().upper()
    return value if value in MODUL_REZIMI else MODUL_ISKLJUCEN


def parse_code_list(raw: str | None) -> frozenset[str]:
    """'318, 401,,' -> {'318', '401'}. Prazni delovi se preskacu."""
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())

"""Zajednicka pravila ciljanja za nove module (faza 0).

Ista pravila kao kod anketa i obavestenja: SVI, CENTRALA, MALOPRODAJA, ORGJED,
PLATNI_BROJ. CENTRALA i MALOPRODAJA za sada nisu podrzani (nema pouzdanog HR
podatka), pa nikad ne pogadjaju korisnika - isto kao u modulima ANKETE/OBAVESTENJA.
Bez DB zavisnosti: pozivalac prosledjuje ciljeve i podatke o korisniku."""

import dataclasses
from collections.abc import Iterable

CILJ_SVI = "SVI"
CILJ_CENTRALA = "CENTRALA"
CILJ_MALOPRODAJA = "MALOPRODAJA"
CILJ_ORGJED = "ORGJED"
CILJ_PLATNI_BROJ = "PLATNI_BROJ"

TIPOVI_CILJA = (CILJ_SVI, CILJ_CENTRALA, CILJ_MALOPRODAJA, CILJ_ORGJED, CILJ_PLATNI_BROJ)
CILJEVI_BEZ_VREDNOSTI = (CILJ_SVI, CILJ_CENTRALA, CILJ_MALOPRODAJA)
CILJEVI_SA_VREDNOSCU = (CILJ_ORGJED, CILJ_PLATNI_BROJ)
CILJEVI_NEPODRZANI = (CILJ_CENTRALA, CILJ_MALOPRODAJA)


@dataclasses.dataclass(frozen=True)
class Cilj:
    tip: str
    vrednost: str | None = None


@dataclasses.dataclass(frozen=True)
class KorisnikZaCiljanje:
    platni_broj: str
    orgjed_sifre: frozenset[str]


def matches(cilj: Cilj, korisnik: KorisnikZaCiljanje) -> bool:
    tip = (cilj.tip or "").strip().upper()
    vrednost = (cilj.vrednost or "").strip()
    if tip == CILJ_SVI:
        return True
    if tip == CILJ_ORGJED:
        return bool(vrednost) and vrednost in korisnik.orgjed_sifre
    if tip == CILJ_PLATNI_BROJ:
        return bool(vrednost) and vrednost == korisnik.platni_broj
    # CENTRALA, MALOPRODAJA i nepoznati tipovi nikad ne pogadjaju korisnika.
    return False


def matches_any(ciljevi: Iterable[Cilj], korisnik: KorisnikZaCiljanje) -> bool:
    """Korisnik vidi sadrzaj ako ga pogadja bar jedan cilj. Bez ciljeva: niko."""
    return any(matches(c, korisnik) for c in ciljevi)

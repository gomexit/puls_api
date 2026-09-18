"""Registar tipova pitanja ankete (PULS_ANKETA_TIPOVI_PITANJA).

Tipovi se administriraju direktno u bazi; kod grana iskljucivo po KOMPONENTI.
Registar je procesni kes (kratak TTL), pa izmena u bazi vazi bez restarta.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.models.anketa import (
    KOMP_BOOLEAN,
    KOMP_DROPDOWN,
    KOMP_MULTI_CHOICE,
    KOMP_SCALE,
    KOMP_SINGLE_CHOICE,
    KOMP_TEXT,
    KOMPONENTE_JEDNA_OPCIJA,
    KOMPONENTE_SA_OPCIJAMA,
    AnketaTipPitanja,
)

logger = logging.getLogger("puls.question_types")

CACHE_TTL_SECONDS = 60


@dataclass(frozen=True)
class QuestionType:
    sifra: str
    naziv: str
    komponenta: str
    min_vrednost: int | None = None
    max_vrednost: int | None = None
    aktivan: bool = True
    redosled: int = 0

    @property
    def ima_opcije(self) -> bool:
        return self.komponenta in KOMPONENTE_SA_OPCIJAMA

    @property
    def jedna_opcija(self) -> bool:
        return self.komponenta in KOMPONENTE_JEDNA_OPCIJA

    @property
    def je_skala(self) -> bool:
        return self.komponenta == KOMP_SCALE

    @property
    def raspon(self) -> tuple[int, int]:
        return int(self.min_vrednost), int(self.max_vrednost)


# Isti sadrzaj kao seed u sql/008. Koristi se dok tabela jos ne postoji (kod
# deployovan pre DDL-a) i kao podrazumevani izvor u testovima bez baze.
BUILTIN_TYPES: tuple[QuestionType, ...] = (
    QuestionType("SINGLE_CHOICE", "Jedan izbor", KOMP_SINGLE_CHOICE, redosled=10),
    QuestionType("MULTI_CHOICE", "Više izbora", KOMP_MULTI_CHOICE, redosled=20),
    QuestionType("DROPDOWN", "Padajuća lista", KOMP_DROPDOWN, redosled=30),
    QuestionType("TEXT", "Slobodan tekst", KOMP_TEXT, redosled=40),
    QuestionType("BOOLEAN", "Da / Ne", KOMP_BOOLEAN, redosled=50),
    QuestionType("RATING_1_5", "Ocena 1-5", KOMP_SCALE, 1, 5, redosled=60),
    QuestionType("RATING_1_10", "Ocena 1-10", KOMP_SCALE, 1, 10, redosled=70),
)

Provider = Callable[[], dict[str, QuestionType]]


def _builtin_provider() -> dict[str, QuestionType]:
    return {t.sifra: t for t in BUILTIN_TYPES}


def _load_from_db() -> dict[str, QuestionType]:
    from sqlalchemy import select

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(select(AnketaTipPitanja)).scalars().all()
    finally:
        db.close()
    return {
        r.sifra: QuestionType(
            sifra=r.sifra,
            naziv=r.naziv,
            komponenta=r.komponenta,
            min_vrednost=None if r.min_vrednost is None else int(r.min_vrednost),
            max_vrednost=None if r.max_vrednost is None else int(r.max_vrednost),
            aktivan=r.aktivan == "D",
            redosled=int(r.redosled or 0),
        )
        for r in rows
    }


_lock = threading.Lock()
_cache: dict[str, QuestionType] | None = None
_cache_at = 0.0


def _db_provider() -> dict[str, QuestionType]:
    global _cache, _cache_at
    now = time.monotonic()
    with _lock:
        if _cache is not None and now - _cache_at < CACHE_TTL_SECONDS:
            return _cache
        try:
            loaded = _load_from_db()
        except Exception:
            # Tabela jos ne postoji (DDL nije izvrsen) ili baza trenutno nije dostupna:
            # zadrzi poslednje dobro stanje, a bez njega ugradjene tipove.
            logger.warning("Tipovi pitanja nisu ucitani iz baze - koristim postojece stanje.")
            loaded = _cache if _cache is not None else _builtin_provider()
        _cache, _cache_at = loaded, now
        return loaded


_provider: Provider = _db_provider


def set_provider(provider: Provider) -> None:
    global _provider
    _provider = provider


def use_builtin_types() -> None:
    set_provider(_builtin_provider)


def get_question_type(sifra: str | None) -> QuestionType | None:
    if not sifra:
        return None
    return _provider().get(sifra)


def list_question_types(only_active: bool = True) -> list[QuestionType]:
    types = [t for t in _provider().values() if t.aktivan or not only_active]
    return sorted(types, key=lambda t: (t.redosled, t.sifra))

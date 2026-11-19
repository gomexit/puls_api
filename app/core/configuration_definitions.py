"""Centralna, eksplicitna allowlist konfiguracionih kljuceva u PULS_KONFIGURACIJA
koje admin API sme da cita/menja. NAMERNO ne postoji nikakav "wildcard" pristup -
svaki dozvoljeni kljuc ima tacno definisan tip, default vrednost, opis i validator.

Ovi kljucevi su vec u upotrebi kroz postojece servise (PasswordService, AuthService,
IdeaService, NotificationPublishingService) - ovde se NE uvode novi/alternativni
nazivi (npr. PASSWORD_MIN_LENGTH, MAX_LOGIN_ATTEMPTS), vec se koriste tacno postojeci
kljucevi da bi admin izmena stvarno uticala na ponasanje tih servisa."""

import dataclasses
import re
from collections.abc import Callable
from functools import partial
from urllib.parse import urlsplit

from app.core.exceptions import ValidationBusinessError

TIP_BROJ = "BROJ"
TIP_TEKST = "TEKST"

_VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}$")
_INTEGER_RE = re.compile(r"^-?\d+$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_URL_MAX_LEN = 1000
_ALLOWED_URL_SCHEME = "https"

# Version string (CURRENT_VERSION/MIN_SUPPORTED_VERSION) - razumna gornja granica
# pre bilo kakvog parsiranja (sprecava ogroman ulaz da uopste stigne do regexa).
MAX_VERSION_LENGTH = 50

# Broj cifara nakon koga se ceo-broj string odbacuje BEZ pokusaja int() konverzije -
# int() nad ogromnim brojem cifara je skup/spor (CPython ogranicava konverziju od
# 3.11, ali ne oslanjamo se na to - odbacujemo rano i eksplicitno).
_MAX_INTEGER_STRING_LENGTH = 20


def parse_version(value: str) -> tuple[int, ...]:
    """Parsira '1', '1.0', '1.2.3' ili '1.2.3.4' u tuple celih brojeva. Baca
    ValueError za bilo sta drugo (prefiks 'v', razmaci, slova, sufiksi, >4 segmenta)."""
    if not _VERSION_RE.match(value):
        raise ValueError(f"Nevažeći format verzije: {value!r}")
    return tuple(int(p) for p in value.split("."))


def compare_versions(a: str, b: str) -> int:
    """Poredi dve verzije numericki po segmentima uz dopunu nulama (1.2 == 1.2.0,
    1.10 > 1.9). Vraca -1/0/1. Baca ValueError ako format nije validan."""
    pa, pb = parse_version(a), parse_version(b)
    length = max(len(pa), len(pb))
    pa = pa + (0,) * (length - len(pa))
    pb = pb + (0,) * (length - len(pb))
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def validate_int_range(raw: str, minimum: int, maximum: int, label: str) -> str:
    """Trim; mora biti ceo broj bez decimala, u zadatom opsegu. Vraca normalizovan
    string (bez viska nula/razmaka) za upis u bazu. Duzina stringa se ogranicava
    PRE int() konverzije, a ValueError/OverflowError iz int() se hvata eksplicitno
    (predugacak/ogroman unos nikad ne sme dati 500)."""
    v = raw.strip()
    if not v or len(v) > _MAX_INTEGER_STRING_LENGTH or not _INTEGER_RE.fullmatch(v):
        raise ValidationBusinessError(f"{label} mora biti ceo broj.")
    try:
        n = int(v)
    except (ValueError, OverflowError):
        raise ValidationBusinessError(f"{label} mora biti ceo broj.") from None
    if n < minimum or n > maximum:
        raise ValidationBusinessError(f"{label} mora biti u opsegu {minimum}–{maximum}.")
    return str(n)


def validate_version_format(raw: str, label: str) -> str:
    """1 do 4 numericka segmenta - bez prefiksa 'v', razmaka (ni vodecih/pratecih),
    slova i sufiksa. NAMERNO se ne trimuje - razmak bilo gde je nevazeci format.
    Duzina se ogranicava PRE parsiranja."""
    if len(raw) > MAX_VERSION_LENGTH:
        raise ValidationBusinessError(f"{label} je predugačak (maksimalno {MAX_VERSION_LENGTH} karaktera).")
    try:
        parse_version(raw)
    except ValueError:
        raise ValidationBusinessError(
            f"{label} mora biti u formatu 1 do 4 numerička segmenta (npr. 1, 1.0, 1.2.3, 1.2.3.4)."
        ) from None
    return raw


def validate_https_url(raw: str, label: str) -> str:
    """Trimovana vrednost mora biti validan HTTPS URL sa stvarnim hostom, max 1000
    karaktera, bez kontrolnih znakova i bez username/password u URL-u. Odbacuje
    http/file/content/javascript i ostale seme. urlsplit/hostname/port mogu baciti
    ValueError za malformisan URL (npr. otvorena '[' IPv6 zagrada) - to se hvata i
    prevodi u ValidationBusinessError (nikad 500)."""
    v = raw.strip()
    if not v:
        raise ValidationBusinessError(f"{label} ne sme biti prazan string (koristi null).")
    if len(v) > _URL_MAX_LEN:
        raise ValidationBusinessError(f"{label} je predugačak (maksimalno {_URL_MAX_LEN} karaktera).")
    if _CONTROL_CHARS_RE.search(v):
        raise ValidationBusinessError(f"{label} sadrži nevažeće kontrolne znakove.")
    try:
        parts = urlsplit(v)
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        raise ValidationBusinessError(f"{label} mora biti validan HTTPS URL sa hostom.") from None
    if parts.scheme.lower() != _ALLOWED_URL_SCHEME:
        raise ValidationBusinessError(f"{label} mora biti validan HTTPS URL sa hostom.")
    if not hostname:
        raise ValidationBusinessError(f"{label} mora biti validan HTTPS URL sa hostom.")
    if parts.username is not None or parts.password is not None:
        raise ValidationBusinessError(f"{label} ne sme sadržati korisničko ime/lozinku u URL-u.")
    return v


_CODE_LIST_ITEM_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")
_CODE_LIST_MAX_ITEMS = 100
_CODE_LIST_MAX_LEN = 4000


def validate_module_mode(raw: str, label: str) -> str:
    """ISKLJUCEN, PILOT ili SVI (bez obzira na velika/mala slova); upisuje se velikim slovima."""
    from app.core.modules import MODUL_REZIMI

    v = raw.strip().upper()
    if v not in MODUL_REZIMI:
        raise ValidationBusinessError(f"{label} mora biti jedna od vrednosti: {', '.join(MODUL_REZIMI)}.")
    return v


def validate_code_list(raw: str, label: str) -> str:
    """Lista sifara odvojenih zarezom (org. jedinice ili platni brojevi). Svaka sifra je
    1-50 znakova (slova, cifre, '_' ili '-'), najvise 100 sifara, bez duplikata.
    Vraca normalizovan zapis bez razmaka, npr. '318,401'."""
    if len(raw) > _CODE_LIST_MAX_LEN:
        raise ValidationBusinessError(f"{label} je predugačak (maksimalno {_CODE_LIST_MAX_LEN} karaktera).")
    items = [part.strip() for part in raw.split(",") if part.strip()]
    if not items:
        raise ValidationBusinessError(f"{label} ne sme biti prazan (koristi null).")
    if len(items) > _CODE_LIST_MAX_ITEMS:
        raise ValidationBusinessError(f"{label} može imati najviše {_CODE_LIST_MAX_ITEMS} šifara.")
    for item in items:
        if not _CODE_LIST_ITEM_RE.fullmatch(item):
            raise ValidationBusinessError(
                f"{label} sadrži neispravnu šifru. Dozvoljena su slova, cifre, '_' i '-', do 50 znakova."
            )
    unique: list[str] = []
    for item in items:
        if item not in unique:
            unique.append(item)
    return ",".join(unique)


@dataclasses.dataclass(frozen=True)
class ConfigDefinition:
    tip_podatka: str
    default: str | None
    opis: str
    validate: Callable[[str], str]
    nullable: bool = False


CONFIGURATION_DEFINITIONS: dict[str, ConfigDefinition] = {
    "MIN_DUZINA_LOZINKE": ConfigDefinition(
        tip_podatka=TIP_BROJ,
        default="8",
        opis="Minimalna dužina lozinke korisnika (PasswordService).",
        validate=partial(validate_int_range, minimum=8, maximum=128, label="MIN_DUZINA_LOZINKE"),
    ),
    "MAX_NEUSPESNIH_PRIJAVA": ConfigDefinition(
        tip_podatka=TIP_BROJ,
        default="3",
        opis="Maksimalan broj neuspešnih prijava pre zaključavanja naloga (AuthService).",
        validate=partial(validate_int_range, minimum=1, maximum=10, label="MAX_NEUSPESNIH_PRIJAVA"),
    ),
    "TRAJANJE_RESET_KODA_MIN": ConfigDefinition(
        tip_podatka=TIP_BROJ,
        default="15",
        opis="Trajanje validnosti koda za reset lozinke u minutima.",
        validate=partial(validate_int_range, minimum=1, maximum=1440, label="TRAJANJE_RESET_KODA_MIN"),
    ),
    "MAX_IDEJA_PO_CIKLUSU": ConfigDefinition(
        tip_podatka=TIP_BROJ,
        default="3",
        opis="Maksimalan broj ideja koje zaposleni može predati u jednom ciklusu.",
        validate=partial(validate_int_range, minimum=1, maximum=100, label="MAX_IDEJA_PO_CIKLUSU"),
    ),
    "TOP_IDEAS_COUNT": ConfigDefinition(
        tip_podatka=TIP_BROJ,
        default="10",
        opis="Broj najbolje rangiranih ideja koje dobijaju status TOP_10.",
        validate=partial(validate_int_range, minimum=1, maximum=100, label="TOP_IDEAS_COUNT"),
    ),
    "NOTIFICATION_DEFAULT_EXPIRY_DAYS": ConfigDefinition(
        tip_podatka=TIP_BROJ,
        default="30",
        opis="Podrazumevani broj dana do isteka obaveštenja.",
        validate=partial(validate_int_range, minimum=1, maximum=365, label="NOTIFICATION_DEFAULT_EXPIRY_DAYS"),
    ),
    "CURRENT_VERSION": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default="1.0",
        opis="Trenutna verzija Android aplikacije.",
        validate=partial(validate_version_format, label="CURRENT_VERSION"),
    ),
    "MIN_SUPPORTED_VERSION": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default="1.0",
        opis="Minimalna verzija Android aplikacije koja je i dalje podržana.",
        validate=partial(validate_version_format, label="MIN_SUPPORTED_VERSION"),
    ),
    "DOWNLOAD_URL": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default=None,
        opis="HTTPS URL za preuzimanje najnovije verzije Android aplikacije.",
        validate=partial(validate_https_url, label="DOWNLOAD_URL"),
        nullable=True,
    ),
    "MODUL_POGODNOSTI": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default="ISKLJUCEN",
        opis="Modul Moje pogodnosti: ISKLJUCEN, PILOT (samo pilot) ili SVI.",
        validate=partial(validate_module_mode, label="MODUL_POGODNOSTI"),
    ),
    "MODUL_PITAJ_HR": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default="ISKLJUCEN",
        opis="Modul Pitaj HR: ISKLJUCEN, PILOT (samo pilot) ili SVI.",
        validate=partial(validate_module_mode, label="MODUL_PITAJ_HR"),
    ),
    "MODUL_KVIZ": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default="ISKLJUCEN",
        opis="Modul Puls izazov (nedeljni kviz): ISKLJUCEN, PILOT (samo pilot) ili SVI.",
        validate=partial(validate_module_mode, label="MODUL_KVIZ"),
    ),
    "MODUL_IGRA": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default="ISKLJUCEN",
        opis="Modul Gomex putanja (igra dana): ISKLJUCEN, PILOT (samo pilot) ili SVI.",
        validate=partial(validate_module_mode, label="MODUL_IGRA"),
    ),
    "MODUL_ZAHVALNICE": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default="ISKLJUCEN",
        opis="Modul Hvala, kolega: ISKLJUCEN, PILOT (samo pilot) ili SVI.",
        validate=partial(validate_module_mode, label="MODUL_ZAHVALNICE"),
    ),
    "MODUL_PILOT_ORGJED": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default=None,
        opis="Šifre org. jedinica za pilot novih modula, odvojene zarezom (npr. 318).",
        validate=partial(validate_code_list, label="MODUL_PILOT_ORGJED"),
        nullable=True,
    ),
    "MODUL_PILOT_PLATNI_BROJ": ConfigDefinition(
        tip_podatka=TIP_TEKST,
        default=None,
        opis="Platni brojevi za pilot novih modula (npr. testeri iz centrale), odvojeni zarezom.",
        validate=partial(validate_code_list, label="MODUL_PILOT_PLATNI_BROJ"),
        nullable=True,
    ),
}

# Stabilan redosled (insertion order dict-a je garantovan od Python 3.7) - koristi se
# za GET listu (uvek svi kljucevi u istom redosledu) i za batch citanje.
ALLOWED_CONFIGURATION_KEYS: tuple[str, ...] = tuple(CONFIGURATION_DEFINITIONS.keys())

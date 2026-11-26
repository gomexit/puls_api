"""Filter neprimerenih reci za zahvalnice (srpski, latinica i cirilica).

Tekst se normalizuje (mala slova, bez dijakritike, cirilica -> latinica, cesce
zamene cifara i ponovljena slova), pa se svaka rec proverava da li POCINJE nekim od
zabranjenih korena. Namerno je jednostavan: cilj je da zaustavi ociglednu psovku i
uvredu; za ostalo postoje prijave kolega i HR."""

import re
import unicodedata

_CIRILICA = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "dj", "е": "e", "ж": "z", "з": "z",
    "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "c", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "c", "џ": "dz", "ш": "s",
}
_ZAMENE = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "đ": "dj"}

# Koreni (posle normalizacije). Rec koja pocinje korenom je zabranjena.
_KORENI = (
    "jeb", "pojeb", "zajeb", "najeb", "izjeb", "ujeb", "odjeb", "razjeb",
    "pick", "pizd", "kurac", "kurc", "kurv", "govn", "sranj", "seronj", "sere",
    "peder", "drkadz", "debil", "kreten", "idiot", "retard", "mamuti", "majkuti",
)
_RECI = re.compile(r"[a-z]+")


def normalize(text: str) -> str:
    out = []
    for ch in text.lower():
        ch = _CIRILICA.get(ch, ch)
        ch = _ZAMENE.get(ch, ch)
        out.append(ch)
    s = unicodedata.normalize("NFKD", "".join(out))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"(.)\1{2,}", r"\1", s)  # "jeeeeb" -> "jeb"


def is_inappropriate(text: str) -> bool:
    s = normalize(text)
    words = _RECI.findall(s)
    if any(w.startswith(_KORENI) for w in words):
        return True
    # "j.e.b" / "j e b": isti koreni u tekstu bez razmaka i interpunkcije, samo za duze korene.
    squashed = "".join(words)
    return any(k in squashed for k in _KORENI if len(k) >= 5)

"""GOMEX PUTANJA - generator i provera nivoa (cist Python, bez baze).

Tabla je N x N polja (tlocrt prodavnice). Igrac povlaci jednu liniju koja:
- pocinje na tacki 1, prolazi kroz numerisane tacke redom i zavrsava na poslednjoj (kasa),
- prolazi kroz SVA polja tacno jednom,
- ide samo na susedno polje (gore/dole/levo/desno) i ne prelazi zid (raf).

Nivo se pravi iz nasumicne Hamiltonove putanje (zmijolika putanja + "backbite"
potezi), pa uvek ima resenje. Zidovi se stavljaju samo izmedju polja koja u toj
putanji nisu uzastopna, pa nikad ne blokiraju resenje. Isti datum uvek daje isti
nivo (seme je datum), tako da svi zaposleni igraju isto.
"""

import datetime
import itertools
import random

Cell = tuple[int, int]

# (velicina, broj tacaka, broj zidova) po danu u nedelji: ponedeljak najlaksi, vikend najtezi.
_TEZINA = {
    0: (6, 6, 6),
    1: (6, 6, 6),
    2: (7, 8, 9),
    3: (7, 8, 9),
    4: (7, 8, 9),
    5: (8, 10, 12),
    6: (8, 10, 12),
}
_BACKBITE_PO_POLJU = 40


def difficulty(datum: datetime.date) -> tuple[int, int, int]:
    """(velicina, broj_tacaka, broj_zidova) za dan."""
    return _TEZINA[datum.weekday()]


def _neighbors(cell: Cell, n: int) -> list[Cell]:
    r, c = cell
    out = []
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < n and 0 <= cc < n:
            out.append((rr, cc))
    return out


def _serpentine(n: int) -> list[Cell]:
    path: list[Cell] = []
    for r in range(n):
        cols = range(n) if r % 2 == 0 else range(n - 1, -1, -1)
        path.extend((r, c) for c in cols)
    return path


def random_hamiltonian_path(n: int, rng: random.Random) -> list[Cell]:
    """Nasumicna putanja kroz sva polja (backbite algoritam)."""
    path = _serpentine(n)
    for _ in range(_BACKBITE_PO_POLJU * n * n):
        if rng.random() < 0.5:
            path.reverse()
        end = path[-1]
        index = {cell: i for i, cell in enumerate(path)}
        nb = rng.choice(_neighbors(end, n))
        i = index[nb]
        if i == len(path) - 2:
            continue  # vec susedno u putanji
        path = path[: i + 1] + path[i + 1 :][::-1]
    return path


def _edge(a: Cell, b: Cell) -> tuple[int, int, int, int]:
    (r1, c1), (r2, c2) = sorted((a, b))
    return (r1, c1, r2, c2)


def generate(datum: datetime.date) -> tuple[dict, list[Cell]]:
    """Vraca (podaci za aplikaciju, resenje). Deterministicki za datum."""
    n, broj_tacaka, broj_zidova = difficulty(datum)
    rng = random.Random(f"gomex-putanja:{datum.isoformat()}")
    path = random_hamiltonian_path(n, rng)
    total = n * n

    # Tacke: prva i poslednja + ravnomerno rasporedjene unutrasnje (bar 2 polja razmaka).
    unutrasnje = broj_tacaka - 2
    korak = (total - 1) / (unutrasnje + 1)
    indeksi = [0]
    for k in range(1, unutrasnje + 1):
        osnova = round(k * korak)
        pomak = rng.randint(-max(1, int(korak / 3)), max(1, int(korak / 3)))
        i = min(total - 2, max(indeksi[-1] + 2, osnova + pomak))
        indeksi.append(i)
    indeksi.append(total - 1)
    tacke = [list(path[i]) for i in indeksi]

    # Zidovi: medju susedima koji nisu uzastopni u putanji.
    u_putanji = {_edge(path[i], path[i + 1]) for i in range(total - 1)}
    kandidati = sorted(
        {_edge((r, c), nb) for r in range(n) for c in range(n) for nb in _neighbors((r, c), n)} - u_putanji
    )
    rng.shuffle(kandidati)
    zidovi = [list(e) for e in sorted(kandidati[:broj_zidova])]

    podaci = {"velicina": n, "tacke": tacke, "zidovi": zidovi}
    return podaci, path


def is_valid_solution(podaci: dict, putanja: list) -> bool:
    """Da li je putanja ispravno resenje nivoa (ne mora biti ista kao sacuvana)."""
    try:
        n = int(podaci["velicina"])
        tacke = [(int(t[0]), int(t[1])) for t in podaci["tacke"]]
        zidovi = {_edge((int(z[0]), int(z[1])), (int(z[2]), int(z[3]))) for z in podaci["zidovi"]}
        cells = [(int(p[0]), int(p[1])) for p in putanja]
    except (KeyError, TypeError, ValueError, IndexError):
        return False
    if len(cells) != n * n or len(set(cells)) != n * n:
        return False
    if any(not (0 <= r < n and 0 <= c < n) for r, c in cells):
        return False
    for a, b in itertools.pairwise(cells):
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            return False
        if _edge(a, b) in zidovi:
            return False
    if cells[0] != tacke[0] or cells[-1] != tacke[-1]:
        return False
    pozicija = {cell: i for i, cell in enumerate(cells)}
    redosled = [pozicija[t] for t in tacke]
    return redosled == sorted(redosled)

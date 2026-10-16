"""Zajednicko sortiranje po koloni za admin GET liste (uz paginaciju).

Ugovor (isti na svim listama):
    ?sort_by=<polje iz odgovora>&sort_dir=asc|desc

- Sortira se po JEDNOJ koloni. Oba parametra su opciona; bez njih vazi podrazumevani
  redosled endpointa (isti kao pre uvodjenja sortiranja).
- Dozvoljene kolone su eksplicitna lista po endpointu (mapa polje -> SQL izraz).
  Tekst korisnika NIKAD ne ulazi u SQL; nepoznato polje je 422.
- Paginacija ostaje stabilna: uvek se dodaje tie-breaker (ID) u istom smeru, pa isti red
  ne moze da se pojavi na dve strane niti da nestane izmedju strana.
- NULL vrednosti idu na kraj u oba smera (NULLS LAST).
- Tekstualne kolone se sortiraju jezicki (NLSSORT XCROATIAN) jer je Oracle sesija BINARY,
  a binarni redosled stavlja Š, Ž, Ć, Č, Đ iza Z.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from fastapi import Query
from sqlalchemy import func, literal_column
from sqlalchemy.sql.elements import ColumnElement

from app.core.exceptions import ValidationBusinessError

SortDirection = Literal["asc", "desc"]
SORT_DIRECTIONS: tuple[str, ...] = ("asc", "desc")

# XCROATIAN daje ispravan redosled srpske latinice (c < č < ć < d < đ < s < š < z < ž).
# Vrednost je konstanta u kodu (ne dolazi od korisnika), pa se ugradjuje kao literal.
TEXT_COLLATION = "NLS_SORT=XCROATIAN"


@dataclass(frozen=True)
class SortColumn:
    """Jedna sortabilna kolona: SQL izraz i da li je tekst (jezicko sortiranje)."""

    expr: ColumnElement
    text: bool = False


@dataclass(frozen=True)
class SortSpec:
    by: str
    dir: SortDirection = "asc"


def build_order_by(
    spec: SortSpec,
    columns: Mapping[str, SortColumn],
    tiebreaker: ColumnElement,
) -> list[ColumnElement]:
    """Pravi ORDER BY: [kolona (NULLS LAST), tie-breaker]. `spec.by` mora biti kljuc mape;
    inace je to greska programera (HTTP sloj je vec odbio nepoznato polje sa 422)."""
    column = columns.get(spec.by)
    if column is None:
        raise ValueError(f"Kolona '{spec.by}' nije dozvoljena za sortiranje.")

    expr = column.expr
    if column.text:
        expr = func.nlssort(expr, literal_column(f"'{TEXT_COLLATION}'"))

    descending = spec.dir == "desc"
    primary = (expr.desc() if descending else expr.asc()).nulls_last()
    tie = tiebreaker.desc() if descending else tiebreaker.asc()
    return [primary, tie]


def sort_params(
    allowed: Sequence[str],
    default_by: str,
    default_dir: SortDirection = "asc",
) -> Callable[..., SortSpec]:
    """FastAPI dependency: cita `sort_by`/`sort_dir`, validira ih naspram `allowed` i vraca
    SortSpec (uvek, sa podrazumevanim vrednostima). U Swagger-u su oba parametra enum.

    - bez parametara: default_by + default_dir;
    - samo sort_dir: smer se primenjuje na default_by;
    - samo sort_by: smer je `asc`."""
    allowed_columns = tuple(allowed)
    if default_by not in allowed_columns:
        raise ValueError("default_by mora biti medju dozvoljenim kolonama.")
    if default_dir not in SORT_DIRECTIONS:
        raise ValueError("default_dir mora biti 'asc' ili 'desc'.")
    allowed_text = ", ".join(allowed_columns)

    def dependency(
        sort_by: str | None = Query(
            default=None,
            description=(
                f"Kolona za sortiranje (jedna). Dozvoljeno: {allowed_text}. "
                f"Podrazumevano `{default_by}`."
            ),
            json_schema_extra={"enum": list(allowed_columns)},
        ),
        sort_dir: str | None = Query(
            default=None,
            description=(
                "Smer sortiranja: `asc` ili `desc`. "
                f"Podrazumevano `{default_dir}` za `{default_by}`, a `asc` za ostale kolone. "
                "Prazne (NULL) vrednosti su uvek na kraju."
            ),
            json_schema_extra={"enum": list(SORT_DIRECTIONS)},
        ),
    ) -> SortSpec:
        by = (sort_by or "").strip().lower() or None
        direction = (sort_dir or "").strip().lower() or None

        if by is not None and by not in allowed_columns:
            raise ValidationBusinessError(
                f"Nedozvoljena kolona za sortiranje. Dozvoljeno: {allowed_text}."
            )
        if direction is not None and direction not in SORT_DIRECTIONS:
            raise ValidationBusinessError("sort_dir mora biti 'asc' ili 'desc'.")

        if by is None:
            return SortSpec(by=default_by, dir=direction or default_dir)  # type: ignore[arg-type]
        return SortSpec(by=by, dir=direction or "asc")  # type: ignore[arg-type]

    return dependency

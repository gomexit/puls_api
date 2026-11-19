from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.sorting import SortColumn, SortSpec, build_order_by
from app.models.slika import SLIKA_STATUS_AKTIVNA, SLIKA_STATUS_ARHIVIRANA, Slika

# Eksplicitna selekcija metadata kolona: nikada `SELECT *`, nikada SADRZAJ (BLOB).
_ADMIN_COLUMNS = (
    Slika.id,
    Slika.naziv,
    Slika.originalni_naziv_fajla,
    Slika.mime_tip,
    Slika.velicina_bajtova,
    Slika.sirina,
    Slika.visina,
    Slika.status,
    Slika.kreirao_platni_broj,
    Slika.izmenio_platni_broj,
    Slika.datum_kreiranja,
    Slika.datum_izmene,
)

_CONTENT_COLUMNS = (
    Slika.id,
    Slika.mime_tip,
    Slika.velicina_bajtova,
    Slika.sha256,
    Slika.status,
    Slika.sadrzaj,
)

_STATUS_FLOW = case(
    {SLIKA_STATUS_AKTIVNA: 1, SLIKA_STATUS_ARHIVIRANA: 2},
    value=Slika.status,
    else_=3,
)
ADMIN_SORT_COLUMNS: dict[str, SortColumn] = {
    "id": SortColumn(Slika.id),
    "naziv": SortColumn(Slika.naziv, text=True),
    "status": SortColumn(_STATUS_FLOW),
    "velicina_bajtova": SortColumn(Slika.velicina_bajtova),
    "datum_kreiranja": SortColumn(Slika.datum_kreiranja),
    "datum_izmene": SortColumn(Slika.datum_izmene),
}
# Najnovije slike prve.
ADMIN_DEFAULT_SORT = SortSpec(by="datum_kreiranja", dir="desc")


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ImageRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------ employee
    def get_active_content(self, image_id: int):
        stmt = select(*_CONTENT_COLUMNS).where(
            Slika.id == image_id, Slika.status == SLIKA_STATUS_AKTIVNA
        )
        return self.db.execute(stmt).first()

    def get_active_etag(self, image_id: int) -> str | None:
        """Samo SHA-256 (bez BLOB-a) - za odgovor 304 na If-None-Match."""
        stmt = select(Slika.sha256).where(Slika.id == image_id, Slika.status == SLIKA_STATUS_AKTIVNA)
        return self.db.execute(stmt).scalar_one_or_none()

    # --------------------------------------------------------------- admin
    def list_admin(
        self,
        status: str | None,
        search: str | None,
        page: int,
        page_size: int,
        sort: SortSpec | None = None,
    ):
        conditions = []
        if status is not None:
            conditions.append(Slika.status == status)
        if search:
            pattern = f"%{_escape_like(search.lower())}%"
            conditions.append(func.lower(Slika.naziv).like(pattern, escape="\\"))

        total = self.db.execute(select(func.count()).select_from(Slika).where(*conditions)).scalar_one()
        order_by = build_order_by(sort or ADMIN_DEFAULT_SORT, ADMIN_SORT_COLUMNS, Slika.id)
        stmt = (
            select(*_ADMIN_COLUMNS)
            .where(*conditions)
            .order_by(*order_by)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.execute(stmt).all()), int(total)

    def get_admin(self, image_id: int):
        stmt = select(*_ADMIN_COLUMNS).where(Slika.id == image_id)
        return self.db.execute(stmt).first()

    def get_admin_content(self, image_id: int):
        stmt = select(*_CONTENT_COLUMNS).where(Slika.id == image_id)
        return self.db.execute(stmt).first()

    # --------------------------------------------------------------- write
    def get_for_update(self, image_id: int) -> Slika | None:
        """Zakljucava red (FOR UPDATE). SADRZAJ je deferred i ne ucitava se."""
        stmt = select(Slika).where(Slika.id == image_id).with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    def add(self, slika: Slika) -> Slika:
        self.db.add(slika)
        return slika

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.onboarding_dokument import (
    ONB_DOKUMENT_STATUS_PUBLISHED,
    OnboardingDokument as Dok,
)

# Eksplicitna selekcija metadata kolona: nikada `SELECT *`, nikada SADRZAJ (BLOB).
_EMPLOYEE_COLUMNS = (
    Dok.id,
    Dok.naziv,
    Dok.opis,
    Dok.originalni_naziv_fajla,
    Dok.velicina_bajtova,
    Dok.redosled,
    Dok.verzija,
    Dok.datum_objave,
)

_ADMIN_COLUMNS = (
    Dok.id,
    Dok.naziv,
    Dok.opis,
    Dok.originalni_naziv_fajla,
    Dok.mime_tip,
    Dok.velicina_bajtova,
    Dok.sha256,
    Dok.status,
    Dok.redosled,
    Dok.verzija,
    Dok.kreirao_platni_broj,
    Dok.izmenio_platni_broj,
    Dok.datum_kreiranja,
    Dok.datum_izmene,
    Dok.datum_objave,
)

_CONTENT_COLUMNS = (
    Dok.id,
    Dok.originalni_naziv_fajla,
    Dok.mime_tip,
    Dok.velicina_bajtova,
    Dok.sha256,
    Dok.status,
    Dok.sadrzaj,
)

_ORDER = (Dok.redosled.asc(), Dok.id.asc())


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class OnboardingDocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------ employee
    def list_published(self):
        stmt = (
            select(*_EMPLOYEE_COLUMNS)
            .where(Dok.status == ONB_DOKUMENT_STATUS_PUBLISHED)
            .order_by(*_ORDER)
        )
        return list(self.db.execute(stmt).all())

    def get_published(self, document_id: int):
        stmt = select(*_EMPLOYEE_COLUMNS).where(
            Dok.id == document_id, Dok.status == ONB_DOKUMENT_STATUS_PUBLISHED
        )
        return self.db.execute(stmt).first()

    def get_published_content(self, document_id: int):
        stmt = select(*_CONTENT_COLUMNS).where(
            Dok.id == document_id, Dok.status == ONB_DOKUMENT_STATUS_PUBLISHED
        )
        return self.db.execute(stmt).first()

    # --------------------------------------------------------------- admin
    def list_admin(self, status: str | None, search: str | None, page: int, page_size: int):
        conditions = []
        if status is not None:
            conditions.append(Dok.status == status)
        if search:
            pattern = f"%{_escape_like(search.lower())}%"
            conditions.append(func.lower(Dok.naziv).like(pattern, escape="\\"))

        total = self.db.execute(select(func.count()).select_from(Dok).where(*conditions)).scalar_one()
        stmt = (
            select(*_ADMIN_COLUMNS)
            .where(*conditions)
            .order_by(*_ORDER)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.execute(stmt).all()), int(total)

    def get_admin(self, document_id: int):
        stmt = select(*_ADMIN_COLUMNS).where(Dok.id == document_id)
        return self.db.execute(stmt).first()

    def get_admin_content(self, document_id: int):
        stmt = select(*_CONTENT_COLUMNS).where(Dok.id == document_id)
        return self.db.execute(stmt).first()

    # --------------------------------------------------------------- write
    def get_for_update(self, document_id: int) -> Dok | None:
        """Zakljucava red (FOR UPDATE). SADRZAJ je deferred i ne ucitava se."""
        stmt = select(Dok).where(Dok.id == document_id).with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    def add(self, dokument: Dok) -> Dok:
        self.db.add(dokument)
        return dokument

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, BinaryIO

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ImageArchivedError,
    ImageNotFoundError,
    InvalidImageStatusError,
    ValidationBusinessError,
)
from app.core.sorting import SortSpec
from app.models.korisnik import Korisnik
from app.models.slika import (
    SLIKA_STATUS_AKTIVNA,
    SLIKA_STATUS_ARHIVIRANA,
    SLIKA_STATUSI,
    Slika,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.image_repository import ADMIN_DEFAULT_SORT, ImageRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.image_processing import (
    NAZIV_MAX,
    ProcessedImage,
    max_size_bytes,
    process_image_upload,
    read_limited,
    validate_name,
)

ENTITY_TYPE = "SLIKA"
SEARCH_MAX = NAZIV_MAX
EMPLOYEE_URL_PREFIX = "/api/v1/images"


@dataclass(frozen=True)
class ImageContent:
    """Binarni sadrzaj spreman za HTTP odgovor (u memoriji; slika je najvise 1200 px)."""

    content: bytes
    sha256: str
    mime_type: str


def _to_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if hasattr(value, "read"):  # oracledb LOB, ako driver nije vec konvertovao u bytes
        value = value.read()
    return bytes(value)


def _admin_view(obj: Any) -> dict:
    image_id = int(obj.id)
    return {
        "id": image_id,
        "naziv": obj.naziv,
        "originalni_naziv_fajla": obj.originalni_naziv_fajla,
        "mime_tip": obj.mime_tip,
        "velicina_bajtova": int(obj.velicina_bajtova),
        "sirina": int(obj.sirina),
        "visina": int(obj.visina),
        "status": obj.status,
        "kreirao_platni_broj": obj.kreirao_platni_broj,
        "izmenio_platni_broj": obj.izmenio_platni_broj,
        "datum_kreiranja": obj.datum_kreiranja,
        "datum_izmene": obj.datum_izmene,
        "url": f"{EMPLOYEE_URL_PREFIX}/{image_id}",
    }


def _content_view(row: Any) -> ImageContent:
    return ImageContent(content=_to_bytes(row.sadrzaj), sha256=row.sha256, mime_type=row.mime_tip)


def normalize_status(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if normalized not in SLIKA_STATUSI:
        raise InvalidImageStatusError()
    return normalized


class ImageService:
    """Modul SLIKE (faza 0): slike kao Oracle BLOB, za pogodnosti, kviz i ostale module.
    Zaposleni samo citaju AKTIVNE slike; admin/HR upravlja kroz GMX Portal (OBO).
    Izmene: jedna transakcija, SELECT FOR UPDATE, odgovor pre commit-a, rollback na gresku."""

    def __init__(
        self,
        db: Session,
        repository: ImageRepository | None = None,
        audit_service: AuditService | None = None,
        settings: Settings | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.repo = repository or ImageRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )
        self._now_fn = now_fn or datetime.datetime.now

    # ================================================================ upload
    def parse_upload(
        self, stream: BinaryIO, filename: str | None, content_type: str | None
    ) -> ProcessedImage:
        """Cita najvise limit + 1 bajt, validira i smanjuje sliku. Nema pristupa bazi."""
        data = read_limited(stream, max_size_bytes(self.settings.image_max_size_mb))
        return process_image_upload(data, filename, content_type)

    # ============================================================== EMPLOYEE
    def get_active_content(self, image_id: int) -> ImageContent:
        row = self.repo.get_active_content(image_id)
        if row is None:
            raise ImageNotFoundError()
        return _content_view(row)

    def get_active_etag(self, image_id: int) -> str:
        sha = self.repo.get_active_etag(image_id)
        if sha is None:
            raise ImageNotFoundError()
        return str(sha)

    # ================================================================= ADMIN
    def list_admin(
        self,
        status: str | None,
        search: str | None,
        page: int,
        page_size: int,
        sort: SortSpec | None = None,
    ) -> dict:
        status_norm = normalize_status(status) if status is not None else None
        search_norm: str | None = None
        if search is not None:
            search_norm = search.strip()
            if len(search_norm) > SEARCH_MAX:
                raise ValidationBusinessError(f"Pretraga može imati najviše {SEARCH_MAX} karaktera.")
            search_norm = search_norm or None
        effective_sort = sort or ADMIN_DEFAULT_SORT
        rows, total = self.repo.list_admin(status_norm, search_norm, page, page_size, effective_sort)
        return {
            "items": [_admin_view(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "sort_by": effective_sort.by,
            "sort_dir": effective_sort.dir,
        }

    def get_admin(self, image_id: int) -> dict:
        row = self.repo.get_admin(image_id)
        if row is None:
            raise ImageNotFoundError()
        return _admin_view(row)

    def get_admin_content(self, image_id: int) -> ImageContent:
        row = self.repo.get_admin_content(image_id)
        if row is None:
            raise ImageNotFoundError()
        return _content_view(row)

    def create(self, actor: Korisnik, naziv: str | None, image: ProcessedImage) -> dict:
        naziv_norm = validate_name(naziv)
        try:
            now = self._now_fn()
            slika = Slika(
                naziv=naziv_norm,
                originalni_naziv_fajla=image.original_name,
                mime_tip=image.mime_type,
                velicina_bajtova=image.size,
                sirina=image.width,
                visina=image.height,
                sha256=image.sha256,
                sadrzaj=image.content,
                status=SLIKA_STATUS_AKTIVNA,
                kreirao_platni_broj=actor.platni_broj,
                izmenio_platni_broj=actor.platni_broj,
                datum_kreiranja=now,
                datum_izmene=now,
            )
            self.repo.add(slika)
            self.db.flush()  # dobija ID pre sastavljanja odgovora i audita
            self._audit(actor, AuditAction.ADMIN_IMAGE_UPLOADED, slika, "UPLOADED")
            view = _admin_view(slika)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def rename(self, actor: Korisnik, image_id: int, naziv: str | None) -> dict:
        naziv_norm = validate_name(naziv)
        try:
            slika = self._locked(image_id)
            if slika.status == SLIKA_STATUS_ARHIVIRANA:
                raise ImageArchivedError()
            if slika.naziv != naziv_norm:
                slika.naziv = naziv_norm
                slika.izmenio_platni_broj = actor.platni_broj
                slika.datum_izmene = self._now_fn()
                self.db.flush()
                self._audit(actor, AuditAction.ADMIN_IMAGE_RENAMED, slika, "RENAMED")
            view = _admin_view(slika)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def change_status(self, actor: Korisnik, image_id: int, novi_status: str | None) -> dict:
        target = normalize_status(novi_status)
        try:
            slika = self._locked(image_id)
            if slika.status == target:  # idempotentno
                view = _admin_view(slika)
                self.db.commit()
                return view
            if slika.status == SLIKA_STATUS_ARHIVIRANA:
                raise ImageArchivedError()
            # Jedini preostali prelaz: AKTIVNA -> ARHIVIRANA.
            slika.status = target
            slika.izmenio_platni_broj = actor.platni_broj
            slika.datum_izmene = self._now_fn()
            self.db.flush()
            self._audit(actor, AuditAction.ADMIN_IMAGE_ARCHIVED, slika, "ARCHIVED")
            view = _admin_view(slika)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # --------------------------------------------------------------- helpers
    def _locked(self, image_id: int) -> Slika:
        slika = self.repo.get_for_update(image_id)
        if slika is None:
            raise ImageNotFoundError()
        return slika

    def _audit(self, actor: Korisnik, sifra_akcije: str, slika: Slika, label: str) -> None:
        # DETALJI: samo id/status/dimenzije/naziv akcije. Nikad sadrzaj ni SHA-256.
        self.audit_service.log(
            sifra_akcije,
            korisnik_id=actor.id,
            platni_broj=actor.platni_broj,
            tip_entiteta=ENTITY_TYPE,
            entitet_id=str(int(slika.id)),
            detalji=(
                f"image_id={int(slika.id)}; status={slika.status}; "
                f"dimenzije={int(slika.sirina)}x{int(slika.visina)}; akcija={label}"
            ),
        )

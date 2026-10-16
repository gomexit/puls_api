import datetime
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    InvalidOnboardingDocumentStatusError,
    OnboardingDocumentArchivedError,
    OnboardingDocumentNotDraftError,
    OnboardingDocumentNotFoundError,
    ValidationBusinessError,
)
from app.models.korisnik import Korisnik
from app.models.onboarding_dokument import (
    ONB_DOKUMENT_MIME_PDF,
    ONB_DOKUMENT_STATUS_ARCHIVED,
    ONB_DOKUMENT_STATUS_DRAFT,
    ONB_DOKUMENT_STATUS_PUBLISHED,
    ONB_DOKUMENT_STATUSI,
    OnboardingDokument,
    is_valid_onboarding_document_transition,
)
from app.repositories.audit_repository import AuditRepository
from app.core.sorting import SortSpec
from app.repositories.onboarding_document_repository import (
    ADMIN_DEFAULT_SORT,
    OnboardingDocumentRepository,
)
from app.services.audit_service import AuditAction, AuditService
from app.services.onboarding_pdf import (
    NAZIV_MAX,
    ValidatedPdf,
    max_size_bytes,
    read_limited,
    validate_metadata,
    validate_pdf_upload,
)

ENTITY_TYPE = "ONBOARDING_DOKUMENT"
SEARCH_MAX = NAZIV_MAX


@dataclass(frozen=True)
class DocumentContent:
    """Binarni sadrzaj spreman za HTTP odgovor. `content` je bytes u memoriji (limit je
    ONBOARDING_PDF_MAX_SIZE_MB), pa nijedan Oracle LOB ne ostaje otvoren posle sesije."""

    filename: str
    content: bytes
    sha256: str
    size: int
    mime_type: str = ONB_DOKUMENT_MIME_PDF


def _to_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if hasattr(value, "read"):  # oracledb LOB, ako driver nije vec konvertovao u bytes
        value = value.read()
    return bytes(value)


def _opt_text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "read"):
        value = value.read()
    return str(value)


def _employee_view(obj: Any) -> dict:
    return {
        "id": int(obj.id),
        "naziv": obj.naziv,
        "opis": _opt_text(obj.opis),
        "originalni_naziv_fajla": obj.originalni_naziv_fajla,
        "velicina_bajtova": int(obj.velicina_bajtova),
        "redosled": int(obj.redosled),
        "verzija": int(obj.verzija),
        "datum_objave": obj.datum_objave,
    }


def _admin_view(obj: Any) -> dict:
    return {
        **_employee_view(obj),
        "mime_tip": obj.mime_tip,
        "sha256": obj.sha256,
        "status": obj.status,
        "kreirao_platni_broj": obj.kreirao_platni_broj,
        "izmenio_platni_broj": obj.izmenio_platni_broj,
        "datum_kreiranja": obj.datum_kreiranja,
        "datum_izmene": obj.datum_izmene,
    }


def _content_view(row: Any) -> DocumentContent:
    return DocumentContent(
        filename=row.originalni_naziv_fajla,
        content=_to_bytes(row.sadrzaj),
        sha256=row.sha256,
        size=int(row.velicina_bajtova),
        mime_type=ONB_DOKUMENT_MIME_PDF,
    )


def normalize_status(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if normalized not in ONB_DOKUMENT_STATUSI:
        raise InvalidOnboardingDocumentStatusError()
    return normalized


class OnboardingDocumentService:
    """Modul ONBOARDING DOKUMENTI (PDF kao Oracle BLOB). Employee citanje je ogranicano na
    PUBLISHED; admin/HR upravlja kroz GMX Portal (OBO). Sve izmene: jedna transakcija,
    SELECT FOR UPDATE, odgovor se sastavlja PRE commit-a, tacno jedan commit, rollback na
    svaku gresku, bez DB upita posle commit-a."""

    def __init__(
        self,
        db: Session,
        repository: OnboardingDocumentRepository | None = None,
        audit_service: AuditService | None = None,
        settings: Settings | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.repo = repository or OnboardingDocumentRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )
        self._now_fn = now_fn or datetime.datetime.now

    # ================================================================ upload
    def parse_upload(
        self, stream: BinaryIO, filename: str | None, content_type: str | None
    ) -> ValidatedPdf:
        """Cita najvise limit + 1 bajt i validira PDF. Nema pristupa bazi."""
        limit = max_size_bytes(self.settings.onboarding_pdf_max_size_mb)
        data = read_limited(stream, limit)
        return validate_pdf_upload(data, filename, content_type)

    # ============================================================== EMPLOYEE
    def list_published(self) -> list[dict]:
        return [_employee_view(r) for r in self.repo.list_published()]

    def get_published(self, document_id: int) -> dict:
        row = self.repo.get_published(document_id)
        if row is None:
            raise OnboardingDocumentNotFoundError()
        return _employee_view(row)

    def get_published_content(self, document_id: int) -> DocumentContent:
        row = self.repo.get_published_content(document_id)
        if row is None:
            raise OnboardingDocumentNotFoundError()
        return _content_view(row)

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
        rows, total = self.repo.list_admin(
            status_norm, search_norm, page, page_size, effective_sort
        )
        return {
            "items": [_admin_view(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "sort_by": effective_sort.by,
            "sort_dir": effective_sort.dir,
        }

    def get_admin(self, document_id: int) -> dict:
        row = self.repo.get_admin(document_id)
        if row is None:
            raise OnboardingDocumentNotFoundError()
        return _admin_view(row)

    def get_admin_content(self, document_id: int) -> DocumentContent:
        row = self.repo.get_admin_content(document_id)
        if row is None:
            raise OnboardingDocumentNotFoundError()
        return _content_view(row)

    # ---------------------------------------------------------------- create
    def create(
        self,
        actor: Korisnik,
        naziv: str | None,
        opis: str | None,
        redosled: int | None,
        pdf: ValidatedPdf,
    ) -> dict:
        metadata = validate_metadata(naziv, opis, redosled)
        try:
            now = self._now_fn()
            dok = OnboardingDokument(
                naziv=metadata.naziv,
                opis=metadata.opis,
                originalni_naziv_fajla=pdf.original_name,
                mime_tip=ONB_DOKUMENT_MIME_PDF,
                velicina_bajtova=pdf.size,
                sha256=pdf.sha256,
                sadrzaj=pdf.content,
                status=ONB_DOKUMENT_STATUS_DRAFT,
                redosled=metadata.redosled,
                verzija=1,
                kreirao_platni_broj=actor.platni_broj,
                izmenio_platni_broj=actor.platni_broj,
                datum_kreiranja=now,
                datum_izmene=now,
                datum_objave=None,
            )
            self.repo.add(dok)
            self.db.flush()  # dobija ID pre sastavljanja odgovora i audita
            self._audit(actor, AuditAction.ADMIN_ONBOARDING_DOCUMENT_CREATED, dok, "CREATED")
            view = _admin_view(dok)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # ---------------------------------------------------------------- update
    def update(
        self,
        actor: Korisnik,
        document_id: int,
        naziv: str | None,
        opis: str | None,
        redosled: int | None,
    ) -> dict:
        metadata = validate_metadata(naziv, opis, redosled)
        try:
            dok = self._locked(document_id)
            if dok.status == ONB_DOKUMENT_STATUS_ARCHIVED:
                raise OnboardingDocumentArchivedError()

            unchanged = (
                dok.naziv == metadata.naziv
                and (_opt_text(dok.opis) or None) == metadata.opis
                and int(dok.redosled) == metadata.redosled
            )
            if not unchanged:
                dok.naziv = metadata.naziv
                dok.opis = metadata.opis
                dok.redosled = metadata.redosled
                dok.izmenio_platni_broj = actor.platni_broj
                dok.datum_izmene = self._now_fn()
                self.db.flush()
                self._audit(actor, AuditAction.ADMIN_ONBOARDING_DOCUMENT_UPDATED, dok, "UPDATED")
            view = _admin_view(dok)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # --------------------------------------------------------------- content
    def replace_content(self, actor: Korisnik, document_id: int, pdf: ValidatedPdf) -> dict:
        try:
            dok = self._locked(document_id)
            if dok.status == ONB_DOKUMENT_STATUS_ARCHIVED:
                raise OnboardingDocumentArchivedError()
            if dok.status != ONB_DOKUMENT_STATUS_DRAFT:
                raise OnboardingDocumentNotDraftError()

            # Potpuno isti sadrzaj: bez nove verzije i bez audita (hash se poredi, BLOB
            # se ne ucitava).
            if dok.sha256 == pdf.sha256:
                view = _admin_view(dok)
                self.db.commit()
                return view

            dok.originalni_naziv_fajla = pdf.original_name
            dok.mime_tip = ONB_DOKUMENT_MIME_PDF
            dok.velicina_bajtova = pdf.size
            dok.sha256 = pdf.sha256
            dok.sadrzaj = pdf.content
            dok.verzija = int(dok.verzija) + 1
            dok.izmenio_platni_broj = actor.platni_broj
            dok.datum_izmene = self._now_fn()
            self.db.flush()
            self._audit(
                actor, AuditAction.ADMIN_ONBOARDING_DOCUMENT_CONTENT_REPLACED, dok, "CONTENT_REPLACED"
            )
            view = _admin_view(dok)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # ---------------------------------------------------------------- status
    def change_status(self, actor: Korisnik, document_id: int, novi_status: str | None) -> dict:
        target = normalize_status(novi_status)
        try:
            dok = self._locked(document_id)
            current = dok.status

            # Identicna promena je idempotentna (ukljucujuci ARCHIVED -> ARCHIVED).
            if current == target:
                view = _admin_view(dok)
                self.db.commit()
                return view
            if current == ONB_DOKUMENT_STATUS_ARCHIVED:
                raise OnboardingDocumentArchivedError()
            if not is_valid_onboarding_document_transition(current, target):
                # Nijedan neidempotentan prelaz van tabele prelaza nije moguc (svi su
                # pokriveni), ali ostaje kao zastita ako se tabela prelaza promeni.
                raise InvalidOnboardingDocumentStatusError("Nedozvoljena promena statusa dokumenta.")

            now = self._now_fn()
            dok.status = target
            if target == ONB_DOKUMENT_STATUS_PUBLISHED:
                dok.datum_objave = now
            elif target == ONB_DOKUMENT_STATUS_DRAFT:
                dok.datum_objave = None
            # ARCHIVED zadrzava datum objave (istorija); iz DRAFT-a ostaje NULL.
            dok.izmenio_platni_broj = actor.platni_broj
            dok.datum_izmene = now
            self.db.flush()

            action, label = _STATUS_AUDIT[(current, target)]
            self._audit(actor, action, dok, label)
            view = _admin_view(dok)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # --------------------------------------------------------------- helpers
    def _locked(self, document_id: int) -> OnboardingDokument:
        dok = self.repo.get_for_update(document_id)
        if dok is None:
            raise OnboardingDocumentNotFoundError()
        return dok

    def _audit(self, actor: Korisnik, sifra_akcije: str, dok: OnboardingDokument, label: str) -> None:
        # DETALJI: samo id/status/verzija/naziv akcije. Nikad PDF sadrzaj, bajtovi ni SHA-256.
        self.audit_service.log(
            sifra_akcije,
            korisnik_id=actor.id,
            platni_broj=actor.platni_broj,
            tip_entiteta=ENTITY_TYPE,
            entitet_id=str(int(dok.id)),
            detalji=(
                f"document_id={int(dok.id)}; status={dok.status}; "
                f"verzija={int(dok.verzija)}; akcija={label}"
            ),
        )


_STATUS_AUDIT: dict[tuple[str, str], tuple[str, str]] = {
    (ONB_DOKUMENT_STATUS_DRAFT, ONB_DOKUMENT_STATUS_PUBLISHED): (
        AuditAction.ADMIN_ONBOARDING_DOCUMENT_PUBLISHED,
        "PUBLISHED",
    ),
    (ONB_DOKUMENT_STATUS_PUBLISHED, ONB_DOKUMENT_STATUS_DRAFT): (
        AuditAction.ADMIN_ONBOARDING_DOCUMENT_UNPUBLISHED,
        "UNPUBLISHED",
    ),
    (ONB_DOKUMENT_STATUS_DRAFT, ONB_DOKUMENT_STATUS_ARCHIVED): (
        AuditAction.ADMIN_ONBOARDING_DOCUMENT_ARCHIVED,
        "ARCHIVED",
    ),
    (ONB_DOKUMENT_STATUS_PUBLISHED, ONB_DOKUMENT_STATUS_ARCHIVED): (
        AuditAction.ADMIN_ONBOARDING_DOCUMENT_ARCHIVED,
        "ARCHIVED",
    ),
}

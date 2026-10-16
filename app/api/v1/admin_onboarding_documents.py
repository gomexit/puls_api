from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.routing import APIRoute
from pydantic import BeforeValidator, Field
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.onboarding_documents import PDF_RESPONSES, pdf_inline_response
from app.core.exceptions import ValidationBusinessError
from app.core.sorting import SortSpec, sort_params
from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.models.onboarding_dokument import ONB_DOKUMENT_STATUSI
from app.repositories.onboarding_document_repository import (
    ADMIN_DEFAULT_SORT,
    ADMIN_SORT_COLUMNS,
)
from app.schemas.common import ErrorResponse
from app.schemas.onboarding_document import (
    STATUS_DESCRIPTION,
    STATUS_TRANSITIONS_MD,
    AdminOnboardingDocumentListResponse,
    AdminOnboardingDocumentOut,
    AdminOnboardingDocumentStatusRequest,
    AdminOnboardingDocumentUpdateRequest,
)
from app.services.onboarding_document_service import OnboardingDocumentService
from app.services.onboarding_pdf import (
    NAZIV_MAX,
    OPIS_MAX,
    REDOSLED_MAX,
    REDOSLED_MIN,
    strip_text,
    strip_text_or_none,
)


class MultipartValidationRoute(APIRoute):
    """Pokvaren multipart body (los boundary, prekinut upload...) FastAPI/Starlette vraca kao
    HTTP 400 {"detail": ...}. Ovde ga svodimo na standardni VALIDATION_ERROR (422) format
    projekta. Vazi samo za rute ovog routera; globalni handler-i se ne menjaju."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except StarletteHTTPException as exc:
                content_type = request.headers.get("content-type", "").lower()
                if exc.status_code == 400 and content_type.startswith("multipart/"):
                    raise ValidationBusinessError("Neispravan multipart zahtev.") from exc
                raise

        return handler


router = APIRouter(
    prefix="/admin/onboarding-documents",
    tags=["Admin Onboarding Documents"],
    route_class=MultipartValidationRoute,
)

R_404 = {404: {"model": ErrorResponse, "description": "`ONBOARDING_DOCUMENT_NOT_FOUND` - dokument ne postoji."}}
R_422 = {422: {"model": ErrorResponse, "description": "`VALIDATION_ERROR` ili `INVALID_PDF_DOCUMENT` - neispravni podaci ili PDF."}}
R_413 = {413: {"model": ErrorResponse, "description": "`PDF_DOCUMENT_TOO_LARGE` - PDF je veci od `ONBOARDING_PDF_MAX_SIZE_MB`."}}
R_409_ARCHIVED = {409: {"model": ErrorResponse, "description": "`ONBOARDING_DOCUMENT_ARCHIVED` - arhiviran dokument se ne menja."}}

PAGE_SIZE_DEFAULT = 20

# Sortiranje po jednoj koloni (?sort_by=&sort_dir=). Bez parametara: redosled, pa id.
list_sort = sort_params(
    allowed=list(ADMIN_SORT_COLUMNS),
    default_by=ADMIN_DEFAULT_SORT.by,
    default_dir=ADMIN_DEFAULT_SORT.dir,
)
PAGE_SIZE_MAX = 100


def get_onboarding_document_service(db: Session = Depends(get_db)) -> OnboardingDocumentService:
    return OnboardingDocumentService(db)


@router.get(
    "",
    response_model=AdminOnboardingDocumentListResponse,
    summary="Lista onboarding dokumenata (svi statusi)",
    description=(
        "Admin/HR vidi dokumente u **svim** statusima (DRAFT, PUBLISHED, ARCHIVED). "
        "Paginacija: `page`, `page_size`. Sortiranje po jednoj koloni: `sort_by` + `sort_dir` "
        "(podrazumevano `redosled` rastuce, pa `id`); odgovor vraca stvarno primenjeni "
        "`sort_by`/`sort_dir`. Filter `status` je opcion; `search` trazi po nazivu.\n\n"
        + STATUS_DESCRIPTION
    ),
)
def list_documents(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter po statusu: DRAFT, PUBLISHED ili ARCHIVED. Bez filtera vraca sve. "
        "Nepoznata vrednost: 422 `INVALID_ONBOARDING_DOCUMENT_STATUS`.",
        json_schema_extra={"enum": list(ONB_DOKUMENT_STATUSI)},
    ),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    sort: SortSpec = Depends(list_sort),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> AdminOnboardingDocumentListResponse:
    result = service.list_admin(status_filter, search, page, page_size, sort)
    return AdminOnboardingDocumentListResponse(
        items=[AdminOnboardingDocumentOut(**it) for it in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        sort_by=result["sort_by"],
        sort_dir=result["sort_dir"],
    )


@router.get(
    "/{document_id}",
    response_model=AdminOnboardingDocumentOut,
    summary="Detalj dokumenta (bilo koji status)",
    responses={**R_404},
)
def get_document(
    document_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> AdminOnboardingDocumentOut:
    return AdminOnboardingDocumentOut(**service.get_admin(document_id))


@router.post(
    "",
    response_model=AdminOnboardingDocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Kreiranje dokumenta (uvek DRAFT)",
    description=(
        "Novi dokument uvek nastaje u statusu **DRAFT**, verzija 1, i zaposleni ga ne vide "
        "dok se ne objavi (`PATCH .../status` -> `PUBLISHED`). Telo je `multipart/form-data`: "
        "`naziv` (1-200), `opis` (opciono, do 4000), `redosled` (1-9999999999, default 1) i "
        "`file` (PDF, do `ONBOARDING_PDF_MAX_SIZE_MB`). Akter se uzima iz OBO zaglavlja."
    ),
    responses={**R_422, **R_413},
)
def create_document(
    naziv: Annotated[
        str, BeforeValidator(strip_text), Form(min_length=1, max_length=NAZIV_MAX)
    ],
    opis: Annotated[
        Annotated[str, Field(max_length=OPIS_MAX)] | None,
        BeforeValidator(strip_text_or_none),
        Form(),
    ] = None,
    redosled: Annotated[int, Form(ge=REDOSLED_MIN, le=REDOSLED_MAX)] = 1,
    file: UploadFile = File(...),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> AdminOnboardingDocumentOut:
    pdf = service.parse_upload(file.file, file.filename, file.content_type)
    return AdminOnboardingDocumentOut(**service.create(actor, naziv, opis, redosled, pdf))


@router.put(
    "/{document_id}",
    response_model=AdminOnboardingDocumentOut,
    summary="Izmena naziva, opisa i redosleda",
    description=(
        "Menja samo metadata (naziv, opis, redosled). Dozvoljeno u **DRAFT** i **PUBLISHED** "
        "statusu; za **ARCHIVED** vraca 409. Ne menja status ni verziju. "
        "Identicna izmena je no-op (bez audita)."
    ),
    responses={**R_404, **R_409_ARCHIVED, **R_422},
)
def update_document(
    document_id: int,
    payload: AdminOnboardingDocumentUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> AdminOnboardingDocumentOut:
    return AdminOnboardingDocumentOut(
        **service.update(actor, document_id, payload.naziv, payload.opis, payload.redosled)
    )


@router.put(
    "/{document_id}/content",
    response_model=AdminOnboardingDocumentOut,
    summary="Zamena PDF sadrzaja (samo DRAFT)",
    description=(
        "Menja PDF **samo dok je dokument u DRAFT-u**. Za PUBLISHED vraca 409 "
        "`ONBOARDING_DOCUMENT_NOT_DRAFT` (prvo povuci iz objave: `PATCH .../status` -> `DRAFT`), "
        "a za ARCHIVED 409 `ONBOARDING_DOCUMENT_ARCHIVED`. Svaka zamena povecava `verzija` za 1; "
        "slanje potpuno istog PDF-a (isti SHA-256) je no-op: verzija ostaje ista i nema audita."
    ),
    responses={
        **R_404,
        **R_422,
        **R_413,
        409: {
            "model": ErrorResponse,
            "description": "`ONBOARDING_DOCUMENT_NOT_DRAFT` (PUBLISHED) ili "
            "`ONBOARDING_DOCUMENT_ARCHIVED` (ARCHIVED).",
        },
    },
)
def replace_document_content(
    document_id: int,
    file: UploadFile = File(...),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> AdminOnboardingDocumentOut:
    pdf = service.parse_upload(file.file, file.filename, file.content_type)
    return AdminOnboardingDocumentOut(**service.replace_content(actor, document_id, pdf))


@router.patch(
    "/{document_id}/status",
    response_model=AdminOnboardingDocumentOut,
    summary="Promena statusa (objava, povlacenje, arhiviranje)",
    description=STATUS_DESCRIPTION + "\n\n" + STATUS_TRANSITIONS_MD,
    responses={
        **R_404,
        **R_409_ARCHIVED,
        422: {
            "model": ErrorResponse,
            "description": "`INVALID_ONBOARDING_DOCUMENT_STATUS` - nepoznat status.",
        },
    },
)
def change_document_status(
    document_id: int,
    payload: AdminOnboardingDocumentStatusRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> AdminOnboardingDocumentOut:
    return AdminOnboardingDocumentOut(**service.change_status(actor, document_id, payload.status))


@router.get(
    "/{document_id}/content",
    response_class=Response,
    summary="Pregled PDF-a (bilo koji status)",
    description=(
        "Vraca binarni PDF (`application/pdf`, inline). Admin/HR moze da pregleda PDF u "
        "bilo kom statusu, ukljucujuci DRAFT i ARCHIVED."
    ),
    responses={**PDF_RESPONSES, **R_404},
)
def get_document_content(
    document_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> Response:
    return pdf_inline_response(service.get_admin_content(document_id))

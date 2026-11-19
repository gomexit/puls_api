from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from pydantic import BeforeValidator
from sqlalchemy.orm import Session

from app.api.v1.admin_onboarding_documents import MultipartValidationRoute
from app.api.v1.images import IMAGE_RESPONSES, image_response
from app.core.sorting import SortSpec, sort_params
from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.models.slika import SLIKA_STATUSI
from app.repositories.image_repository import ADMIN_DEFAULT_SORT, ADMIN_SORT_COLUMNS
from app.schemas.common import ErrorResponse
from app.schemas.image import (
    STATUS_DESCRIPTION,
    AdminImageListResponse,
    AdminImageOut,
    AdminImageStatusRequest,
    AdminImageUpdateRequest,
)
from app.services.image_processing import NAZIV_MAX
from app.services.image_service import ImageService
from app.services.onboarding_pdf import strip_text

router = APIRouter(
    prefix="/admin/images",
    tags=["Admin Images"],
    route_class=MultipartValidationRoute,
)

R_404 = {404: {"model": ErrorResponse, "description": "`IMAGE_NOT_FOUND` - slika ne postoji."}}
R_422 = {422: {"model": ErrorResponse, "description": "`VALIDATION_ERROR` ili `INVALID_IMAGE` - neispravni podaci ili slika."}}
R_413 = {413: {"model": ErrorResponse, "description": "`IMAGE_TOO_LARGE` - fajl je veći od `IMAGE_MAX_SIZE_MB` (5 MB)."}}
R_409 = {409: {"model": ErrorResponse, "description": "`IMAGE_ARCHIVED` - arhivirana slika se ne menja."}}

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100

list_sort = sort_params(
    allowed=list(ADMIN_SORT_COLUMNS),
    default_by=ADMIN_DEFAULT_SORT.by,
    default_dir=ADMIN_DEFAULT_SORT.dir,
)


def get_image_service(db: Session = Depends(get_db)) -> ImageService:
    return ImageService(db)


@router.get(
    "",
    response_model=AdminImageListResponse,
    summary="Lista slika (svi statusi)",
    description=(
        "Paginacija: `page`, `page_size`. Sortiranje: `sort_by` + `sort_dir` (podrazumevano "
        "`datum_kreiranja` opadajuće). Filter `status` je opcion; `search` traži po nazivu.\n\n"
        + STATUS_DESCRIPTION
    ),
)
def list_images(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="AKTIVNA ili ARHIVIRANA. Nepoznata vrednost: 422 `INVALID_IMAGE_STATUS`.",
        json_schema_extra={"enum": list(SLIKA_STATUSI)},
    ),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    sort: SortSpec = Depends(list_sort),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: ImageService = Depends(get_image_service),
) -> AdminImageListResponse:
    result = service.list_admin(status_filter, search, page, page_size, sort)
    return AdminImageListResponse(
        items=[AdminImageOut(**it) for it in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        sort_by=result["sort_by"],
        sort_dir=result["sort_dir"],
    )


@router.get("/{image_id}", response_model=AdminImageOut, summary="Detalj slike", responses={**R_404})
def get_image(
    image_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: ImageService = Depends(get_image_service),
) -> AdminImageOut:
    return AdminImageOut(**service.get_admin(image_id))


@router.get(
    "/{image_id}/content",
    response_class=Response,
    summary="Sadržaj slike (bilo koji status)",
    description="Binarna slika za pregled u portalu, i kad je arhivirana. `Cache-Control: private, no-store`.",
    responses={200: IMAGE_RESPONSES[200], **R_404},
)
def get_image_content(
    image_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: ImageService = Depends(get_image_service),
) -> Response:
    return image_response(service.get_admin_content(image_id), "private, no-store")


@router.post(
    "",
    response_model=AdminImageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload slike",
    description=(
        "Telo je `multipart/form-data`: `naziv` (1-200) i `file` (JPEG ili PNG, do 5 MB). "
        "Backend proverava sadržaj (ne veruje ekstenziji ni MIME-u), okreće sliku po EXIF "
        "orijentaciji, smanjuje je na najviše 1200 px po dužoj strani i uklanja metapodatke "
        "(EXIF, GPS). Odgovor sadrži stvarne dimenzije i veličinu sačuvane slike i `url` za "
        "aplikaciju. Nova slika je odmah **AKTIVNA**. Akter se uzima iz OBO zaglavlja."
    ),
    responses={**R_422, **R_413},
)
def upload_image(
    naziv: Annotated[str, BeforeValidator(strip_text), Form(min_length=1, max_length=NAZIV_MAX)],
    file: UploadFile = File(...),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: ImageService = Depends(get_image_service),
) -> AdminImageOut:
    image = service.parse_upload(file.file, file.filename, file.content_type)
    return AdminImageOut(**service.create(actor, naziv, image))


@router.put(
    "/{image_id}",
    response_model=AdminImageOut,
    summary="Izmena naziva slike",
    description="Menja samo naziv. Sadržaj slike se ne menja nikad (za novu sliku uradi novi upload). "
    "Identična izmena je no-op (bez audita).",
    responses={**R_404, **R_409, **R_422},
)
def rename_image(
    image_id: int,
    payload: AdminImageUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: ImageService = Depends(get_image_service),
) -> AdminImageOut:
    return AdminImageOut(**service.rename(actor, image_id, payload.naziv))


@router.patch(
    "/{image_id}/status",
    response_model=AdminImageOut,
    summary="Arhiviranje slike",
    description=STATUS_DESCRIPTION
    + "\n\nJedini prelaz je AKTIVNA -> ARHIVIRANA. Ista vrednost kao trenutna je idempotentna "
    "(200, bez audita). ARHIVIRANA -> AKTIVNA: 409 `IMAGE_ARCHIVED`.",
    responses={**R_404, **R_409, **R_422},
)
def change_image_status(
    image_id: int,
    payload: AdminImageStatusRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: ImageService = Depends(get_image_service),
) -> AdminImageOut:
    return AdminImageOut(**service.change_status(actor, image_id, payload.status))

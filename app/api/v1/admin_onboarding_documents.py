from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.routing import APIRoute
from pydantic import BeforeValidator, Field
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.onboarding_documents import PDF_RESPONSES, pdf_inline_response
from app.core.exceptions import ValidationBusinessError
from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.schemas.onboarding_document import (
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

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


def get_onboarding_document_service(db: Session = Depends(get_db)) -> OnboardingDocumentService:
    return OnboardingDocumentService(db)


@router.get("", response_model=AdminOnboardingDocumentListResponse)
def list_documents(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> AdminOnboardingDocumentListResponse:
    result = service.list_admin(status_filter, search, page, page_size)
    return AdminOnboardingDocumentListResponse(
        items=[AdminOnboardingDocumentOut(**it) for it in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/{document_id}", response_model=AdminOnboardingDocumentOut)
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


@router.put("/{document_id}", response_model=AdminOnboardingDocumentOut)
def update_document(
    document_id: int,
    payload: AdminOnboardingDocumentUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> AdminOnboardingDocumentOut:
    return AdminOnboardingDocumentOut(
        **service.update(actor, document_id, payload.naziv, payload.opis, payload.redosled)
    )


@router.put("/{document_id}/content", response_model=AdminOnboardingDocumentOut)
def replace_document_content(
    document_id: int,
    file: UploadFile = File(...),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> AdminOnboardingDocumentOut:
    pdf = service.parse_upload(file.file, file.filename, file.content_type)
    return AdminOnboardingDocumentOut(**service.replace_content(actor, document_id, pdf))


@router.patch("/{document_id}/status", response_model=AdminOnboardingDocumentOut)
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
    responses=PDF_RESPONSES,
)
def get_document_content(
    document_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> Response:
    return pdf_inline_response(service.get_admin_content(document_id))

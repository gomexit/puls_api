from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.schemas.onboarding_document import (
    OnboardingDocumentListResponse,
    OnboardingDocumentOut,
)
from app.services.onboarding_document_service import DocumentContent, OnboardingDocumentService
from app.services.onboarding_pdf import content_disposition_inline

router = APIRouter(prefix="/onboarding/documents", tags=["Onboarding Documents"])

PDF_RESPONSES = {
    200: {
        "description": "PDF dokument (inline).",
        "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
    }
}


def get_onboarding_document_service(db: Session = Depends(get_db)) -> OnboardingDocumentService:
    return OnboardingDocumentService(db)


def pdf_inline_response(doc: DocumentContent) -> Response:
    """Binarni PDF sa bezbednim headerima. Cache-Control: private, no-store jer je sadrzaj
    iza autentikacije; nosniff sprecava da browser 'pogodi' drugaciji tip sadrzaja."""
    return Response(
        content=doc.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition_inline(doc.filename),
            "Content-Length": str(len(doc.content)),
            "ETag": f'"{doc.sha256}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("", response_model=OnboardingDocumentListResponse)
def list_documents(
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> OnboardingDocumentListResponse:
    return OnboardingDocumentListResponse(
        items=[OnboardingDocumentOut(**it) for it in service.list_published()]
    )


@router.get("/{document_id}", response_model=OnboardingDocumentOut)
def get_document(
    document_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> OnboardingDocumentOut:
    return OnboardingDocumentOut(**service.get_published(document_id))


@router.get(
    "/{document_id}/content",
    response_class=Response,
    responses=PDF_RESPONSES,
)
def get_document_content(
    document_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: OnboardingDocumentService = Depends(get_onboarding_document_service),
) -> Response:
    return pdf_inline_response(service.get_published_content(document_id))

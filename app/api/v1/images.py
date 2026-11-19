from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.schemas.common import ErrorResponse
from app.services.image_service import ImageContent, ImageService

router = APIRouter(prefix="/images", tags=["Images"])

# Slika je nepromenljiva (nova slika = novi ID), pa aplikacija sme da je kesira lokalno.
# "private": samo uredjaj korisnika, nikad deljeni proxy - sadrzaj je iza prijave.
CACHE_CONTROL = "private, max-age=86400"

NOT_FOUND_RESPONSE = {
    404: {
        "model": ErrorResponse,
        "description": "`IMAGE_NOT_FOUND` - slika ne postoji ili je arhivirana (odgovor je isti).",
    }
}

IMAGE_RESPONSES = {
    200: {
        "description": "Slika (JPEG ili PNG, najviše 1200 px po dužoj strani).",
        "content": {
            "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
            "image/png": {"schema": {"type": "string", "format": "binary"}},
        },
    },
    304: {"description": "Slika nije promenjena (`If-None-Match` odgovara `ETag`-u)."},
}


def get_image_service(db: Session = Depends(get_db)) -> ImageService:
    return ImageService(db)


def _etag(sha256: str) -> str:
    return f'"{sha256}"'


def image_response(image: ImageContent, cache_control: str) -> Response:
    return Response(
        content=image.content,
        media_type=image.mime_type,
        headers={
            "Content-Length": str(len(image.content)),
            "ETag": _etag(image.sha256),
            "Cache-Control": cache_control,
            "X-Content-Type-Options": "nosniff",
        },
    )


def _if_none_match_hits(request: Request, sha256: str) -> bool:
    header = request.headers.get("if-none-match")
    if not header:
        return False
    tags = {part.strip().removeprefix("W/") for part in header.split(",")}
    return "*" in tags or _etag(sha256) in tags


@router.get(
    "/{image_id}",
    response_class=Response,
    summary="Prikaz aktivne slike",
    description=(
        "Binarna slika za prikaz u aplikaciji (logo partnera, slika pitanja...). Zahteva "
        "prijavu. `ETag` je SHA-256 sadržaja; uz `If-None-Match` sa istom vrednošću "
        "odgovor je **304** bez sadržaja. `Cache-Control: private, max-age=86400`. "
        "Arhivirana ili nepostojeća slika: 404."
    ),
    responses={**IMAGE_RESPONSES, **NOT_FOUND_RESPONSE},
)
def get_image(
    image_id: int,
    request: Request,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: ImageService = Depends(get_image_service),
) -> Response:
    if request.headers.get("if-none-match"):
        sha = service.get_active_etag(image_id)
        if _if_none_match_hits(request, sha):
            return Response(
                status_code=304,
                headers={"ETag": _etag(sha), "Cache-Control": CACHE_CONTROL},
            )
    return image_response(service.get_active_content(image_id), CACHE_CONTROL)

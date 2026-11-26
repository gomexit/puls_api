from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.schemas.common import ErrorResponse
from app.schemas.quiz import (
    QuizAnswerRequest,
    QuizAnswerResponse,
    QuizCurrentResponse,
    QuizPlayResponse,
    QuizResultResponse,
)
from app.services.quiz_service import QuizService

router = APIRouter(prefix="/quizzes", tags=["Puls izazov"])
attempts_router = APIRouter(prefix="/quiz-attempts", tags=["Puls izazov"])

R_QUIZ_404 = {404: {"model": ErrorResponse, "description": "`QUIZ_NOT_FOUND` - kviz ne postoji ili nije za mene."}}
R_ATTEMPT_404 = {404: {"model": ErrorResponse, "description": "`QUIZ_ATTEMPT_NOT_FOUND`."}}


def get_quiz_service(db: Session = Depends(get_db)) -> QuizService:
    return QuizService(db)


@router.get(
    "/current",
    response_model=QuizCurrentResponse,
    summary="Trenutni Puls izazov",
    description="Aktivan kviz za mene (`kviz=null` ako ga nema ili modul nije uključen) i stanje "
    "mog pokušaja (`pokusaj=null` ako nisam počeo).",
)
def current_quiz(
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: QuizService = Depends(get_quiz_service),
) -> QuizCurrentResponse:
    return QuizCurrentResponse(**service.current(korisnik))


@router.post(
    "/{kviz_id}/start",
    response_model=QuizPlayResponse,
    summary="Početak (ili nastavak) kviza",
    description="Prvi poziv pokreće serverski sat (`rok`). Ponovni poziv dok traje vraća isti pokušaj "
    "sa već datim odgovorima. Pitanja nikad ne sadrže tačan odgovor. Već odigran kviz: 409 "
    "`QUIZ_ALREADY_PLAYED`.",
    responses={**R_QUIZ_404, 409: {"model": ErrorResponse, "description": "`QUIZ_ALREADY_PLAYED`."}},
)
def start_quiz(
    kviz_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: QuizService = Depends(get_quiz_service),
) -> QuizPlayResponse:
    return QuizPlayResponse(**service.start(korisnik, kviz_id))


@attempts_router.post(
    "/{pokusaj_id}/answers",
    response_model=QuizAnswerResponse,
    summary="Odgovor na pitanje",
    description="Vraća da li je odgovor tačan, tačan odgovor i objašnjenje. Odgovor se ne menja. "
    "Posle poslednjeg pitanja pokušaj je završen (`zavrsen=true`).",
    responses={
        **R_ATTEMPT_404,
        409: {
            "model": ErrorResponse,
            "description": "`QUIZ_TIME_EXPIRED`, `QUIZ_ATTEMPT_FINISHED` ili `QUIZ_QUESTION_ALREADY_ANSWERED`.",
        },
        422: {"model": ErrorResponse, "description": "`INVALID_QUIZ_ANSWER`."},
    },
)
def answer_question(
    pokusaj_id: int,
    payload: QuizAnswerRequest,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: QuizService = Depends(get_quiz_service),
) -> QuizAnswerResponse:
    return QuizAnswerResponse(**service.answer(korisnik, pokusaj_id, payload.pitanje_id, payload.opcija_id))


@attempts_router.post(
    "/{pokusaj_id}/finish",
    response_model=QuizResultResponse,
    summary="Završetak kviza",
    description="Završava pokušaj (neodgovorena pitanja su netačna) i vraća rezultat. Idempotentno.",
    responses={**R_ATTEMPT_404},
)
def finish_attempt(
    pokusaj_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: QuizService = Depends(get_quiz_service),
) -> QuizResultResponse:
    return QuizResultResponse(**service.finish(korisnik, pokusaj_id))


@attempts_router.get(
    "/{pokusaj_id}/result",
    response_model=QuizResultResponse,
    summary="Rezultat kviza",
    description="Broj tačnih, vreme, prosek moje org. jedinice (od 3 učesnika) i pregled pitanja. "
    "Dok kviz traje: 409 `QUIZ_ATTEMPT_IN_PROGRESS`.",
    responses={**R_ATTEMPT_404, 409: {"model": ErrorResponse, "description": "`QUIZ_ATTEMPT_IN_PROGRESS`."}},
)
def attempt_result(
    pokusaj_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: QuizService = Depends(get_quiz_service),
) -> QuizResultResponse:
    return QuizResultResponse(**service.result(korisnik, pokusaj_id))

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class PulsApiError(Exception):
    """Base exception for business-rule failures that map to a JSON error response."""

    code = "INTERNAL_ERROR"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Došlo je do greške."

    def __init__(self, message: str | None = None):
        self.message = message or self.message
        super().__init__(self.message)


class InvalidCredentialsError(PulsApiError):
    code = "INVALID_CREDENTIALS"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Pogrešan platni broj ili lozinka."


class AccountInactiveError(PulsApiError):
    code = "ACCOUNT_INACTIVE"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Nalog nije aktivan."


class AccountDisabledError(PulsApiError):
    code = "ACCOUNT_DISABLED"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Nalog je onemogućen."


class AccountLockedError(PulsApiError):
    code = "ACCOUNT_LOCKED"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Nalog je zaključan zbog previše neuspešnih pokušaja prijave."


class PasswordChangeRequiredError(PulsApiError):
    code = "PASSWORD_CHANGE_REQUIRED"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Neophodna je promena lozinke."


class PhoneConfirmationRequiredError(PulsApiError):
    code = "PHONE_CONFIRMATION_REQUIRED"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Neophodna je potvrda broja telefona."


class InvalidSessionError(PulsApiError):
    code = "INVALID_SESSION"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Nevažeća sesija."


class SessionExpiredError(PulsApiError):
    code = "SESSION_EXPIRED"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Sesija je istekla."


class InvalidResetCodeError(PulsApiError):
    code = "INVALID_RESET_CODE"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Neispravan kod za reset lozinke."


class ResetCodeExpiredError(PulsApiError):
    code = "RESET_CODE_EXPIRED"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Kod za reset lozinke je istekao."


class ValidationBusinessError(PulsApiError):
    code = "VALIDATION_ERROR"
    status_code = 422
    message = "Neispravni podaci."


class ForbiddenError(PulsApiError):
    code = "FORBIDDEN"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Nemate pravo pristupa."


class InvalidServiceCredentialsError(PulsApiError):
    # Namerno generička poruka: ne otkriva da li servisni ključ nedostaje,
    # je pogrešan ili nije konfigurisan. Sam ključ se nikada ne loguje ni vraća.
    code = "INVALID_SERVICE_CREDENTIALS"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Nevažeći servisni kredencijali."


# --- Modul IDEJE ---
class NoActiveIdeaCycleError(PulsApiError):
    code = "NO_ACTIVE_IDEA_CYCLE"
    status_code = status.HTTP_409_CONFLICT
    message = "Trenutno ne postoji aktivan ciklus za ideje."


class IdeaLimitReachedError(PulsApiError):
    code = "IDEA_LIMIT_REACHED"
    status_code = status.HTTP_409_CONFLICT
    message = "Dostigli ste maksimalan broj ideja za ovaj ciklus."


class IdeaNotFoundError(PulsApiError):
    code = "IDEA_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Ideja nije pronađena."


class IdeaEditNotAllowedError(PulsApiError):
    code = "IDEA_EDIT_NOT_ALLOWED"
    status_code = status.HTTP_409_CONFLICT
    message = "Izmena ove ideje trenutno nije dozvoljena."


class InvalidIdeaStatusTransitionError(PulsApiError):
    code = "INVALID_IDEA_STATUS_TRANSITION"
    status_code = status.HTTP_409_CONFLICT
    message = "Nedozvoljena promena statusa ideje."


class IdeaCycleNotFoundError(PulsApiError):
    code = "IDEA_CYCLE_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Ciklus ideja nije pronađen."


class InvalidIdeaCycleTransitionError(PulsApiError):
    code = "INVALID_IDEA_CYCLE_TRANSITION"
    status_code = status.HTTP_409_CONFLICT
    message = "Nedozvoljena promena statusa ciklusa."


class ActiveIdeaCycleAlreadyExistsError(PulsApiError):
    code = "ACTIVE_IDEA_CYCLE_ALREADY_EXISTS"
    status_code = status.HTTP_409_CONFLICT
    message = "Već postoji aktivan ciklus ideja."


# --- Modul ANKETE (employee) ---
class SurveyNotFoundError(PulsApiError):
    code = "SURVEY_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Anketa nije pronađena ili više nije dostupna."


class SurveyNotTargetedError(PulsApiError):
    code = "SURVEY_NOT_TARGETED"
    status_code = status.HTTP_403_FORBIDDEN
    message = "Ova anketa nije namenjena vama."


class SurveyNotActiveError(PulsApiError):
    code = "SURVEY_NOT_ACTIVE"
    status_code = status.HTTP_409_CONFLICT
    message = "Anketa više nije aktivna."


class SurveyAlreadySubmittedError(PulsApiError):
    code = "SURVEY_ALREADY_SUBMITTED"
    status_code = status.HTTP_409_CONFLICT
    message = "Već ste predali odgovore na ovu anketu."


# --- Modul ANKETE (admin) ---
class SurveyStructureLockedError(PulsApiError):
    code = "SURVEY_STRUCTURE_LOCKED"
    status_code = status.HTTP_409_CONFLICT
    message = "Struktura ankete više ne može da se menja."


class InvalidSurveyStatusTransitionError(PulsApiError):
    code = "INVALID_SURVEY_STATUS_TRANSITION"
    status_code = status.HTTP_409_CONFLICT
    message = "Nedozvoljena promena statusa ankete."


class SurveyTypeNotFoundError(PulsApiError):
    code = "SURVEY_TYPE_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Tip ankete nije pronađen."


class AnonymousSurveyResponsesNotAvailableError(PulsApiError):
    code = "ANONYMOUS_SURVEY_RESPONSES_NOT_AVAILABLE"
    status_code = status.HTTP_409_CONFLICT
    message = "Pojedinačni odgovori nisu dostupni za anonimnu anketu."


# --- Modul OBAVESTENJA ---
class NotificationNotFoundError(PulsApiError):
    # Generička poruka: isti odgovor za nepostojeće, tuđe, neobjavljeno, buduće,
    # isteklo i arhivirano obaveštenje - ne otkriva postojanje tuđeg obaveštenja.
    code = "NOTIFICATION_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Obaveštenje nije pronađeno ili više nije dostupno."


class InvalidNotificationStatusTransitionError(PulsApiError):
    code = "INVALID_NOTIFICATION_STATUS_TRANSITION"
    status_code = status.HTTP_409_CONFLICT
    message = "Nedozvoljena promena statusa obaveštenja."


class NotificationEditNotAllowedError(PulsApiError):
    code = "NOTIFICATION_EDIT_NOT_ALLOWED"
    status_code = status.HTTP_409_CONFLICT
    message = "Izmena obaveštenja je dozvoljena samo dok je u statusu DRAFT."


class NotificationCategoryNotFoundError(PulsApiError):
    code = "NOTIFICATION_CATEGORY_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Kategorija obaveštenja nije pronađena."


class NotificationCategoryAlreadyExistsError(PulsApiError):
    code = "NOTIFICATION_CATEGORY_ALREADY_EXISTS"
    status_code = status.HTTP_409_CONFLICT
    message = "Kategorija obaveštenja sa ovom šifrom već postoji."


class PushTokenConflictError(PulsApiError):
    # Konkurentna registracija istog fizickog tokena/uredjaja pogodila je
    # UX_PUSH_TOKEN_AKTIVAN_HASH ili UX_PUSH_TOKEN_AKTIVAN_KOR. Bezbedno za retry.
    code = "PUSH_TOKEN_CONFLICT"
    status_code = status.HTTP_409_CONFLICT
    message = "Registracija push tokena nije uspela zbog istovremene izmene. Pokušajte ponovo."


class UserNotFoundError(PulsApiError):
    code = "USER_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Korisnik nije pronađen."


class AdminSelfActionNotAllowedError(PulsApiError):
    code = "ADMIN_SELF_ACTION_NOT_ALLOWED"
    status_code = status.HTTP_409_CONFLICT
    message = "Administrator ne može izvršiti ovu akciju nad sopstvenim nalogom."


class SmsDeliveryFailedError(PulsApiError):
    code = "SMS_DELIVERY_FAILED"
    status_code = status.HTTP_502_BAD_GATEWAY
    message = "Slanje SMS poruke nije uspelo. Lozinka nije promenjena."


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(PulsApiError)
    async def handle_puls_api_error(request: Request, exc: PulsApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": "Neispravni podaci u zahtevu."}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        import logging

        logging.getLogger("puls.api").exception("Unhandled exception on %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": {"code": "INTERNAL_ERROR", "message": "Došlo je do neočekivane greške."}},
        )

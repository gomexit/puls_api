"""Apstrakcija slanja FCM poruka.

Produkciona implementacija koristi Firebase Admin SDK (lazy import - paket nije
potreban za pokretanje aplikacije/testova). Fake implementacija se koristi u testovima;
nijedan test ne komunicira sa Google/Firebase servisima.

BEZBEDNOST: FCM token se ne loguje. Vraca se samo bezbedan status + kod greske."""

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("puls.push")

# Rezultati slanja (bezbedni, bez tokena/tajni).
SEND_OK = "OK"                    # FCM prihvatio poruku (nije potvrda dostave)
SEND_INVALID_TOKEN = "INVALID_TOKEN"  # token unregistered/invalid -> deaktivirati
SEND_TRANSIENT = "TRANSIENT"     # privremena greska -> retry
SEND_ERROR = "ERROR"             # ostala greska -> retry do max, pa FAILED


@dataclass
class FcmSendResult:
    status: str
    error_code: str | None = None


def classify_fcm_exception(exc: Exception) -> FcmSendResult:
    """Pure, testable klasifikacija izuzetka iz FCM send poziva u bezbedan
    FcmSendResult. Nikad ne loguje poruku izuzetka (moze sadrzati echo ulaznih
    podataka) - samo tip/kod.

    Klasifikacija koristi poredjenje po IMENU klase (a ne isinstance) namerno:
    firebase-admin je opcioni, lazy-importovan paket, pa ova funkcija mora ostati
    testabilna i bez njega instaliranog, a i dalje tacno pogadja stvarne SDK tipove
    po imenu u produkciji.

    SAMO greske koje POUZDANO znace da je token neupotrebljiv mapiraju se u
    SEND_INVALID_TOKEN (UnregisteredError, SenderIdMismatchError - ako ta verzija
    SDK-a njome oznacava token drugog projekta). Generican ValueError nastao pri
    sastavljanju/validaciji poruke NIJE dokaz da je token nevalidan - mapira se u
    trajni SEND_ERROR i NIKADA ne dovodi do deaktivacije tokena."""
    name = type(exc).__name__
    if name == "UnregisteredError":
        return FcmSendResult(status=SEND_INVALID_TOKEN, error_code="UNREGISTERED")
    if name == "SenderIdMismatchError":
        return FcmSendResult(status=SEND_INVALID_TOKEN, error_code="SENDER_ID_MISMATCH")
    if name == "UnavailableError":
        return FcmSendResult(status=SEND_TRANSIENT, error_code="UNAVAILABLE")
    if name == "InternalError":
        return FcmSendResult(status=SEND_TRANSIENT, error_code="INTERNAL")
    if isinstance(exc, ValueError):
        # Poruka nije validna/sastavljiva - ne znaci nevalidan token. Bez tokena/
        # sadrzaja u logu.
        return FcmSendResult(status=SEND_ERROR, error_code="INVALID_MESSAGE")
    code = name[:100]
    logger.warning("FCM send greska (kod=%s)", code)
    return FcmSendResult(status=SEND_ERROR, error_code=code)


class FcmProvider(Protocol):
    def send(self, fcm_token: str, data: dict[str, str], ttl_seconds: int) -> FcmSendResult:
        ...


class NullFcmProvider:
    """Placeholder kada je FCM iskljucen. Poziv je greska (worker ne radi kad je FCM off)."""

    def send(self, fcm_token: str, data: dict[str, str], ttl_seconds: int) -> FcmSendResult:
        raise RuntimeError("FCM je onemogucen (FCM_ENABLED=false).")


class FakeFcmProvider:
    """Deterministicki provider za testove. Ne kontaktira mrezu."""

    def __init__(self, result: FcmSendResult | None = None):
        self.result = result or FcmSendResult(status=SEND_OK)
        self.sent: list[dict[str, str]] = []  # data payload-i (bez tokena)

    def send(self, fcm_token: str, data: dict[str, str], ttl_seconds: int) -> FcmSendResult:
        # Namerno NE cuvamo fcm_token (bezbednost); cuvamo samo data radi asertacija.
        self.sent.append({"data": dict(data), "ttl": str(ttl_seconds)})
        return self.result


class FirebaseFcmProvider:
    """Produkciona implementacija preko Firebase Admin SDK. Aplikacija se inicijalizuje
    tacno jednom. Salje data-only, Android high priority poruku sa TTL-om."""

    _app = None  # klasno stanje: Firebase app inicijalizovan jednom po procesu

    def __init__(self, credentials_file: str):
        import firebase_admin
        from firebase_admin import credentials

        if FirebaseFcmProvider._app is None:
            cred = credentials.Certificate(credentials_file)
            # Ako je vec inicijalizovan drugde, iskoristi default app.
            try:
                FirebaseFcmProvider._app = firebase_admin.initialize_app(cred)
            except ValueError:
                FirebaseFcmProvider._app = firebase_admin.get_app()

    def send(self, fcm_token: str, data: dict[str, str], ttl_seconds: int) -> FcmSendResult:
        import datetime

        from firebase_admin import messaging

        message = messaging.Message(
            token=fcm_token,
            data={k: str(v) for k, v in data.items()},
            android=messaging.AndroidConfig(
                priority="high",
                ttl=datetime.timedelta(seconds=max(0, ttl_seconds)),
            ),
        )
        try:
            messaging.send(message)
            return FcmSendResult(status=SEND_OK)
        except Exception as exc:
            return classify_fcm_exception(exc)


def get_fcm_provider(settings) -> FcmProvider:
    """Fabrika: NullFcmProvider kad je FCM iskljucen, inace FirebaseFcmProvider.
    Poruke greske konfiguracije ne prikazuju tajne (samo putanju/postojanje fajla)."""
    if not settings.fcm_enabled:
        return NullFcmProvider()
    import os

    path = settings.fcm_credentials_file
    if not path or not os.path.isfile(path):
        raise RuntimeError("FCM_ENABLED=true ali FCM_CREDENTIALS_FILE ne postoji ili nije citljiv.")
    return FirebaseFcmProvider(path)

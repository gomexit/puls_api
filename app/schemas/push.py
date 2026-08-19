import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

FCM_TOKEN_MAX = 4000
APP_VERSION_MAX = 50
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class PushTokenRegisterRequest(BaseModel):
    # extra=forbid: identitet (korisnik_id/platni_broj/uredjaj_id) se NE prima iz payload-a.
    model_config = ConfigDict(extra="forbid")

    fcm_token: str = Field(min_length=1, max_length=FCM_TOKEN_MAX)
    app_version: str | None = Field(default=None, max_length=APP_VERSION_MAX)

    @field_validator("fcm_token")
    @classmethod
    def _token(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("FCM token je obavezan.")
        if len(v) > FCM_TOKEN_MAX:
            raise ValueError("FCM token je predugačak.")
        if _CONTROL_CHARS.search(v):
            raise ValueError("FCM token sadrži nedozvoljene znakove.")
        return v

    @field_validator("app_version")
    @classmethod
    def _app_version(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class PushTokenRegisterResponse(BaseModel):
    registered: bool


class PushTokenDeleteResponse(BaseModel):
    deactivated: bool

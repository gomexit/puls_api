import datetime

from pydantic import BaseModel, Field

STATUS_ENUM = ["NIJE_POCETO", "U_TOKU", "RESENO"]


class GameDailyResponse(BaseModel):
    datum: datetime.date = Field(description="Današnji dan (lokalno vreme servera).")
    velicina: int = Field(description="Tabla je velicina x velicina polja.")
    broj_tacaka: int
    status: str = Field(json_schema_extra={"enum": STATUS_ENUM})
    moje_vreme_ms: int | None = Field(description="Vreme prvog rešenja; null dok nije rešeno.")
    niz_dana: int = Field(description="Koliko dana zaredom sam rešio nivo (danas ili do juče).")
    prosek_orgjed_ms: int | None = Field(description="Prosek moje prodavnice (od 3 rešenja), inače null.")
    broj_resenih_orgjed: int | None


class GameLevelResponse(BaseModel):
    datum: datetime.date
    velicina: int
    tacke: list[list[int]] = Field(description="Tačke redom kao [red, kolona]; prva je start, poslednja kasa.")
    zidovi: list[list[int]] = Field(description="Zid između dva susedna polja: [red1, kol1, red2, kol2].")
    status: str = Field(description="U_TOKU ili RESENO (ponovna igra se ne računa).")


class GameResultRequest(BaseModel):
    datum: datetime.date = Field(description="`datum` nivoa iz /game/daily/start.")
    putanja: list[list[int]] = Field(
        min_length=1, max_length=100, description="Sva polja redom kao [red, kolona], od tačke 1 do kase."
    )


class GameResultResponse(GameDailyResponse):
    prvo_resenje: bool = Field(description="true = ovo rešenje je upisano; false = nivo je već bio rešen.")

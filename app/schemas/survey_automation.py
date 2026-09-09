import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SurveyAutomationOut(BaseModel):
    id: int
    anketa_id: int
    dani_od_zaposlenja: int
    rok_dana: int
    datum_primene_od: datetime.date
    aktivna: bool
    datum_kreiranja: datetime.datetime | None = None
    datum_izmene: datetime.datetime | None = None


class SurveyAutomationListResponse(BaseModel):
    items: list[SurveyAutomationOut]


class SurveyAutomationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dani_od_zaposlenja: Literal[7, 30, 60, 90]
    rok_dana: int = Field(default=7, ge=1, le=365)
    datum_primene_od: datetime.date
    aktivna: bool

from pydantic import BaseModel, ConfigDict, Field


class AdminConfigurationItemOut(BaseModel):
    kljuc: str
    vrednost: str | None
    tip_podatka: str
    opis: str | None
    koristi_podrazumevanu_vrednost: bool
    izmenio_korisnik_id: int | None


class AdminConfigurationListResponse(BaseModel):
    items: list[AdminConfigurationItemOut]


class AdminConfigurationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # VREDNOST kolona je VARCHAR2(4000) - ogranicenje se primenjuje samo na str
    # (null i dalje prolazi, bitno za DOWNLOAD_URL).
    vrednost: str | None = Field(max_length=4000)

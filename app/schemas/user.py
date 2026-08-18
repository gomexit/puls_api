from pydantic import BaseModel


class UserSummary(BaseModel):
    id: int
    platni_broj: str
    ime: str
    prezime: str
    broj_telefona: str | None = None


class CurrentUserRaspored(BaseModel):
    orgjed_sifra: str
    radno_mesto_sifra: str | None = None


class CurrentUserResponse(BaseModel):
    id: int
    platni_broj: str
    ime: str
    prezime: str
    broj_telefona: str | None = None
    status_zaposlenja: str
    status_naloga: str
    obavezna_promena_lozinke: bool
    telefon_potvrdjen: bool
    uloge: list[str]
    raspored: CurrentUserRaspored | None = None

from pydantic import BaseModel, Field


class HomeModuleOut(BaseModel):
    kod: str = Field(
        description="Stabilan kod modula: POGODNOSTI, PITAJ_HR, KVIZ, IGRA ili ZAHVALNICE.",
        examples=["POGODNOSTI"],
    )
    naziv: str = Field(description="Naziv pločice na početnom ekranu.", examples=["Moje pogodnosti"])
    aktivan: bool = Field(
        description="Da li korisnik vidi modul (MODUL_<NAZIV> = SVI, ili PILOT i korisnik je u pilotu). "
        "Aplikacija prikazuje samo aktivne module."
    )
    broj_novih: int = Field(
        default=0,
        ge=0,
        description="Broj novih stavki za oznaku na pločici (nove pogodnosti, nepročitani HR odgovori, "
        "nove zahvalnice...). Dok modul ne postoji, uvek 0.",
    )


class HomeSummaryResponse(BaseModel):
    moduli: list[HomeModuleOut] = Field(
        description="Svi novi moduli u redosledu pločica, i aktivni i neaktivni."
    )

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.schemas.survey import (
    DraftRequest,
    DraftResponse,
    MojOdgovorOut,
    OpcijaOut,
    PitanjeOut,
    SekcijaOut,
    SubmitResponse,
    SurveyDetailResponse,
    SurveyListItem,
    SurveyListResponse,
    UslovOut,
)
from app.services.survey_service import SurveyService

router = APIRouter(prefix="/surveys", tags=["Surveys"])


def get_survey_service(db: Session = Depends(get_db)) -> SurveyService:
    return SurveyService(db)


@router.get("", response_model=SurveyListResponse)
def list_surveys(
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: SurveyService = Depends(get_survey_service),
) -> SurveyListResponse:
    items, za_popunjavanje = service.list_surveys(korisnik)
    return SurveyListResponse(
        items=[
            SurveyListItem(
                id=it["anketa"].id,
                naziv=it["anketa"].naziv,
                tip=it["anketa"].tip_sifra,
                tip_naziv=it["tip_naziv"],
                anonimna=it["anketa"].is_anonimna,
                datum_pocetka=it["anketa"].datum_pocetka,
                datum_zavrsetka=it["anketa"].datum_zavrsetka,
                broj_pitanja=it["broj_pitanja"],
                moj_status=it["moj_status"],
            )
            for it in items
        ],
        za_popunjavanje=za_popunjavanje,
    )


def _build_detail(d: dict) -> SurveyDetailResponse:
    anketa = d["anketa"]
    questions_by_section: dict[int, list] = {}
    for q in d["questions"]:
        questions_by_section.setdefault(q.sekcija_id, []).append(q)

    sekcije_out = []
    for s in d["sections"]:
        pitanja_out = []
        for q in questions_by_section.get(s.id, []):
            opcije = [
                OpcijaOut(id=o.id, tekst=o.tekst, redosled=int(o.redosled))
                for o in d["opts_by_q"].get(q.id, [])
            ]
            uslov = None
            if q.uslov_pitanje_id is not None:
                uslov = UslovOut(
                    pitanje_id=q.uslov_pitanje_id,
                    operator=q.uslov_operator,
                    vrednosti=d["uslov_by_q"].get(q.id, []),
                )
            pitanja_out.append(
                PitanjeOut(
                    id=q.id,
                    tekst=q.tekst,
                    tip=q.tip_pitanja,
                    obavezno=q.obavezno_bool,
                    redosled=int(q.redosled),
                    opcije=opcije,
                    uslov=uslov,
                )
            )
        sekcije_out.append(
            SekcijaOut(id=s.id, naziv=s.naziv, redosled=int(s.redosled), pitanja=pitanja_out)
        )

    moji = [
        MojOdgovorOut(
            pitanje_id=a.pitanje_id,
            tekst=a.tekst,
            broj=a.broj,
            logicka=a.logicka,
            opcija_ids=a.opcija_ids,
        )
        for a in d["moji_odgovori"]
    ]
    return SurveyDetailResponse(
        id=anketa.id,
        naziv=anketa.naziv,
        opis=anketa.opis,
        tip=anketa.tip_sifra,
        tip_naziv=d["tip_naziv"],
        anonimna=anketa.is_anonimna,
        datum_pocetka=anketa.datum_pocetka,
        datum_zavrsetka=anketa.datum_zavrsetka,
        moj_status=d["moj_status"],
        datum_predaje=d["datum_predaje"],
        odgovori_dostupni=d["odgovori_dostupni"],
        sekcije=sekcije_out,
        moji_odgovori=moji,
    )


@router.get("/{survey_id}", response_model=SurveyDetailResponse)
def get_survey(
    survey_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: SurveyService = Depends(get_survey_service),
) -> SurveyDetailResponse:
    return _build_detail(service.get_detail(korisnik, survey_id))


@router.put("/{survey_id}/draft", response_model=DraftResponse)
def save_draft(
    survey_id: int,
    payload: DraftRequest,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: SurveyService = Depends(get_survey_service),
) -> DraftResponse:
    status = service.save_draft(korisnik, survey_id, payload.odgovori)
    return DraftResponse(message="Odgovori su sačuvani.", moj_status=status)


@router.post("/{survey_id}/submit", response_model=SubmitResponse)
def submit_survey(
    survey_id: int,
    payload: DraftRequest,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: SurveyService = Depends(get_survey_service),
) -> SubmitResponse:
    ucesce = service.submit(korisnik, survey_id, payload.odgovori)
    return SubmitResponse(
        message="Odgovori su poslati.",
        moj_status=ucesce.status,
        datum_predaje=ucesce.datum_predaje,
    )
"""Automatska dodela onboarding anketa na milestone-e (7/30/60/90 dana od
DATUM_ZAPOSLENJA), na osnovu aktivnih PULS_ANKETA_AUTOMATIKA pravila.

assign_due_surveys() vodi CEO batch u JEDNOJ transakciji (bez commit-a ovde -
poziva ga discover_events() koji commituje na kraju) - greska bilo gde u petlji
mora rollback-ovati ceo batch, ne parcijalno stanje.

RESURS_ID sistemskog dogadjaja ONBOARDING_SURVEY_AVAILABLE = PULS_ANKETA_UCESCA.ID
(ucesce_id), NE anketa_id - dodela je per-korisnik i ucesce_id jednoznacno referencira
i anketu i korisnika za kasniju obradu u _resolve_onboarding_survey_available. Inbox
obavestenje koje ce ta obrada kreirati ima svoj SOPSTVENI RESURS_ID = ANKETA_ID (za
Android deep-link na anketu) - to je odvojeno polje u PULS_OBAVESTENJA, ne meša se
sa RESURS_ID ovog dogadjaja."""

import datetime
import logging

from app.models.anketa import ANKETA_STATUS_ACTIVE, UCESCE_NOT_STARTED
from app.models.anketa_ucesce import AnketaUcesce
from app.models.sistemski_dogadjaj import DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE
from app.models.korisnik import Korisnik
from app.repositories.onboarding_automation_repository import OnboardingAutomationRepository
from app.repositories.survey_repository import SurveyRepository
from app.repositories.system_event_repository import SystemEventRepository

logger = logging.getLogger("puls.onboarding_automation")


class OnboardingSurveyAssignmentService:
    def __init__(
        self,
        db,
        automation_repository: OnboardingAutomationRepository | None = None,
        survey_repository: SurveyRepository | None = None,
        event_repository: SystemEventRepository | None = None,
    ):
        self.db = db
        self.automation_repo = automation_repository or OnboardingAutomationRepository(db)
        self.survey_repo = survey_repository or SurveyRepository(db)
        self.event_repo = event_repository or SystemEventRepository(db)

    def assign_due_surveys(self, now: datetime.datetime) -> dict:
        assigned = 0
        for pravilo in self.automation_repo.find_active_rules():
            anketa = self.survey_repo.get_survey(pravilo.anketa_id)
            if anketa is None or anketa.status != ANKETA_STATUS_ACTIVE or anketa.anonimna == "D":
                # Batch posao - neispravno/neaktivno pravilo se preskace, ne baca gresku.
                continue
            # find_qualified_candidates vec iskljucuje korisnike koji imaju postojece
            # PULS_ANKETA_UCESCA za ovu anketu (korelisani NOT EXISTS u upitu) - nema
            # dodatnog upita po kandidatu.
            kandidati: list[Korisnik] = self.automation_repo.find_qualified_candidates(pravilo, now)
            for korisnik in kandidati:
                datum_dostupnosti = self._add_days(korisnik.datum_zaposlenja, pravilo.dani_od_zaposlenja)
                datum_isteka = self._add_days(korisnik.datum_zaposlenja, pravilo.dani_od_zaposlenja + pravilo.rok_dana)
                ucesce = AnketaUcesce(
                    anketa_id=anketa.id,
                    korisnik_id=korisnik.id,
                    status=UCESCE_NOT_STARTED,
                    automatika_id=pravilo.id,
                    datum_dostupnosti=datum_dostupnosti,
                    datum_isteka=datum_isteka,
                    datum_zaposlenja_snapshot=korisnik.datum_zaposlenja,
                    datum_kreiranja=now,
                    datum_izmene=now,
                )
                self.survey_repo.add_ucesce(ucesce)
                kljuc = (
                    f"ONBOARDING_SURVEY_AVAILABLE:{anketa.id}:{korisnik.id}:"
                    f"{korisnik.datum_zaposlenja.isoformat()}"
                )
                if self.event_repo.enqueue_if_absent(
                    kljuc, DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, now
                ):
                    assigned += 1
        return {"assigned": assigned}

    @staticmethod
    def _add_days(datum: datetime.date, dani: int) -> datetime.datetime:
        rezultat = datum + datetime.timedelta(days=int(dani))
        return datetime.datetime.combine(rezultat, datetime.time.min)

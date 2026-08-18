import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    InvalidSurveyStatusTransitionError,
    SurveyNotFoundError,
    SurveyStructureLockedError,
    SurveyTypeNotFoundError,
    ValidationBusinessError,
)
from app.models.anketa import (
    ANKETA_STATUS_ACTIVE,
    ANKETA_STATUS_DRAFT,
    ANKETA_STATUS_SCHEDULED,
    CILJEVI_NEPODRZANI,
    CILJEVI_SA_VREDNOSCU,
    CILJ_ORGJED,
    CILJ_PLATNI_BROJ,
    CILJ_SVI,
    OPERATORI,
    TIPOVI_CILJA,
    TIPOVI_PITANJA,
    TIPOVI_SA_OPCIJAMA,
    Anketa,
    AnketaTip,
    is_valid_survey_transition,
)
from app.models.anketa_struktura import (
    AnketaCilj,
    AnketaOpcija,
    AnketaPitanje,
    AnketaSekcija,
    AnketaUslovVrednost,
)
from app.models.anketa_ucesce import AnketaUcesce
from app.models.korisnik import Korisnik
from app.repositories.audit_repository import AuditRepository
from app.repositories.survey_repository import SurveyRepository
from app.repositories.survey_targeting_repository import SurveyTargetingRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.survey_payload_validation import validate_admin_survey_payload
from app.services.survey_validation import validate_structure


class SurveyAdminService:
    """Admin/HR modul ANKETE. Owns the transaction boundary (commit/rollback)."""

    def __init__(
        self,
        db: Session,
        repository: SurveyRepository | None = None,
        targeting_repository: SurveyTargetingRepository | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.repo = repository or SurveyRepository(db)
        self.targeting = targeting_repository or SurveyTargetingRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )

    # ------------------------------------------------------------------ tipovi
    def list_types(self) -> list[AnketaTip]:
        return self.repo.list_types()

    def create_type(self, actor: Korisnik, sifra: str, naziv: str) -> AnketaTip:
        try:
            if self.repo.get_type(sifra) is not None:
                raise ValidationBusinessError("Tip ankete sa ovom šifrom već postoji.")
            tip = self.repo.add_type(
                AnketaTip(sifra=sifra, naziv=naziv, aktivan="D", datum_kreiranja=datetime.datetime.now())
            )
            self.db.commit()
            return tip
        except IntegrityError as exc:
            # Konkurentno kreiranje iste sifre: pre-provera je prosla ali PK odbio.
            # Mapiramo SAMO taj konkretan constraint; ostale IntegrityError re-raise.
            self.db.rollback()
            if "PK_PULS_ANKETA_TIPOVI" in str(getattr(exc, "orig", exc)).upper():
                raise ValidationBusinessError("Tip ankete sa ovom šifrom već postoji.") from exc
            raise
        except Exception:
            self.db.rollback()
            raise

    def update_type(
        self, actor: Korisnik, sifra: str, naziv: str | None, aktivan: bool | None
    ) -> AnketaTip:
        try:
            tip = self.repo.get_type(sifra)
            if tip is None:
                raise SurveyTypeNotFoundError()
            if naziv is not None:
                tip.naziv = naziv
            if aktivan is not None:
                tip.aktivan = "D" if aktivan else "N"
            tip.datum_izmene = datetime.datetime.now()
            self.db.commit()
            return tip
        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------------------ ankete
    def create_survey(self, actor: Korisnik, payload) -> Anketa:
        try:
            validate_admin_survey_payload(payload)
            tip = self.repo.get_type(payload.tip_sifra)
            if tip is None:
                raise SurveyTypeNotFoundError()
            if tip.aktivan != "D":
                raise ValidationBusinessError("Nije dozvoljeno kreiranje sa deaktiviranim tipom.")

            now = datetime.datetime.now()
            anketa = self.repo.add_survey(
                Anketa(
                    tip_sifra=payload.tip_sifra,
                    naziv=payload.naziv,
                    opis=payload.opis,
                    anonimna="D" if payload.anonimna else "N",
                    status=ANKETA_STATUS_DRAFT,
                    datum_pocetka=payload.datum_pocetka,
                    datum_zavrsetka=payload.datum_zavrsetka,
                    datum_kreiranja=now,
                )
            )
            self._persist_structure(anketa.id, payload.sekcije, payload.ciljevi, now)
            self.audit_service.log(
                AuditAction.SURVEY_CREATED,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="ANKETA",
                entitet_id=str(anketa.id),
            )
            self.db.commit()
            return anketa
        except Exception:
            self.db.rollback()
            raise

    def update_survey(self, actor: Korisnik, survey_id: int, payload) -> Anketa:
        try:
            anketa = self.repo.get_survey(survey_id)
            if anketa is None:
                raise SurveyNotFoundError()
            if anketa.status != ANKETA_STATUS_DRAFT:
                raise SurveyStructureLockedError()

            validate_admin_survey_payload(payload)
            tip = self.repo.get_type(payload.tip_sifra)
            if tip is None:
                raise SurveyTypeNotFoundError()
            if tip.aktivan != "D":
                raise ValidationBusinessError("Nije dozvoljena izmena sa deaktiviranim tipom.")

            now = datetime.datetime.now()
            anketa.tip_sifra = payload.tip_sifra
            anketa.naziv = payload.naziv
            anketa.opis = payload.opis
            anketa.anonimna = "D" if payload.anonimna else "N"
            anketa.datum_pocetka = payload.datum_pocetka
            anketa.datum_zavrsetka = payload.datum_zavrsetka
            anketa.datum_izmene = now

            self.repo.delete_structure(anketa.id)
            self.db.flush()
            self._persist_structure(anketa.id, payload.sekcije, payload.ciljevi, now)

            self.audit_service.log(
                AuditAction.SURVEY_UPDATED,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="ANKETA",
                entitet_id=str(anketa.id),
            )
            self.db.commit()
            return anketa
        except Exception:
            self.db.rollback()
            raise

    def _persist_structure(self, anketa_id: int, sekcije, ciljevi, now: datetime.datetime) -> None:
        kljuc_to_qid: dict[str, int] = {}
        optkey_to_oid: dict[str, int] = {}
        qobj_by_id: dict[int, AnketaPitanje] = {}
        pending_uslovi: list[tuple[int, object]] = []

        for s in sekcije:
            sekcija = self.repo.add_section(
                AnketaSekcija(anketa_id=anketa_id, naziv=s.naziv, redosled=s.redosled, datum_kreiranja=now)
            )
            for q in s.pitanja:
                if q.tip not in TIPOVI_PITANJA:
                    raise ValidationBusinessError("Nepoznat tip pitanja.")
                pitanje = self.repo.add_question(
                    AnketaPitanje(
                        sekcija_id=sekcija.id,
                        tekst=q.tekst,
                        tip_pitanja=q.tip,
                        obavezno="D" if q.obavezno else "N",
                        redosled=q.redosled,
                        datum_kreiranja=now,
                    )
                )
                qobj_by_id[pitanje.id] = pitanje
                if q.kljuc:
                    kljuc_to_qid[q.kljuc] = pitanje.id
                for o in q.opcije:
                    opcija = self.repo.add_option(
                        AnketaOpcija(
                            pitanje_id=pitanje.id, tekst=o.tekst, redosled=o.redosled, datum_kreiranja=now
                        )
                    )
                    if o.kljuc:
                        optkey_to_oid[o.kljuc] = opcija.id
                if q.uslov is not None:
                    pending_uslovi.append((pitanje.id, q.uslov))

        for qid, uslov in pending_uslovi:
            if uslov.operator not in OPERATORI:
                raise ValidationBusinessError("Nepoznat operator uslova.")
            control_qid = kljuc_to_qid.get(uslov.pitanje_kljuc)
            if control_qid is None:
                raise ValidationBusinessError("Uslov referencira nepoznato kontrolno pitanje.")
            control = qobj_by_id[control_qid]
            values = list(uslov.vrednosti)
            if control.tip_pitanja in TIPOVI_SA_OPCIJAMA:
                resolved = []
                for v in values:
                    oid = optkey_to_oid.get(v)
                    if oid is None:
                        raise ValidationBusinessError("Vrednost uslova ne referencira poznatu opciju.")
                    resolved.append(str(oid))
                values = resolved
            for idx, v in enumerate(values, start=1):
                self.repo.add_uslov_value(
                    AnketaUslovVrednost(pitanje_id=qid, vrednost=v, redosled=idx)
                )
            qobj_by_id[qid].uslov_pitanje_id = control_qid
            qobj_by_id[qid].uslov_operator = uslov.operator

        for c in ciljevi:
            if c.tip_cilja not in TIPOVI_CILJA:
                raise ValidationBusinessError("Nepoznat tip cilja.")
            if c.tip_cilja in CILJEVI_SA_VREDNOSCU and not c.vrednost:
                raise ValidationBusinessError("Ciljevi ORGJED/PLATNI_BROJ zahtevaju vrednost.")
            vrednost = c.vrednost if c.tip_cilja in CILJEVI_SA_VREDNOSCU else None
            self.repo.add_target(
                AnketaCilj(
                    anketa_id=anketa_id, tip_cilja=c.tip_cilja, vrednost=vrednost, datum_kreiranja=now
                )
            )
        self.db.flush()

    def change_status(self, actor: Korisnik, survey_id: int, novi_status: str) -> Anketa:
        try:
            anketa = self.repo.get_survey(survey_id)
            if anketa is None:
                raise SurveyNotFoundError()
            if not is_valid_survey_transition(anketa.status, novi_status):
                raise InvalidSurveyStatusTransitionError()

            first_exit = anketa.status == ANKETA_STATUS_DRAFT and novi_status in (
                ANKETA_STATUS_SCHEDULED,
                ANKETA_STATUS_ACTIVE,
            )
            now = datetime.datetime.now()
            if first_exit:
                # Struktura se validira i ciljevi materijalizuju samo jednom - pri
                # prvom izlasku iz DRAFT.
                validate_structure(self.repo, self.targeting, anketa)
                if novi_status == ANKETA_STATUS_SCHEDULED and anketa.datum_pocetka <= now:
                    raise ValidationBusinessError("Za SCHEDULED datum početka mora biti u budućnosti.")
                self._materialize_targets(anketa, now)

            # Prelazak u ACTIVE (DRAFT->ACTIVE i SCHEDULED->ACTIVE) mora biti unutar perioda.
            if novi_status == ANKETA_STATUS_ACTIVE and not anketa.is_within_period(now):
                raise ValidationBusinessError("Za ACTIVE trenutni datum mora biti unutar perioda ankete.")

            anketa.status = novi_status
            anketa.datum_izmene = now
            self.audit_service.log(
                AuditAction.SURVEY_STATUS_CHANGED,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="ANKETA",
                entitet_id=str(anketa.id),
                detalji=novi_status,
            )
            self.db.commit()
            return anketa
        except Exception:
            self.db.rollback()
            raise

    def _materialize_targets(self, anketa: Anketa, now: datetime.datetime) -> None:
        """Snapshot ciljanih aktivnih korisnika -> po jedan NOT_STARTED red ucesca.
        DISTINCT uklanja duplikate; unique constraint je zavrsna zastita."""
        targets = self.repo.get_targets(anketa.id)
        user_ids: set[int] = set()
        for t in targets:
            if t.tip_cilja in CILJEVI_NEPODRZANI:
                raise ValidationBusinessError(
                    "Ciljanje CENTRALA/MALOPRODAJA nije podržano (nedostaje pouzdan HR podatak)."
                )
            if t.tip_cilja == CILJ_SVI:
                user_ids |= self.targeting.all_active_user_ids()
            elif t.tip_cilja == CILJ_ORGJED:
                user_ids |= self.targeting.user_ids_by_orgjed(t.vrednost)
            elif t.tip_cilja == CILJ_PLATNI_BROJ:
                uid = self.targeting.user_id_by_platni_broj(t.vrednost)
                if uid is not None:
                    user_ids.add(uid)

        existing = self.repo.existing_participant_ids(anketa.id)
        for uid in user_ids - existing:
            self.repo.add_ucesce(
                AnketaUcesce(anketa_id=anketa.id, korisnik_id=uid, status="NOT_STARTED", datum_kreiranja=now)
            )

    def extend_deadline(self, actor: Korisnik, survey_id: int, novi_datum: datetime.datetime) -> Anketa:
        try:
            anketa = self.repo.get_survey(survey_id)
            if anketa is None:
                raise SurveyNotFoundError()
            if anketa.status not in (ANKETA_STATUS_SCHEDULED, ANKETA_STATUS_ACTIVE):
                raise ValidationBusinessError("Rok se može produžiti samo za SCHEDULED ili ACTIVE anketu.")
            novi = novi_datum
            if novi <= anketa.datum_zavrsetka:
                raise ValidationBusinessError("Novi datum završetka mora biti posle postojećeg.")
            anketa.datum_zavrsetka = novi
            anketa.datum_izmene = datetime.datetime.now()
            self.audit_service.log(
                AuditAction.SURVEY_DEADLINE_EXTENDED,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="ANKETA",
                entitet_id=str(anketa.id),
            )
            self.db.commit()
            return anketa
        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------------------ citanje
    def list_surveys(self, status, tip, datum_od, datum_do, page, page_size):
        items, total = self.repo.list_surveys(status, tip, datum_od, datum_do, page, page_size)
        enriched = []
        for a in items:
            ciljanih = self.repo.count_participants(a.id)
            predatih = self.repo.count_submitted(a.id)
            procenat = round((predatih / ciljanih * 100), 2) if ciljanih else 0.0
            enriched.append((a, ciljanih, predatih, procenat))
        return enriched, total

    def get_survey(self, survey_id: int) -> Anketa:
        anketa = self.repo.get_survey(survey_id)
        if anketa is None:
            raise SurveyNotFoundError()
        return anketa
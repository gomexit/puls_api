"""PULS IZAZOV - administracija (GMX Portal, OBO): sifarnik kategorija, kvizovi,
objava/arhiviranje i rezultati.

Pravila:
- DRAFT -> OBJAVLJEN -> ARHIVIRAN (DRAFT -> ARHIVIRAN dozvoljen). Nazad nema.
- DRAFT se menja u celini (pitanja i ciljevi se zamenjuju).
- OBJAVLJEN: samo naziv, opis i produzenje DATUM_DO; ostalo -> 409 QUIZ_LOCKED.
- Dva objavljena kviza ne smeju imati preklopljen period (409 QUIZ_PERIOD_OVERLAP).
- Pitanje: 2-4 opcije, tacno jedna tacna, aktivna kategorija, aktivna slika (opciono).
Svaka izmena: jedna transakcija, SELECT FOR UPDATE, odgovor pre commit-a, rollback na gresku."""

import datetime
import re
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    InvalidQuizStatusError,
    InvalidQuizStatusTransitionError,
    QuizArchivedError,
    QuizCategoryAlreadyExistsError,
    QuizCategoryNotFoundError,
    QuizLockedError,
    QuizNotFoundError,
    QuizNotReadyError,
    QuizPeriodOverlapError,
    ValidationBusinessError,
)
from app.models.korisnik import Korisnik
from app.models.kviz import (
    KVIZ_CILJ_TIPOVI,
    KVIZ_STATUS_ARHIVIRAN,
    KVIZ_STATUS_DRAFT,
    KVIZ_STATUS_OBJAVLJEN,
    KVIZ_STATUSI,
    MAX_OPCIJA,
    MAX_PITANJA,
    MIN_OPCIJA,
    TRAJANJE_MAX_SEKUNDI,
    TRAJANJE_MIN_SEKUNDI,
    TRAJANJE_PODRAZUMEVANO,
    Kviz,
    KvizKategorija,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.quiz_repository import QuizRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.system_notification_service import SystemNotificationService

ENTITY_QUIZ = "KVIZ"
ENTITY_CATEGORY = "KVIZ_KATEGORIJA"
SIFRA_RE = re.compile(r"^[A-Z0-9_]{1,30}$")
MAX_CILJEVA = 500
# Prosek org. jedinice se prikazuje tek od ovoliko zavrsenih pokusaja (privatnost).
MIN_POKUSAJA_ZA_PROSEK = 3


def normalize_status(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if normalized not in KVIZ_STATUSI:
        raise InvalidQuizStatusError()
    return normalized


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def category_view(k: KvizKategorija) -> dict:
    return {
        "sifra": k.sifra,
        "naziv": k.naziv,
        "redosled": int(k.redosled),
        "aktivna": k.aktivna == "D",
        "kreirao_platni_broj": k.kreirao_platni_broj,
        "izmenio_platni_broj": k.izmenio_platni_broj,
        "datum_kreiranja": k.datum_kreiranja,
        "datum_izmene": k.datum_izmene,
    }


def _quiz_summary(k: Kviz, broj_pitanja: int) -> dict:
    return {
        "id": int(k.id),
        "naziv": k.naziv,
        "opis": k.opis,
        "datum_od": k.datum_od,
        "datum_do": k.datum_do,
        "trajanje_sekundi": int(k.trajanje_sekundi),
        "status": k.status,
        "broj_pitanja": broj_pitanja,
        "kreirao_platni_broj": k.kreirao_platni_broj,
        "izmenio_platni_broj": k.izmenio_platni_broj,
        "datum_objave": k.datum_objave,
        "datum_kreiranja": k.datum_kreiranja,
        "datum_izmene": k.datum_izmene,
    }


class QuizAdminService:
    def __init__(
        self,
        db: Session,
        repository: QuizRepository | None = None,
        audit_service: AuditService | None = None,
        system_notification_service: SystemNotificationService | None = None,
        settings: Settings | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.repo = repository or QuizRepository(db)
        self.audit_service = audit_service or AuditService(AuditRepository(db), izvor=self.settings.audit_source)
        self.system_notifications = system_notification_service or SystemNotificationService(db)
        self._now_fn = now_fn or datetime.datetime.now

    # ================================================================ kategorije
    def list_categories(self, aktivna: bool | None = None) -> list[dict]:
        flag = None if aktivna is None else ("D" if aktivna else "N")
        return [category_view(k) for k in self.repo.list_categories(flag)]

    def create_category(self, actor: Korisnik, sifra: str, naziv: str, redosled: int, aktivna: bool) -> dict:
        sifra_norm = (sifra or "").strip().upper()
        if not SIFRA_RE.match(sifra_norm):
            raise ValidationBusinessError("Šifra sme da sadrži samo velika slova, cifre i _ (najviše 30).")
        try:
            if self.repo.get_category(sifra_norm) is not None:
                raise QuizCategoryAlreadyExistsError()
            now = self._now_fn()
            kat = KvizKategorija(
                sifra=sifra_norm,
                naziv=naziv,
                redosled=redosled,
                aktivna="D" if aktivna else "N",
                kreirao_platni_broj=actor.platni_broj,
                izmenio_platni_broj=actor.platni_broj,
                datum_kreiranja=now,
                datum_izmene=now,
            )
            self.repo.add_category(kat)
            self.db.flush()
            self._audit(actor, AuditAction.ADMIN_QUIZ_CATEGORY_CREATED, ENTITY_CATEGORY, sifra_norm,
                        f"sifra={sifra_norm}; aktivna={kat.aktivna}")
            view = category_view(kat)
            self.db.commit()
            return view
        except IntegrityError as exc:  # konkurentan unos iste sifre
            self.db.rollback()
            raise QuizCategoryAlreadyExistsError() from exc
        except Exception:
            self.db.rollback()
            raise

    def update_category(self, actor: Korisnik, sifra: str, naziv: str, redosled: int, aktivna: bool) -> dict:
        sifra_norm = (sifra or "").strip().upper()
        try:
            kat = self.repo.get_category_for_update(sifra_norm)
            if kat is None:
                raise QuizCategoryNotFoundError()
            flag = "D" if aktivna else "N"
            if (kat.naziv, int(kat.redosled), kat.aktivna) != (naziv, redosled, flag):
                kat.naziv = naziv
                kat.redosled = redosled
                kat.aktivna = flag
                kat.izmenio_platni_broj = actor.platni_broj
                kat.datum_izmene = self._now_fn()
                self.db.flush()
                self._audit(actor, AuditAction.ADMIN_QUIZ_CATEGORY_UPDATED, ENTITY_CATEGORY, sifra_norm,
                            f"sifra={sifra_norm}; aktivna={flag}")
            view = category_view(kat)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # ================================================================= kvizovi
    def list_quizzes(self, status: str | None, search: str | None, page: int, page_size: int) -> dict:
        status_norm = normalize_status(status) if status is not None else None
        search_norm = (search or "").strip() or None
        if search_norm and len(search_norm) > 200:
            raise ValidationBusinessError("Pretraga može imati najviše 200 karaktera.")
        rows, total = self.repo.list_admin(status_norm, search_norm, page, page_size)
        counts = self.repo.question_counts(int(r.id) for r in rows)
        return {
            "items": [_quiz_summary(r, counts.get(int(r.id), 0)) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_quiz(self, kviz_id: int) -> dict:
        kviz = self.repo.get(kviz_id)
        if kviz is None:
            raise QuizNotFoundError()
        return self._detail(kviz)

    def create_quiz(self, actor: Korisnik, payload: dict) -> dict:
        data = self._validate_full(payload)
        try:
            now = self._now_fn()
            kviz = Kviz(
                naziv=data["naziv"],
                opis=data["opis"],
                datum_od=data["datum_od"],
                datum_do=data["datum_do"],
                trajanje_sekundi=data["trajanje_sekundi"],
                status=KVIZ_STATUS_DRAFT,
                kreirao_platni_broj=actor.platni_broj,
                izmenio_platni_broj=actor.platni_broj,
                datum_objave=None,
                datum_kreiranja=now,
                datum_izmene=now,
            )
            self.repo.add(kviz)
            self.db.flush()  # ID kviza
            self.repo.replace_targets(int(kviz.id), data["ciljevi"])
            self.repo.replace_questions(int(kviz.id), data["pitanja"])
            self.db.flush()
            self._audit_quiz(actor, AuditAction.ADMIN_QUIZ_CREATED, kviz, len(data["pitanja"]))
            view = self._detail(kviz)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def update_quiz(self, actor: Korisnik, kviz_id: int, payload: dict) -> dict:
        try:
            kviz = self._locked(kviz_id)
            if kviz.status == KVIZ_STATUS_ARHIVIRAN:
                raise QuizArchivedError()
            if kviz.status == KVIZ_STATUS_OBJAVLJEN:
                changed = self._update_published(kviz, payload)
            else:
                changed = self._update_draft(kviz, payload)
            if changed:
                kviz.izmenio_platni_broj = actor.platni_broj
                kviz.datum_izmene = self._now_fn()
                self.db.flush()
                self._audit_quiz(actor, AuditAction.ADMIN_QUIZ_UPDATED, kviz, None)
            view = self._detail(kviz)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def change_status(self, actor: Korisnik, kviz_id: int, novi_status: str | None) -> dict:
        target = normalize_status(novi_status)
        try:
            kviz = self._locked(kviz_id)
            if kviz.status == target:  # idempotentno
                view = self._detail(kviz)
                self.db.commit()
                return view
            now = self._now_fn()
            if target == KVIZ_STATUS_OBJAVLJEN and kviz.status == KVIZ_STATUS_DRAFT:
                self._check_ready(kviz, now)
                self._check_overlap(kviz.datum_od, kviz.datum_do, int(kviz.id))
                kviz.status = KVIZ_STATUS_OBJAVLJEN
                kviz.datum_objave = now
                akcija = AuditAction.ADMIN_QUIZ_PUBLISHED
            elif target == KVIZ_STATUS_ARHIVIRAN and kviz.status in (KVIZ_STATUS_DRAFT, KVIZ_STATUS_OBJAVLJEN):
                kviz.status = KVIZ_STATUS_ARHIVIRAN
                akcija = AuditAction.ADMIN_QUIZ_ARCHIVED
            else:
                raise InvalidQuizStatusTransitionError()
            kviz.izmenio_platni_broj = actor.platni_broj
            kviz.datum_izmene = now
            self.db.flush()
            if kviz.status == KVIZ_STATUS_OBJAVLJEN and kviz.datum_od <= now:
                # Vec u periodu: push odmah. Za buduci DATUM_OD dogadjaj enqueue-uje worker.
                self.system_notifications.enqueue_quiz_activated(int(kviz.id))
            self._audit_quiz(actor, akcija, kviz, None)
            view = self._detail(kviz)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # ================================================================ rezultati
    def results(self, kviz_id: int) -> dict:
        kviz = self.repo.get(kviz_id)
        if kviz is None:
            raise QuizNotFoundError()
        pitanja = self.repo.get_questions(int(kviz.id))
        totals = self.repo.attempt_totals(int(kviz.id))
        q_stats = self.repo.question_stats(int(kviz.id))
        po_pitanju = []
        for p in pitanja:
            odgovora, tacnih = q_stats.get(int(p.id), (0, 0))
            po_pitanju.append(
                {
                    "pitanje_id": int(p.id),
                    "redosled": int(p.redosled),
                    "tekst": p.tekst,
                    "broj_odgovora": odgovora,
                    "broj_tacnih": tacnih,
                    "procenat_tacnih": _round(100.0 * tacnih / odgovora, 1) if odgovora else None,
                }
            )
        return {
            "kviz_id": int(kviz.id),
            "naziv": kviz.naziv,
            "status": kviz.status,
            "broj_pitanja": len(pitanja),
            "broj_pokusaja": totals["ukupno"],
            "broj_zavrsenih": totals["zavrseno"],
            "prosek_tacnih": _round(totals["prosek_tacnih"]),
            "prosek_trajanja_ms": int(totals["prosek_trajanja_ms"]) if totals["prosek_trajanja_ms"] is not None else None,
            "po_orgjed": [
                {"orgjed_sifra": o, "broj_zavrsenih": c, "prosek_tacnih": _round(a)}
                for o, c, a in self.repo.orgjed_stats(int(kviz.id))
            ],
            "po_pitanju": po_pitanju,
        }

    # ================================================================ helpers
    def _locked(self, kviz_id: int) -> Kviz:
        kviz = self.repo.get_for_update(kviz_id)
        if kviz is None:
            raise QuizNotFoundError()
        return kviz

    def _update_published(self, kviz: Kviz, payload: dict) -> bool:
        for locked in ("datum_od", "trajanje_sekundi", "ciljevi", "pitanja"):
            if payload.get(locked) is not None:
                raise QuizLockedError()
        changed = False
        if payload.get("naziv") is not None and payload["naziv"] != kviz.naziv:
            kviz.naziv = payload["naziv"]
            changed = True
        if "opis" in payload and payload["opis"] != kviz.opis:
            kviz.opis = payload["opis"]
            changed = True
        novi_do = payload.get("datum_do")
        if novi_do is not None and novi_do != kviz.datum_do:
            if novi_do < kviz.datum_do:
                raise QuizLockedError("Rok objavljenog kviza može samo da se produži.")
            self._check_overlap(kviz.datum_od, novi_do, int(kviz.id))
            kviz.datum_do = novi_do
            changed = True
        return changed

    def _update_draft(self, kviz: Kviz, payload: dict) -> bool:
        merged = {
            "naziv": payload.get("naziv") if payload.get("naziv") is not None else kviz.naziv,
            "opis": payload.get("opis", kviz.opis),
            "datum_od": payload.get("datum_od") or kviz.datum_od,
            "datum_do": payload.get("datum_do") or kviz.datum_do,
            "trajanje_sekundi": payload.get("trajanje_sekundi") or int(kviz.trajanje_sekundi),
            "ciljevi": payload.get("ciljevi"),
            "pitanja": payload.get("pitanja"),
        }
        data = self._validate_full(merged)
        kviz.naziv = data["naziv"]
        kviz.opis = data["opis"]
        kviz.datum_od = data["datum_od"]
        kviz.datum_do = data["datum_do"]
        kviz.trajanje_sekundi = data["trajanje_sekundi"]
        if payload.get("ciljevi") is not None:
            self.repo.replace_targets(int(kviz.id), data["ciljevi"])
        if payload.get("pitanja") is not None:
            self.repo.replace_questions(int(kviz.id), data["pitanja"])
        return True

    def _validate_full(self, payload: dict) -> dict:
        naziv = (payload.get("naziv") or "").strip()
        if not naziv:
            raise ValidationBusinessError("Naziv kviza je obavezan.")
        opis = payload.get("opis")
        opis = (opis.strip() or None) if isinstance(opis, str) else None
        datum_od, datum_do = payload.get("datum_od"), payload.get("datum_do")
        if datum_od is None or datum_do is None:
            raise ValidationBusinessError("Period kviza (datum_od, datum_do) je obavezan.")
        if datum_do <= datum_od:
            raise ValidationBusinessError("datum_do mora biti posle datum_od.")
        trajanje = payload.get("trajanje_sekundi") or TRAJANJE_PODRAZUMEVANO
        if not TRAJANJE_MIN_SEKUNDI <= int(trajanje) <= TRAJANJE_MAX_SEKUNDI:
            raise ValidationBusinessError(
                f"Trajanje mora biti između {TRAJANJE_MIN_SEKUNDI} i {TRAJANJE_MAX_SEKUNDI} sekundi."
            )
        return {
            "naziv": naziv,
            "opis": opis,
            "datum_od": datum_od,
            "datum_do": datum_do,
            "trajanje_sekundi": int(trajanje),
            "ciljevi": self._validate_targets(payload.get("ciljevi") or []),
            "pitanja": self._validate_questions(payload.get("pitanja") or []),
        }

    @staticmethod
    def _validate_targets(ciljevi: list[dict]) -> list[tuple[str, str]]:
        seen: list[tuple[str, str]] = []
        for c in ciljevi:
            tip = (c.get("tip") or "").strip().upper()
            vrednost = (c.get("vrednost") or "").strip()
            if tip not in KVIZ_CILJ_TIPOVI:
                raise ValidationBusinessError("Tip cilja mora biti ORGJED ili PLATNI_BROJ.")
            if not vrednost or len(vrednost) > 50:
                raise ValidationBusinessError("Vrednost cilja je obavezna (najviše 50 karaktera).")
            if (tip, vrednost) not in seen:
                seen.append((tip, vrednost))
        if len(seen) > MAX_CILJEVA:
            raise ValidationBusinessError(f"Najviše {MAX_CILJEVA} ciljeva.")
        return seen

    def _validate_questions(self, pitanja: list[dict]) -> list[dict]:
        if len(pitanja) > MAX_PITANJA:
            raise ValidationBusinessError(f"Kviz može imati najviše {MAX_PITANJA} pitanja.")
        result = []
        for idx, p in enumerate(pitanja, start=1):
            tekst = (p.get("tekst") or "").strip()
            objasnjenje = (p.get("objasnjenje") or "").strip()
            if not tekst or not objasnjenje:
                raise ValidationBusinessError(f"Pitanje {idx}: tekst i objašnjenje su obavezni.")
            opcije = []
            for o in p.get("opcije") or []:
                o_tekst = (o.get("tekst") or "").strip()
                if not o_tekst:
                    raise ValidationBusinessError(f"Pitanje {idx}: tekst odgovora je obavezan.")
                opcije.append({"tekst": o_tekst, "tacna": bool(o.get("tacna"))})
            if not MIN_OPCIJA <= len(opcije) <= MAX_OPCIJA:
                raise ValidationBusinessError(f"Pitanje {idx}: potrebno je {MIN_OPCIJA}-{MAX_OPCIJA} odgovora.")
            if sum(1 for o in opcije if o["tacna"]) != 1:
                raise ValidationBusinessError(f"Pitanje {idx}: tačno jedan odgovor mora biti tačan.")
            result.append(
                {
                    "tekst": tekst,
                    "objasnjenje": objasnjenje,
                    "kategorija_sifra": (p.get("kategorija_sifra") or "").strip().upper(),
                    "slika_id": p.get("slika_id"),
                    "opcije": opcije,
                }
            )
        kategorije = {p["kategorija_sifra"] for p in result}
        if kategorije - self.repo.active_category_codes(kategorije):
            raise ValidationBusinessError("Kategorija pitanja ne postoji ili nije aktivna.")
        slike = {int(p["slika_id"]) for p in result if p["slika_id"] is not None}
        if slike - self.repo.active_image_ids(slike):
            raise ValidationBusinessError("Slika pitanja ne postoji ili je arhivirana.")
        return result

    def _check_ready(self, kviz: Kviz, now: datetime.datetime) -> None:
        if not self.repo.get_questions(int(kviz.id)):
            raise QuizNotReadyError("Kviz mora imati bar jedno pitanje.")
        if kviz.datum_do <= now:
            raise QuizNotReadyError("Rok kviza je već prošao.")

    def _check_overlap(self, datum_od, datum_do, exclude_id: int | None) -> None:
        if self.repo.find_overlapping_published(datum_od, datum_do, exclude_id):
            raise QuizPeriodOverlapError()

    def _detail(self, kviz: Kviz) -> dict:
        kviz_id = int(kviz.id)
        pitanja = self.repo.get_questions(kviz_id)
        opcije = self.repo.get_options(int(p.id) for p in pitanja)
        by_q: dict[int, list] = {}
        for o in opcije:
            by_q.setdefault(int(o.pitanje_id), []).append(o)
        view = _quiz_summary(kviz, len(pitanja))
        view["ciljevi"] = [{"tip": c.tip_cilja, "vrednost": c.vrednost} for c in self.repo.get_targets(kviz_id)]
        view["pitanja"] = [
            {
                "id": int(p.id),
                "redosled": int(p.redosled),
                "tekst": p.tekst,
                "kategorija_sifra": p.kategorija_sifra,
                "slika_id": int(p.slika_id) if p.slika_id is not None else None,
                "slika_url": f"/api/v1/images/{int(p.slika_id)}" if p.slika_id is not None else None,
                "objasnjenje": p.objasnjenje,
                "opcije": [
                    {"id": int(o.id), "redosled": int(o.redosled), "tekst": o.tekst, "tacna": o.tacna == "D"}
                    for o in sorted(by_q.get(int(p.id), []), key=lambda x: int(x.redosled))
                ],
            }
            for p in pitanja
        ]
        return view

    def _audit(self, actor: Korisnik, akcija: str, tip: str, entitet_id: str, detalji: str) -> None:
        self.audit_service.log(
            akcija,
            korisnik_id=actor.id,
            platni_broj=actor.platni_broj,
            tip_entiteta=tip,
            entitet_id=entitet_id,
            detalji=detalji,
        )

    def _audit_quiz(self, actor: Korisnik, akcija: str, kviz: Kviz, broj_pitanja: int | None) -> None:
        # Bez teksta pitanja i tacnih odgovora.
        detalji = f"kviz_id={int(kviz.id)}; status={kviz.status}"
        if broj_pitanja is not None:
            detalji += f"; broj_pitanja={broj_pitanja}"
        self._audit(actor, akcija, ENTITY_QUIZ, str(int(kviz.id)), detalji)

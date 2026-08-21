"""In-memory fake-ovi za modul OBAVESTENJA (bez prave Oracle baze)."""

import datetime
import itertools
from types import SimpleNamespace

from app.models.obavestenje import (
    Obavestenje,
    ObavestenjeCilj,
    ObavestenjeKategorija,
    ObavestenjePrimalac,
)
from app.repositories.notification_repository import (
    READ_STATUS_READ,
    READ_STATUS_UNREAD,
)

_ids = itertools.count(1)


def _next_id() -> int:
    return next(_ids)


class FakeNotifDb:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def flush(self) -> None:
        self.flushed += 1


class FakeNotificationRepo:
    def __init__(self):
        self.categories: dict[str, ObavestenjeKategorija] = {}
        self.notifications: dict[int, Obavestenje] = {}
        self.targets: list[ObavestenjeCilj] = []
        self.recipients: list[ObavestenjePrimalac] = []
        self.survey_ids: set[int] = set()
        self.idea_ids: set[int] = set()
        self.idea_cycle_ids: set[int] = set()

    # --- setup helpers ---
    def add_category(self, kat: ObavestenjeKategorija) -> ObavestenjeKategorija:
        self.categories[kat.sifra] = kat
        return kat

    def seed_notification(self, obav: Obavestenje) -> Obavestenje:
        if obav.id is None:
            obav.id = _next_id()
        self.notifications[obav.id] = obav
        return obav

    def seed_recipient(self, primalac: ObavestenjePrimalac) -> ObavestenjePrimalac:
        if primalac.id is None:
            primalac.id = _next_id()
        self.recipients.append(primalac)
        return primalac

    # --- read side ---
    def _available_rows(self, korisnik_id, now, read_status, category):
        rows = []
        for p in self.recipients:
            if p.korisnik_id != korisnik_id:
                continue
            obav = self.notifications.get(p.obavestenje_id)
            if obav is None or not obav.is_available_to_employees(now):
                continue
            if read_status == READ_STATUS_READ and p.procitano != "D":
                continue
            if read_status == READ_STATUS_UNREAD and p.procitano != "N":
                continue
            if category is not None and obav.kategorija_sifra != category:
                continue
            kat = self.categories.get(obav.kategorija_sifra)
            rows.append((obav, p, kat))
        rows.sort(key=lambda r: (r[0].datum_objave, r[0].id), reverse=True)
        return rows

    def list_inbox(self, korisnik_id, now, read_status, category, page, page_size):
        rows = self._available_rows(korisnik_id, now, read_status, category)
        total = len(rows)
        start = (page - 1) * page_size
        return rows[start : start + page_size], total

    def count_unread(self, korisnik_id, now):
        return len(self._available_rows(korisnik_id, now, READ_STATUS_UNREAD, None))

    def get_inbox_item(self, korisnik_id, notification_id, now):
        for obav, p, kat in self._available_rows(korisnik_id, now, "ALL", None):
            if obav.id == notification_id:
                return obav, p, kat
        return None

    def get_available_notification(self, notification_id, now):
        obav = self.notifications.get(notification_id)
        if obav is not None and obav.is_available_to_employees(now):
            return obav
        return None

    def recipient_exists(self, notification_id, korisnik_id):
        return any(
            p.obavestenje_id == notification_id and p.korisnik_id == korisnik_id
            for p in self.recipients
        )

    def unread_recipient_ids(self, notification_id):
        return {
            p.korisnik_id
            for p in self.recipients
            if p.obavestenje_id == notification_id and p.procitano == "N"
        }

    def get_recipient_for_update(self, notification_id, korisnik_id):
        return next(
            (
                p
                for p in self.recipients
                if p.obavestenje_id == notification_id and p.korisnik_id == korisnik_id
            ),
            None,
        )

    # --- kategorije ---
    def get_category(self, sifra):
        return self.categories.get(sifra)

    def list_categories(self, aktivna=None):
        items = list(self.categories.values())
        if aktivna is not None:
            items = [k for k in items if k.aktivna == ("D" if aktivna else "N")]
        # REDOSLED ASC (NULL poslednje), pa SIFRA ASC.
        return sorted(
            items,
            key=lambda k: (k.redosled is None, k.redosled if k.redosled is not None else 0, k.sifra),
        )

    # --- resurs provere ---
    def survey_exists(self, survey_id):
        return survey_id in self.survey_ids

    def idea_exists(self, idea_id):
        return idea_id in self.idea_ids

    def idea_cycle_exists(self, cycle_id):
        return cycle_id in self.idea_cycle_ids

    # --- admin citanje ---
    def admin_list(self, status, category, datum_od, datum_do, page, page_size):
        items = list(self.notifications.values())
        if status is not None:
            items = [o for o in items if o.status == status]
        if category is not None:
            items = [o for o in items if o.kategorija_sifra == category]
        if datum_od is not None:
            items = [o for o in items if o.datum_kreiranja and o.datum_kreiranja >= datum_od]
        if datum_do is not None:
            items = [o for o in items if o.datum_kreiranja and o.datum_kreiranja <= datum_do]
        items.sort(key=lambda o: (o.datum_kreiranja, o.id), reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        rows = [self._list_row(o) for o in items[start : start + page_size]]
        return rows, total

    def _list_row(self, o):
        ukupno, procitano = self.recipient_counts(o.id)
        kat = self.categories.get(o.kategorija_sifra)
        return SimpleNamespace(
            id=o.id,
            kategorija_sifra=o.kategorija_sifra,
            kategorija_naziv=kat.naziv if kat else o.kategorija_sifra,
            naslov=o.naslov,
            kratak_tekst=o.kratak_tekst,
            status=o.status,
            akcija_tip=o.akcija_tip,
            resurs_id=o.resurs_id,
            akcija_url=o.akcija_url,
            kreirao_platni_broj=o.kreirao_platni_broj,
            datum_objave=o.datum_objave,
            datum_isteka=o.datum_isteka,
            datum_kreiranja=o.datum_kreiranja,
            datum_izmene=o.datum_izmene,
            broj_primalaca=ukupno,
            broj_procitanih=procitano,
        )

    def recipient_counts(self, notification_id):
        recips = [p for p in self.recipients if p.obavestenje_id == notification_id]
        ukupno = len(recips)
        procitano = sum(1 for p in recips if p.procitano == "D")
        return ukupno, procitano

    def delete_targets(self, notification_id):
        self.targets = [c for c in self.targets if c.obavestenje_id != notification_id]

    # --- publishing side ---

    def get_notification(self, notification_id):
        return self.notifications.get(notification_id)

    def get_notification_for_update(self, notification_id):
        return self.notifications.get(notification_id)

    def add_notification(self, obav):
        obav.id = _next_id()
        self.notifications[obav.id] = obav
        return obav

    def add_target(self, cilj):
        cilj.id = _next_id()
        self.targets.append(cilj)
        return cilj

    def get_targets(self, notification_id):
        return [c for c in self.targets if c.obavestenje_id == notification_id]

    def add_recipient(self, primalac):
        primalac.id = _next_id()
        self.recipients.append(primalac)
        return primalac

    def existing_recipient_ids(self, notification_id):
        return {p.korisnik_id for p in self.recipients if p.obavestenje_id == notification_id}


class FakePushDeliveryRepo:
    """In-memory PULS_PUSH_ISPORUKE za testove."""

    def __init__(self):
        self.rows: list[SimpleNamespace] = []

    def existing_user_ids(self, obavestenje_id):
        return {r.korisnik_id for r in self.rows if r.obavestenje_id == obavestenje_id}

    def add_pending(self, obavestenje_id, korisnik_id, now):
        r = SimpleNamespace(
            id=_next_id(), obavestenje_id=obavestenje_id, korisnik_id=korisnik_id,
            status="PENDING", broj_pokusaja=0, datum_sledeceg_pokusaja=now,
            poslednji_error_code=None, datum_kreiranja=now, datum_poslednjeg_pokusaja=None,
            datum_slanja=None, broj_ponovnih_slanja=0,
        )
        self.rows.append(r)
        return r

    def create_pending_for_recipients(self, obavestenje_id, korisnik_ids, now):
        existing = self.existing_user_ids(obavestenje_id)
        created = 0
        for uid in korisnik_ids - existing:
            self.add_pending(obavestenje_id, uid, now)
            created += 1
        return created

    def requeue_unread(self, obavestenje_id, unread_user_ids, now):
        seen = set()
        affected = 0
        for r in self.rows:
            if r.obavestenje_id == obavestenje_id and r.korisnik_id in unread_user_ids:
                seen.add(r.korisnik_id)
                r.status = "PENDING"
                r.broj_pokusaja = 0
                r.datum_sledeceg_pokusaja = now
                r.poslednji_error_code = None
                r.datum_slanja = None
                r.datum_poslednjeg_pokusaja = None
                r.broj_ponovnih_slanja = (r.broj_ponovnih_slanja or 0) + 1
                affected += 1
        for uid in unread_user_ids - seen:
            r = self.add_pending(obavestenje_id, uid, now)
            r.broj_ponovnih_slanja = 1
            affected += 1
        return affected

    def claim_ready_batch(self, now, limit):
        ready = [
            r for r in self.rows
            if r.status == "PENDING"
            and (r.datum_sledeceg_pokusaja is None or r.datum_sledeceg_pokusaja <= now)
        ]
        ready.sort(key=lambda r: (r.datum_sledeceg_pokusaja or now, r.id))
        return ready[:limit]

    def get(self, delivery_id):
        return next((r for r in self.rows if r.id == delivery_id), None)

    def stats_for_notification(self, obavestenje_id):
        rows = [r for r in self.rows if r.obavestenje_id == obavestenje_id]
        return {
            "push_pending": sum(1 for r in rows if r.status == "PENDING"),
            "push_sent": sum(1 for r in rows if r.status == "SENT"),
            "push_failed": sum(1 for r in rows if r.status == "FAILED"),
            "push_skipped": sum(1 for r in rows if r.status == "SKIPPED"),
        }

    def count_sent(self, obavestenje_id):
        return sum(1 for r in self.rows if r.obavestenje_id == obavestenje_id and r.status == "SENT")


class FakeNotificationTargetingRepo:
    def __init__(self, all_ids=None, by_orgjed=None, by_platni=None):
        self._all = set(all_ids or [])
        self._by_orgjed = by_orgjed or {}
        self._by_platni = by_platni or {}

    def all_active_user_ids(self):
        return set(self._all)

    def user_ids_by_orgjed(self, orgjed):
        return set(self._by_orgjed.get(orgjed, set()))

    def user_id_by_platni_broj(self, platni):
        return self._by_platni.get(platni)


class FakeConfigService:
    def __init__(self, values=None):
        self.values = values or {}

    def get_int(self, kljuc, default):
        return int(self.values.get(kljuc, default))

    def get_str(self, kljuc, default):
        return self.values.get(kljuc, default)


# --------------------------------------------------------------------- fabrike
def make_kategorija(sifra="OPSTE", naziv="Opšte", aktivna="D") -> ObavestenjeKategorija:
    return ObavestenjeKategorija(sifra=sifra, naziv=naziv, aktivna=aktivna, redosled=10)


def make_obavestenje(**ov) -> Obavestenje:
    now = datetime.datetime(2026, 8, 18, 10, 0, 0)
    defaults = dict(
        id=_next_id(),
        kategorija_sifra="OPSTE",
        naslov="Naslov",
        kratak_tekst="Kratak tekst",
        sadrzaj="Sadržaj obaveštenja",
        status="PUBLISHED",
        akcija_tip="NONE",
        resurs_id=None,
        akcija_url=None,
        datum_objave=now - datetime.timedelta(days=1),
        datum_isteka=now + datetime.timedelta(days=29),
        datum_kreiranja=now - datetime.timedelta(days=1),
    )
    defaults.update(ov)
    return Obavestenje(**defaults)


def make_primalac(obavestenje_id, korisnik_id, procitano="N", datum_citanja=None) -> ObavestenjePrimalac:
    return ObavestenjePrimalac(
        id=_next_id(),
        obavestenje_id=obavestenje_id,
        korisnik_id=korisnik_id,
        procitano=procitano,
        datum_citanja=datum_citanja,
    )

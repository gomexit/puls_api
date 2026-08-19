import datetime
import itertools

from app.models.idea_ciklus import IdeaCiklus
from app.models.ideja import Ideja
from app.models.korisnicka_sesija import KorisnickaSesija
from app.models.korisnik import Korisnik
from app.models.korisnik_raspored import KorisnikRaspored
from app.models.reset_lozinke import ResetLozinke
from app.services.sms_service import SmsProvider

_id_counter = itertools.count(1)


class FakeDb:
    """Stand-in SQLAlchemy Session: only commit/rollback are exercised by the services under test."""

    def __init__(self):
        self.committed = 0
        self.rolled_back = 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


def make_korisnik(**overrides) -> Korisnik:
    defaults = dict(
        id=next(_id_counter),
        platni_broj="12345",
        ime="Boro",
        prezime="Radojcic",
        broj_telefona="060123456",
        lozinka_hash=None,
        status_zaposlenja="AKTIVAN",
        status_naloga="OMOGUCEN",
        obavezna_promena_lozinke="D",
        telefon_potvrdjen="N",
        broj_neuspesnih_prijava=0,
        zakljucan="N",
        datum_zakljucavanja=None,
    )
    defaults.update(overrides)
    return Korisnik(**defaults)


class FakeKorisnikRepository:
    def __init__(self, korisnici: list[Korisnik] | None = None):
        self.korisnici = {k.id: k for k in (korisnici or [])}

    def add(self, korisnik: Korisnik) -> None:
        self.korisnici[korisnik.id] = korisnik

    def get_by_id(self, korisnik_id: int) -> Korisnik | None:
        return self.korisnici.get(korisnik_id)

    def get_by_platni_broj(self, platni_broj: str) -> Korisnik | None:
        for k in self.korisnici.values():
            if k.platni_broj == platni_broj:
                return k
        return None

    def list_candidates_for_provisioning(self, limit: int | None = None) -> list[Korisnik]:
        candidates = [
            k
            for k in sorted(self.korisnici.values(), key=lambda x: x.id)
            if k.status_zaposlenja == "AKTIVAN"
            and k.status_naloga == "OMOGUCEN"
            and k.lozinka_hash is None
        ]
        if limit is not None:
            candidates = candidates[:limit]
        return candidates

    def get_active_role_codes(self, korisnik_id: int) -> list[str]:
        return []

    def get_primary_active_raspored(self, korisnik_id: int):
        return None


class FakeSessionRepository:
    def __init__(self):
        self.sesije: list[KorisnickaSesija] = []

    def get_by_token_hash(self, token_hash: str) -> KorisnickaSesija | None:
        for s in self.sesije:
            if s.token_hash == token_hash:
                return s
        return None

    def revoke_active_sessions_for_user(self, korisnik_id: int, razlog: str) -> None:
        for s in self.sesije:
            if s.korisnik_id == korisnik_id and s.aktivna == "D":
                s.aktivna = "N"
                s.datum_ponistavanja = datetime.datetime.now()
                s.razlog_ponistavanja = razlog

    def create_session(
        self, korisnik_id, token_hash, uredjaj_id, naziv_uredjaja, ttl_days, ip_adresa, korisnicki_agent
    ) -> KorisnickaSesija:
        now = datetime.datetime.now()
        sesija = KorisnickaSesija(
            id=next(_id_counter),
            korisnik_id=korisnik_id,
            token_hash=token_hash,
            uredjaj_id=uredjaj_id,
            naziv_uredjaja=naziv_uredjaja,
            aktivna="D",
            datum_izdavanja=now,
            datum_isteka=now + datetime.timedelta(days=ttl_days),
            poslednja_aktivnost=now,
            ip_adresa=ip_adresa,
            korisnicki_agent=korisnicki_agent,
        )
        self.sesije.append(sesija)
        return sesija

    def revoke_session(self, sesija: KorisnickaSesija, razlog: str) -> None:
        sesija.aktivna = "N"
        sesija.datum_ponistavanja = datetime.datetime.now()
        sesija.razlog_ponistavanja = razlog

    def touch_activity(self, sesija: KorisnickaSesija) -> None:
        sesija.poslednja_aktivnost = datetime.datetime.now()

    def has_active_session_for_device(self, korisnik_id, uredjaj_id, now) -> bool:
        return any(
            s.korisnik_id == korisnik_id
            and s.uredjaj_id == uredjaj_id
            and s.aktivna == "D"
            and (s.datum_isteka is None or s.datum_isteka > now)
            for s in self.sesije
        )


class FakeResetPasswordRepository:
    def __init__(self):
        self.resets: list[ResetLozinke] = []

    def deactivate_active_for_user(self, korisnik_id: int) -> None:
        for r in self.resets:
            if r.korisnik_id == korisnik_id and r.aktivan == "D":
                r.aktivan = "N"

    def create(self, korisnik_id, kod_hash, ttl_minutes, ip_adresa) -> ResetLozinke:
        now = datetime.datetime.now()
        reset = ResetLozinke(
            id=next(_id_counter),
            korisnik_id=korisnik_id,
            kod_hash=kod_hash,
            aktivan="D",
            broj_pokusaja=0,
            datum_zahteva=now,
            datum_isteka=now + datetime.timedelta(minutes=ttl_minutes),
            ip_adresa=ip_adresa,
        )
        self.resets.append(reset)
        return reset

    def get_active_for_user(self, korisnik_id: int) -> ResetLozinke | None:
        active = [r for r in self.resets if r.korisnik_id == korisnik_id and r.aktivan == "D"]
        return active[-1] if active else None

    def increment_attempts(self, reset: ResetLozinke) -> None:
        reset.broj_pokusaja = (reset.broj_pokusaja or 0) + 1

    def mark_used(self, reset: ResetLozinke) -> None:
        reset.aktivan = "N"
        reset.datum_koriscenja = datetime.datetime.now()


class FakeConfigurationService:
    def __init__(self, values: dict[str, str] | None = None):
        self.values = values or {}

    def get_int(self, kljuc: str, default: int) -> int:
        return int(self.values.get(kljuc, default))

    def get_bool(self, kljuc: str, default: bool) -> bool:
        return bool(self.values.get(kljuc, default))

    def get_str(self, kljuc: str, default: str) -> str:
        return self.values.get(kljuc, default)


class FakeAuditService:
    def __init__(self):
        self.entries: list[dict] = []

    def log(self, sifra_akcije: str, **kwargs) -> None:
        self.entries.append({"sifra_akcije": sifra_akcije, **kwargs})


class FakePushTokenRepository:
    """In-memory PULS_PUSH_TOKENI. Cuva se hash umesto oslanjanja na pun token u logu."""

    def __init__(self):
        # ključ (korisnik_id, uredjaj_id) -> dict(token, hash, aktivan, app_version)
        self.tokens: dict[tuple[int, str], dict] = {}

    @staticmethod
    def _hash(token: str) -> str:
        import hashlib

        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def get_active_for_user(self, korisnik_id: int):
        for (kid, uredjaj_id), t in self.tokens.items():
            if kid == korisnik_id and t["aktivan"] == "D":
                return type("T", (), {"fcm_token": t["token"], "uredjaj_id": uredjaj_id, "korisnik_id": kid})()
        return None

    def upsert(self, korisnik_id, uredjaj_id, fcm_token, app_version):
        h = self._hash(fcm_token)
        for (kid, dev), t in self.tokens.items():
            if kid == korisnik_id and dev != uredjaj_id:
                t["aktivan"] = "N"
            if t["hash"] == h and kid != korisnik_id:
                t["aktivan"] = "N"
        self.tokens[(korisnik_id, uredjaj_id)] = {
            "token": fcm_token, "hash": h, "aktivan": "D", "app_version": app_version
        }
        return self.tokens[(korisnik_id, uredjaj_id)]

    def deactivate_user_device(self, korisnik_id, uredjaj_id):
        t = self.tokens.get((korisnik_id, uredjaj_id))
        if t and t["aktivan"] == "D":
            t["aktivan"] = "N"
            return 1
        return 0

    def deactivate_all_for_user(self, korisnik_id):
        n = 0
        for (kid, _dev), t in self.tokens.items():
            if kid == korisnik_id and t["aktivan"] == "D":
                t["aktivan"] = "N"
                n += 1
        return n

    def deactivate_token_hash(self, token_hash):
        n = 0
        for t in self.tokens.values():
            if t["hash"] == token_hash and t["aktivan"] == "D":
                t["aktivan"] = "N"
                n += 1
        return n


class FakeSmsProvider(SmsProvider):
    def __init__(self, should_succeed: bool = True):
        self.sent: list[tuple[str, str]] = []
        self.should_succeed = should_succeed

    def send_sms(self, phone_number: str, message: str) -> bool:
        self.sent.append((phone_number, message))
        return self.should_succeed


def make_ciklus(**overrides) -> IdeaCiklus:
    now = datetime.datetime.now()
    defaults = dict(
        id=next(_id_counter),
        naziv="Ideje - test ciklus",
        datum_pocetka=now - datetime.timedelta(days=1),
        datum_zavrsetka=now + datetime.timedelta(days=6),
        status="AKTIVAN",
        datum_kreiranja=now,
    )
    defaults.update(overrides)
    return IdeaCiklus(**defaults)


def make_ideja(**overrides) -> Ideja:
    now = datetime.datetime.now()
    defaults = dict(
        id=next(_id_counter),
        korisnik_id=1,
        ciklus_id=1,
        platni_broj="12345",
        ime_autora="Boro",
        prezime_autora="Radojcic",
        orgjed_sifra=None,
        naslov="Naslov",
        opis="Opis",
        status="POSLATA",
        hr_ocena=None,
        ai_ocena=None,
        konacna_ocena=None,
        datum_kreiranja=now,
    )
    defaults.update(overrides)
    return Ideja(**defaults)


class FakeIdeaKorisnikRepository(FakeKorisnikRepository):
    """Kao FakeKorisnikRepository, ali sa podesivim primarnim rasporedom po korisniku."""

    def __init__(self, korisnici=None, rasporedi: dict[int, str] | None = None):
        super().__init__(korisnici)
        self._rasporedi = rasporedi or {}

    def get_primary_active_raspored(self, korisnik_id: int):
        orgjed = self._rasporedi.get(korisnik_id)
        if orgjed is None:
            return None
        return KorisnikRaspored(id=next(_id_counter), korisnik_id=korisnik_id, orgjed_sifra=orgjed)


class FakeIdeaCycleRepository:
    def __init__(self, cycles: list[IdeaCiklus] | None = None):
        self.cycles: list[IdeaCiklus] = list(cycles or [])

    def add(self, ciklus: IdeaCiklus) -> None:
        self.cycles.append(ciklus)

    def get_by_id(self, ciklus_id: int) -> IdeaCiklus | None:
        return next((c for c in self.cycles if c.id == ciklus_id), None)

    def get_active_cycle(self) -> IdeaCiklus | None:
        return next((c for c in self.cycles if c.status == "AKTIVAN"), None)

    def get_active_cycle_for_update(self) -> IdeaCiklus | None:
        return self.get_active_cycle()

    def list_cycles(self) -> list[IdeaCiklus]:
        return sorted(self.cycles, key=lambda c: (c.datum_pocetka, c.id), reverse=True)

    def count_active_cycles(self) -> int:
        return sum(1 for c in self.cycles if c.status == "AKTIVAN")

    def create(self, naziv, datum_pocetka, datum_zavrsetka) -> IdeaCiklus:
        ciklus = IdeaCiklus(
            id=next(_id_counter),
            naziv=naziv,
            datum_pocetka=datum_pocetka,
            datum_zavrsetka=datum_zavrsetka,
            status="PLANIRAN",
            datum_kreiranja=datetime.datetime.now(),
        )
        self.cycles.append(ciklus)
        return ciklus


def _top_sort_key(ideja: Ideja):
    from decimal import Decimal

    return (
        ideja.konacna_ocena is None,
        -(ideja.konacna_ocena if ideja.konacna_ocena is not None else Decimal(0)),
        ideja.hr_ocena is None,
        -(ideja.hr_ocena if ideja.hr_ocena is not None else 0),
        ideja.datum_kreiranja,
        ideja.id,
    )


class FakeIdeaRepository:
    def __init__(self, ideje: list[Ideja] | None = None):
        self.ideje: list[Ideja] = list(ideje or [])

    def get_by_id(self, idea_id: int) -> Ideja | None:
        return next((i for i in self.ideje if i.id == idea_id), None)

    def count_user_ideas_in_cycle(self, korisnik_id: int, ciklus_id: int) -> int:
        return sum(
            1 for i in self.ideje if i.korisnik_id == korisnik_id and i.ciklus_id == ciklus_id
        )

    def create(
        self, korisnik_id, ciklus_id, platni_broj, ime_autora, prezime_autora, orgjed_sifra, naslov, opis
    ) -> Ideja:
        ideja = Ideja(
            id=next(_id_counter),
            korisnik_id=korisnik_id,
            ciklus_id=ciklus_id,
            platni_broj=platni_broj,
            ime_autora=ime_autora,
            prezime_autora=prezime_autora,
            orgjed_sifra=orgjed_sifra,
            naslov=naslov,
            opis=opis,
            status="POSLATA",
            datum_kreiranja=datetime.datetime.now(),
        )
        self.ideje.append(ideja)
        return ideja

    def list_by_user(self, korisnik_id: int, ciklus_id: int | None = None) -> list[Ideja]:
        items = [i for i in self.ideje if i.korisnik_id == korisnik_id]
        if ciklus_id is not None:
            items = [i for i in items if i.ciklus_id == ciklus_id]
        return sorted(items, key=lambda i: (i.datum_kreiranja, i.id), reverse=True)

    def list_top(self, ciklus_id: int, limit: int) -> list[Ideja]:
        items = [
            i for i in self.ideje if i.ciklus_id == ciklus_id and i.status in ("TOP_10", "NAGRAĐENA")
        ]
        return sorted(items, key=_top_sort_key)[:limit]

    def admin_list(self, ciklus_id, status, korisnik_id, platni_broj, page, page_size):
        items = list(self.ideje)
        if ciklus_id is not None:
            items = [i for i in items if i.ciklus_id == ciklus_id]
        if status is not None:
            items = [i for i in items if i.status == status]
        if korisnik_id is not None:
            items = [i for i in items if i.korisnik_id == korisnik_id]
        if platni_broj is not None:
            items = [i for i in items if i.platni_broj == platni_broj]
        total = len(items)
        items = sorted(items, key=lambda i: (i.datum_kreiranja, i.id), reverse=True)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

"""In-memory fake AdminUsersRepository (bez prave Oracle baze) - koristi se za
servisne testove modula ADMIN USERS."""

from app.repositories.korisnik_repository import RasporedWithNames


class FakeAdminUsersRepository:
    def __init__(self, korisnici=None, roles=None, rasporedi=None, orgjed_nazivi=None, rm_nazivi=None):
        self.korisnici = {k.id: k for k in (korisnici or [])}
        # sifra -> naziv (simulira IIS.ORGJED / IIS.RADNAMESTA; nepoznata sifra -> None)
        self.orgjed_nazivi: dict[str, str] = orgjed_nazivi or {}
        self.rm_nazivi: dict[str, str] = rm_nazivi or {}
        # korisnik_id -> [sifra, ...] aktivnih uloga
        self.roles: dict[int, list[str]] = roles or {}
        # korisnik_id -> [KorisnikRaspored, ...]
        self.rasporedi: dict[int, list] = rasporedi or {}
        self.for_update_calls: list[int] = []

    def get_by_id(self, user_id):
        return self.korisnici.get(user_id)

    def get_by_id_for_update(self, user_id):
        self.for_update_calls.append(user_id)
        return self.korisnici.get(user_id)

    def _primary(self, kid):
        candidates = [r for r in self.rasporedi.get(kid, []) if r.aktivan == "D"]
        if not candidates:
            return None
        candidates.sort(key=lambda r: (r.primarni != "D", r.id))
        return candidates[0]

    def list_users(self, search, status_zaposlenja, status_naloga, zakljucan, uloga, page, page_size, orgjed=None):
        items = list(self.korisnici.values())
        if search is not None:
            s = search.upper()
            items = [
                k
                for k in items
                if s in k.platni_broj.upper() or s in k.ime.upper() or s in k.prezime.upper()
            ]
        if status_zaposlenja is not None:
            items = [k for k in items if k.status_zaposlenja == status_zaposlenja]
        if status_naloga is not None:
            items = [k for k in items if k.status_naloga == status_naloga]
        if zakljucan is not None:
            wanted = "D" if zakljucan else "N"
            items = [k for k in items if k.zakljucan == wanted]
        if uloga is not None:
            items = [k for k in items if uloga in self.roles.get(k.id, [])]
        if orgjed:
            wanted_org = set(orgjed)
            items = [
                k for k in items if (p := self._primary(k.id)) is not None and p.orgjed_sifra in wanted_org
            ]
        items.sort(key=lambda k: k.id)
        total = len(items)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

    def batch_active_role_codes(self, korisnik_ids):
        ids = set(korisnik_ids)
        return {kid: list(codes) for kid, codes in self.roles.items() if kid in ids}

    def batch_primary_active_rasporedi(self, korisnik_ids):
        result = {}
        for kid in set(korisnik_ids):
            p = self._primary(kid)
            if p is not None:
                result[kid] = RasporedWithNames(
                    p.orgjed_sifra,
                    self.orgjed_nazivi.get(p.orgjed_sifra),
                    p.radno_mesto_sifra,
                    self.rm_nazivi.get(p.radno_mesto_sifra),
                )
        return result

    def list_orgjed(self):
        sifre = {r.orgjed_sifra for rs in self.rasporedi.values() for r in rs if r.aktivan == "D"}
        return sorted(((s, self.orgjed_nazivi.get(s)) for s in sifre), key=lambda x: (x[1] or "", x[0]))

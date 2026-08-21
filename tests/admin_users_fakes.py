"""In-memory fake AdminUsersRepository (bez prave Oracle baze) - koristi se za
servisne testove modula ADMIN USERS."""


class FakeAdminUsersRepository:
    def __init__(self, korisnici=None, roles=None, rasporedi=None):
        self.korisnici = {k.id: k for k in (korisnici or [])}
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

    def list_users(self, search, status_zaposlenja, status_naloga, zakljucan, uloga, page, page_size):
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
        items.sort(key=lambda k: k.id)
        total = len(items)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

    def batch_active_role_codes(self, korisnik_ids):
        ids = set(korisnik_ids)
        return {kid: list(codes) for kid, codes in self.roles.items() if kid in ids}

    def batch_primary_active_rasporedi(self, korisnik_ids):
        ids = set(korisnik_ids)
        result = {}
        for kid in ids:
            candidates = [r for r in self.rasporedi.get(kid, []) if r.aktivan == "D"]
            if not candidates:
                continue
            candidates.sort(key=lambda r: (r.primarni != "D", r.id))
            result[kid] = candidates[0]
        return result

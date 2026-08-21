"""In-memory fake AdminConfigurationRepository/ConfigurationRepository (bez prave
Oracle baze) - koriste se za servisne/HTTP testove modula ADMIN CONFIGURATION i
javnog GET /app/version endpointa."""


class FakeKonfiguracijaRow:
    def __init__(self, kljuc, vrednost, tip_podatka, opis, aktivna="D", izmenio_korisnik_id=None):
        self.kljuc = kljuc
        self.vrednost = vrednost
        self.tip_podatka = tip_podatka
        self.opis = opis
        self.aktivna = aktivna
        self.izmenio_korisnik_id = izmenio_korisnik_id


class FakeDb:
    """Stand-in SQLAlchemy Session: samo commit/rollback/add se koriste u servisu.

    `store` je deljeni dict sa FakeAdminConfigurationRepository - simulira da red
    dodat preko db.add() postane vidljiv narednom repo.get_for_update() pozivu,
    isto kao sto bi bio vidljiv u istoj transakciji nad pravom Oracle bazom."""

    def __init__(self, store: dict | None = None):
        self.committed = 0
        self.rolled_back = 0
        self.added: list = []
        self.store: dict = store if store is not None else {}

    def add(self, obj) -> None:
        self.added.append(obj)
        key = getattr(obj, "kljuc", None)
        if key is not None:
            self.store[key] = obj

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


class FakeAdminConfigurationRepository:
    def __init__(self, rows: list[FakeKonfiguracijaRow] | None = None, store: dict | None = None):
        self.rows: dict[str, FakeKonfiguracijaRow] = store if store is not None else {}
        for r in rows or []:
            self.rows[r.kljuc] = r
        self.for_update_calls: list[str] = []
        self.for_update_batch_calls: list[list[str]] = []

    def list_active_by_keys(self, keys: list[str]) -> dict[str, FakeKonfiguracijaRow]:
        return {k: r for k, r in self.rows.items() if k in keys and r.aktivna == "D"}

    def get_for_update(self, key: str) -> FakeKonfiguracijaRow | None:
        self.for_update_calls.append(key)
        return self.rows.get(key)

    def get_for_update_batch(self, keys: list[str]) -> dict[str, FakeKonfiguracijaRow]:
        self.for_update_batch_calls.append(list(keys))
        return {k: self.rows[k] for k in keys if k in self.rows}

    def get_active_value(self, key: str) -> str | None:
        row = self.rows.get(key)
        if row is not None and row.aktivna == "D":
            return row.vrednost
        return None


class FailingAdminConfigurationRepository(FakeAdminConfigurationRepository):
    """Simulira grešku PRI čuvanju (npr. na commit-u) - koristi se za rollback test."""

    def __init__(self, rows=None, fail_on="commit"):
        super().__init__(rows)
        self.fail_on = fail_on


class FakeConfigurationRepository:
    """Fake za app.repositories.configuration_repository.ConfigurationRepository -
    koristi se u AppVersionService testovima (samo get_values je bitan)."""

    def __init__(self, values: dict[str, str] | None = None):
        self.values = values or {}

    def get_value(self, kljuc: str) -> str | None:
        return self.values.get(kljuc)

    def get_values(self, kljucevi: list[str]) -> dict[str, str]:
        return {k: v for k, v in self.values.items() if k in kljucevi}

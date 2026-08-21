"""In-memory fake AdminDashboardRepository za servisne/HTTP testove modula ADMIN
DASHBOARD (bez prave Oracle baze)."""


class FakeAdminDashboardRepository:
    def __init__(
        self,
        korisnici: dict | None = None,
        ankete: dict | None = None,
        ideje: dict | None = None,
        obavestenja: dict | None = None,
    ):
        self._korisnici = korisnici or {
            "aktivni": 0,
            "neaktivni": 0,
            "aktivirali_aplikaciju": 0,
            "zakljucani": 0,
        }
        self._ankete = ankete or {
            "aktivne": 0,
            "zavrsene": 0,
            "broj_primalaca": 0,
            "broj_predaja": 0,
            "procenat_odziva": 0.0,
        }
        self._ideje = ideje or {
            "nove": 0,
            "u_obradi": 0,
            "odobrene": 0,
            "odbijene": 0,
            "top_10": 0,
            "nagradjene": 0,
        }
        self._obavestenja = obavestenja or {
            "objavljena": 0,
            "broj_primalaca": 0,
            "procitane": 0,
            "neprocitane": 0,
            "push_pending": 0,
            "push_sent": 0,
            "push_failed": 0,
            "push_skipped": 0,
        }

    def korisnici_counts(self) -> dict:
        return dict(self._korisnici)

    def ankete_counts(self) -> dict:
        return dict(self._ankete)

    def ideje_counts(self) -> dict:
        return dict(self._ideje)

    def obavestenja_counts(self) -> dict:
        return dict(self._obavestenja)

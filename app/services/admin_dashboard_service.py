"""Admin DASHBOARD modul: samo citanje, bez transakcione granice (nema commit-a),
bez audit loga za sam pregled dashboard-a."""

from sqlalchemy.orm import Session

from app.repositories.admin_dashboard_repository import AdminDashboardRepository


class AdminDashboardService:
    def __init__(self, db: Session, repository: AdminDashboardRepository | None = None):
        self.db = db
        self.repo = repository or AdminDashboardRepository(db)

    def get_dashboard(self) -> dict:
        return {
            "korisnici": self.repo.korisnici_counts(),
            "ankete": self.repo.ankete_counts(),
            "ideje": self.repo.ideje_counts(),
            "obavestenja": self.repo.obavestenja_counts(),
        }

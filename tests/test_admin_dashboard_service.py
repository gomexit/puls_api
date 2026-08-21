"""Servisni testovi za AdminDashboardService (fake repository, bez DB)."""

from app.services.admin_dashboard_service import AdminDashboardService
from tests.admin_dashboard_fakes import FakeAdminDashboardRepository


def test_get_dashboard_zero_data():
    service = AdminDashboardService(db=None, repository=FakeAdminDashboardRepository())
    result = service.get_dashboard()
    assert result["korisnici"] == {
        "aktivni": 0,
        "neaktivni": 0,
        "aktivirali_aplikaciju": 0,
        "zakljucani": 0,
    }
    assert result["ankete"]["procenat_odziva"] == 0.0
    assert result["ideje"]["nagradjene"] == 0
    assert result["obavestenja"]["push_sent"] == 0


def test_get_dashboard_all_counters():
    repo = FakeAdminDashboardRepository(
        korisnici={"aktivni": 10, "neaktivni": 2, "aktivirali_aplikaciju": 8, "zakljucani": 1},
        ankete={
            "aktivne": 3,
            "zavrsene": 5,
            "broj_primalaca": 100,
            "broj_predaja": 40,
            "procenat_odziva": 40.0,
        },
        ideje={
            "nove": 7,
            "u_obradi": 4,
            "odobrene": 2,
            "odbijene": 1,
            "top_10": 3,
            "nagradjene": 1,
        },
        obavestenja={
            "objavljena": 6,
            "broj_primalaca": 60,
            "procitane": 40,
            "neprocitane": 20,
            "push_pending": 1,
            "push_sent": 55,
            "push_failed": 2,
            "push_skipped": 2,
        },
    )
    service = AdminDashboardService(db=None, repository=repo)
    result = service.get_dashboard()
    assert result["korisnici"]["aktivni"] == 10
    assert result["korisnici"]["zakljucani"] == 1
    assert result["ankete"]["broj_predaja"] == 40
    assert result["ideje"]["nagradjene"] == 1
    assert result["obavestenja"]["push_sent"] == 55


def test_procenat_odziva_rounding_and_zero_division():
    repo = FakeAdminDashboardRepository(
        ankete={
            "aktivne": 0,
            "zavrsene": 0,
            "broj_primalaca": 3,
            "broj_predaja": 1,
            "procenat_odziva": round(1 / 3 * 100, 2),
        }
    )
    service = AdminDashboardService(db=None, repository=repo)
    result = service.get_dashboard()
    assert result["ankete"]["procenat_odziva"] == 33.33

    repo_zero = FakeAdminDashboardRepository(
        ankete={
            "aktivne": 0,
            "zavrsene": 0,
            "broj_primalaca": 0,
            "broj_predaja": 0,
            "procenat_odziva": 0.0,
        }
    )
    service_zero = AdminDashboardService(db=None, repository=repo_zero)
    assert service_zero.get_dashboard()["ankete"]["procenat_odziva"] == 0.0


def test_unicode_nagradjena_status_preserved():
    repo = FakeAdminDashboardRepository(ideje={
        "nove": 0,
        "u_obradi": 0,
        "odobrene": 0,
        "odbijene": 0,
        "top_10": 0,
        "nagradjene": 5,
    })
    service = AdminDashboardService(db=None, repository=repo)
    result = service.get_dashboard()
    assert result["ideje"]["nagradjene"] == 5

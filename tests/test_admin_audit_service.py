"""Servisni testovi za AdminAuditService (fake repository, bez DB)."""

import datetime

import pytest

from app.core.exceptions import AuditLogNotFoundError
from app.services.admin_audit_service import AdminAuditService
from tests.admin_audit_fakes import FakeAdminAuditRepository, FakeAuditLog


def _service(logs=None):
    return AdminAuditService(db=None, repository=FakeAdminAuditRepository(logs))


def test_list_logs_pagination():
    logs = [FakeAuditLog(id=i, datum_kreiranja=datetime.datetime(2026, 1, i)) for i in range(1, 6)]
    service = _service(logs)
    result = service.list_logs(1, 2, None, None, None, None, None, None, None)
    assert result["total"] == 5
    assert len(result["items"]) == 2
    assert result["has_more"] is True

    result_last = service.list_logs(3, 2, None, None, None, None, None, None, None)
    assert len(result_last["items"]) == 1
    assert result_last["has_more"] is False


def test_list_logs_sorted_by_datum_desc_then_id_desc():
    logs = [
        FakeAuditLog(id=1, datum_kreiranja=datetime.datetime(2026, 1, 1)),
        FakeAuditLog(id=2, datum_kreiranja=datetime.datetime(2026, 1, 2)),
        FakeAuditLog(id=3, datum_kreiranja=datetime.datetime(2026, 1, 2)),
    ]
    service = _service(logs)
    result = service.list_logs(1, 20, None, None, None, None, None, None, None)
    ids = [item["id"] for item in result["items"]]
    assert ids == [3, 2, 1]


def test_list_logs_filters():
    logs = [
        FakeAuditLog(id=1, platni_broj="111", sifra_akcije="LOGIN", izvor="PORTAL"),
        FakeAuditLog(id=2, platni_broj="222", sifra_akcije="LOGOUT", izvor="APP"),
    ]
    service = _service(logs)
    result = service.list_logs(1, 20, "111", None, None, None, None, None, None)
    assert result["total"] == 1
    assert result["items"][0]["id"] == 1

    result2 = service.list_logs(1, 20, None, "LOGOUT", None, None, None, None, None)
    assert result2["total"] == 1
    assert result2["items"][0]["id"] == 2

    result3 = service.list_logs(1, 20, None, None, None, None, "APP", None, None)
    assert result3["total"] == 1
    assert result3["items"][0]["id"] == 2


def test_list_logs_datetime_range_filter():
    logs = [
        FakeAuditLog(id=1, datum_kreiranja=datetime.datetime(2026, 1, 1)),
        FakeAuditLog(id=2, datum_kreiranja=datetime.datetime(2026, 1, 15)),
        FakeAuditLog(id=3, datum_kreiranja=datetime.datetime(2026, 1, 31)),
    ]
    service = _service(logs)
    result = service.list_logs(
        1, 20, None, None, None, None, None,
        datetime.datetime(2026, 1, 5), datetime.datetime(2026, 1, 20),
    )
    assert result["total"] == 1
    assert result["items"][0]["id"] == 2


def test_list_logs_does_not_expose_detalji_ip_or_agent():
    logs = [FakeAuditLog(id=1, detalji="tajni detalj", ip_adresa="1.2.3.4", korisnicki_agent="curl/1")]
    service = _service(logs)
    result = service.list_logs(1, 20, None, None, None, None, None, None, None)
    item = result["items"][0]
    assert "detalji" not in item
    assert "ip_adresa" not in item
    assert "korisnicki_agent" not in item


def test_get_log_detail_includes_full_data():
    logs = [
        FakeAuditLog(
            id=1,
            detalji="detalj json",
            ip_adresa="10.0.0.1",
            korisnicki_agent="Mozilla/5.0",
        )
    ]
    service = _service(logs)
    result = service.get_log(1)
    assert result["detalji"] == "detalj json"
    assert result["ip_adresa"] == "10.0.0.1"
    assert result["korisnicki_agent"] == "Mozilla/5.0"


def test_get_log_not_found_raises():
    service = _service([])
    with pytest.raises(AuditLogNotFoundError):
        service.get_log(999)

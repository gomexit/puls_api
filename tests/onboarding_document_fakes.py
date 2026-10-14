"""Fake-ovi za modul ONBOARDING DOKUMENTI (bez Oracle konekcije). PDF fixture-i se
generisu u memoriji pomocu pypdf - nikakvi pravi poslovni PDF fajlovi nisu u repou."""

import datetime
import io
import itertools

from pypdf import PdfWriter

from app.models.onboarding_dokument import OnboardingDokument
from app.services.onboarding_pdf import validate_pdf_upload

_id_counter = itertools.count(1)
FIXED_NOW = datetime.datetime(2026, 10, 14, 9, 0, 0)


def make_pdf_bytes(pages: int = 1, password: str | None = None, width: int = 200) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=200)
    if password:
        writer.encrypt(password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def make_validated_pdf(name: str = "pravilnik.pdf", pages: int = 1, width: int = 200):
    return validate_pdf_upload(make_pdf_bytes(pages, width=width), name, "application/pdf")


def make_dokument(**overrides) -> OnboardingDokument:
    pdf = make_validated_pdf()
    defaults = dict(
        id=next(_id_counter),
        naziv="Pravilnik za nove zaposlene",
        opis="Osnovne informacije",
        originalni_naziv_fajla=pdf.original_name,
        mime_tip="application/pdf",
        velicina_bajtova=pdf.size,
        sha256=pdf.sha256,
        sadrzaj=pdf.content,
        status="DRAFT",
        redosled=1,
        verzija=1,
        kreirao_platni_broj="admin1",
        izmenio_platni_broj="admin1",
        datum_kreiranja=FIXED_NOW,
        datum_izmene=FIXED_NOW,
        datum_objave=None,
    )
    defaults.update(overrides)
    if defaults["status"] == "PUBLISHED" and defaults["datum_objave"] is None:
        defaults["datum_objave"] = FIXED_NOW
    return OnboardingDokument(**defaults)


class FakeOnbDb:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0
        self.fail_flush = False

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def flush(self) -> None:
        if self.fail_flush:
            raise RuntimeError("flush pukao")
        self.flushed += 1


class FakeOnboardingDocumentRepo:
    """Vraca ORM entitete (imaju sva polja koja servis cita). `queries_after_commit`
    broji pristupe repozitorijumu posle commit-a (mora ostati 0)."""

    def __init__(self, db: FakeOnbDb | None = None):
        self.db = db
        self.docs: dict[int, OnboardingDokument] = {}
        self.queries_after_commit = 0
        self.for_update_calls = 0
        self.added: list[OnboardingDokument] = []

    # --- test helpers ---
    def seed(self, dok: OnboardingDokument) -> OnboardingDokument:
        self.docs[int(dok.id)] = dok
        return dok

    def _touch(self) -> None:
        if self.db is not None and self.db.committed > 0:
            self.queries_after_commit += 1

    def _sorted(self, docs):
        return sorted(docs, key=lambda d: (int(d.redosled), int(d.id)))

    # --- employee ---
    def list_published(self):
        self._touch()
        return self._sorted(d for d in self.docs.values() if d.status == "PUBLISHED")

    def get_published(self, document_id):
        self._touch()
        d = self.docs.get(document_id)
        return d if d is not None and d.status == "PUBLISHED" else None

    def get_published_content(self, document_id):
        return self.get_published(document_id)

    # --- admin ---
    def list_admin(self, status, search, page, page_size):
        self._touch()
        docs = list(self.docs.values())
        if status is not None:
            docs = [d for d in docs if d.status == status]
        if search:
            docs = [d for d in docs if search.lower() in d.naziv.lower()]
        docs = self._sorted(docs)
        start = (page - 1) * page_size
        return docs[start : start + page_size], len(docs)

    def get_admin(self, document_id):
        self._touch()
        return self.docs.get(document_id)

    def get_admin_content(self, document_id):
        return self.get_admin(document_id)

    # --- write ---
    def get_for_update(self, document_id):
        self._touch()
        self.for_update_calls += 1
        return self.docs.get(document_id)

    def add(self, dok):
        self._touch()
        if dok.id is None:
            dok.id = next(_id_counter)
        self.added.append(dok)
        self.docs[int(dok.id)] = dok
        return dok

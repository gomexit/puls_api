"""Fake-ovi za modul SLIKE (bez Oracle konekcije). Slike se generisu u memoriji (Pillow)."""

import datetime
import io
import itertools

from PIL import Image

from app.models.slika import Slika
from app.services.image_processing import process_image_upload

_id_counter = itertools.count(1000)
FIXED_NOW = datetime.datetime(2026, 11, 19, 9, 0, 0)


def make_image_bytes(fmt: str = "JPEG", size=(100, 80), color=(200, 30, 30), exif: bytes | None = None) -> bytes:
    mode = "RGBA" if fmt == "PNG" else "RGB"
    fill = color + (255,) if mode == "RGBA" else color
    img = Image.new(mode, size, fill)
    buf = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def make_processed(name: str = "logo.jpg", fmt: str = "JPEG", size=(100, 80)):
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return process_image_upload(make_image_bytes(fmt, size), name, mime)


def make_slika(**overrides) -> Slika:
    img = make_processed()
    defaults = dict(
        id=next(_id_counter),
        naziv="Logo partnera",
        originalni_naziv_fajla=img.original_name,
        mime_tip=img.mime_type,
        velicina_bajtova=img.size,
        sirina=img.width,
        visina=img.height,
        sha256=img.sha256,
        sadrzaj=img.content,
        status="AKTIVNA",
        kreirao_platni_broj="admin1",
        izmenio_platni_broj="admin1",
        datum_kreiranja=FIXED_NOW,
        datum_izmene=FIXED_NOW,
    )
    defaults.update(overrides)
    return Slika(**defaults)


class FakeImageDb:
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


class FakeImageRepo:
    def __init__(self, db: FakeImageDb | None = None):
        self.db = db
        self.images: dict[int, Slika] = {}
        self.content_reads = 0
        self.etag_reads = 0

    def seed(self, slika: Slika) -> Slika:
        self.images[int(slika.id)] = slika
        return slika

    def get_active_content(self, image_id):
        self.content_reads += 1
        s = self.images.get(image_id)
        return s if s is not None and s.status == "AKTIVNA" else None

    def get_active_etag(self, image_id):
        self.etag_reads += 1
        s = self.images.get(image_id)
        return s.sha256 if s is not None and s.status == "AKTIVNA" else None

    def list_admin(self, status, search, page, page_size, sort=None):
        items = list(self.images.values())
        if status is not None:
            items = [s for s in items if s.status == status]
        if search:
            items = [s for s in items if search.lower() in s.naziv.lower()]
        items.sort(key=lambda s: int(s.id), reverse=True)
        start = (page - 1) * page_size
        return items[start : start + page_size], len(items)

    def get_admin(self, image_id):
        return self.images.get(image_id)

    def get_admin_content(self, image_id):
        return self.images.get(image_id)

    def get_for_update(self, image_id):
        return self.images.get(image_id)

    def add(self, slika):
        if slika.id is None:
            slika.id = next(_id_counter)
        self.images[int(slika.id)] = slika
        return slika

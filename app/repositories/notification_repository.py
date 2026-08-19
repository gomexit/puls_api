import datetime

from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.orm import Session

from app.models.anketa import Anketa
from app.models.ideja import Ideja
from app.models.obavestenje import (
    OBAVESTENJE_STATUS_PUBLISHED,
    Obavestenje,
    ObavestenjeCilj,
    ObavestenjeKategorija,
    ObavestenjePrimalac,
)

# Read-status filter za Inbox.
READ_STATUS_ALL = "ALL"
READ_STATUS_READ = "READ"
READ_STATUS_UNREAD = "UNREAD"


def _available_condition(now: datetime.datetime):
    """SQL ogledalo Obavestenje.is_available_to_employees: PUBLISHED, objava nije u
    buducnosti, istek nije prosao. Drzati sinhrono sa modelom."""
    return and_(
        Obavestenje.status == OBAVESTENJE_STATUS_PUBLISHED,
        Obavestenje.datum_objave.is_not(None),
        Obavestenje.datum_objave <= now,
        Obavestenje.datum_isteka.is_not(None),
        Obavestenje.datum_isteka > now,
    )


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------- Inbox (read)
    def _inbox_base(self, korisnik_id: int, now: datetime.datetime, read_status: str, category: str | None):
        # JOIN primalac+obavestenje(+kategorija) da izbegnemo N+1 za kategoriju/read stanje.
        stmt = (
            select(Obavestenje, ObavestenjePrimalac, ObavestenjeKategorija)
            .join(ObavestenjePrimalac, ObavestenjePrimalac.obavestenje_id == Obavestenje.id)
            .join(ObavestenjeKategorija, ObavestenjeKategorija.sifra == Obavestenje.kategorija_sifra)
            .where(ObavestenjePrimalac.korisnik_id == korisnik_id, _available_condition(now))
        )
        if read_status == READ_STATUS_READ:
            stmt = stmt.where(ObavestenjePrimalac.procitano == "D")
        elif read_status == READ_STATUS_UNREAD:
            stmt = stmt.where(ObavestenjePrimalac.procitano == "N")
        if category is not None:
            stmt = stmt.where(Obavestenje.kategorija_sifra == category)
        return stmt

    def list_inbox(
        self,
        korisnik_id: int,
        now: datetime.datetime,
        read_status: str,
        category: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[Obavestenje, ObavestenjePrimalac, ObavestenjeKategorija]], int]:
        stmt = self._inbox_base(korisnik_id, now, read_status, category)
        total = int(
            self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        )
        rows = self.db.execute(
            stmt.order_by(Obavestenje.datum_objave.desc(), Obavestenje.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [(r[0], r[1], r[2]) for r in rows], total

    def count_unread(self, korisnik_id: int, now: datetime.datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(ObavestenjePrimalac)
            .join(Obavestenje, Obavestenje.id == ObavestenjePrimalac.obavestenje_id)
            .where(
                ObavestenjePrimalac.korisnik_id == korisnik_id,
                ObavestenjePrimalac.procitano == "N",
                _available_condition(now),
            )
        )
        return int(self.db.execute(stmt).scalar_one())

    def get_inbox_item(
        self, korisnik_id: int, notification_id: int, now: datetime.datetime
    ) -> tuple[Obavestenje, ObavestenjePrimalac, ObavestenjeKategorija] | None:
        stmt = (
            select(Obavestenje, ObavestenjePrimalac, ObavestenjeKategorija)
            .join(ObavestenjePrimalac, ObavestenjePrimalac.obavestenje_id == Obavestenje.id)
            .join(ObavestenjeKategorija, ObavestenjeKategorija.sifra == Obavestenje.kategorija_sifra)
            .where(
                Obavestenje.id == notification_id,
                ObavestenjePrimalac.korisnik_id == korisnik_id,
                _available_condition(now),
            )
        )
        row = self.db.execute(stmt).first()
        return (row[0], row[1], row[2]) if row is not None else None

    def get_available_notification(
        self, notification_id: int, now: datetime.datetime
    ) -> Obavestenje | None:
        stmt = select(Obavestenje).where(
            Obavestenje.id == notification_id, _available_condition(now)
        )
        return self.db.execute(stmt).scalars().first()

    def get_recipient_for_update(
        self, notification_id: int, korisnik_id: int
    ) -> ObavestenjePrimalac | None:
        # SELECT ... FOR UPDATE: bezbedno read/unread pri paralelnim pozivima.
        stmt = (
            select(ObavestenjePrimalac)
            .where(
                ObavestenjePrimalac.obavestenje_id == notification_id,
                ObavestenjePrimalac.korisnik_id == korisnik_id,
            )
            .with_for_update()
        )
        return self.db.execute(stmt).scalars().first()

    # --------------------------------------------------------------- Kategorije
    def get_category(self, sifra: str) -> ObavestenjeKategorija | None:
        return self.db.get(ObavestenjeKategorija, sifra)

    def list_categories(self, aktivna: bool | None = None) -> list[ObavestenjeKategorija]:
        stmt = select(ObavestenjeKategorija)
        if aktivna is not None:
            stmt = stmt.where(ObavestenjeKategorija.aktivna == ("D" if aktivna else "N"))
        # REDOSLED ASC (NULL poslednje), pa SIFRA ASC kao stabilan tie-break.
        stmt = stmt.order_by(
            ObavestenjeKategorija.redosled.asc().nulls_last(),
            ObavestenjeKategorija.sifra.asc(),
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_category(self, kategorija: ObavestenjeKategorija) -> ObavestenjeKategorija:
        self.db.add(kategorija)
        self.db.flush()
        return kategorija

    # -------------------------------------------------------- Resurs (SURVEY/IDEA)
    def survey_exists(self, survey_id: int) -> bool:
        return self.db.execute(
            select(func.count()).select_from(Anketa).where(Anketa.id == survey_id)
        ).scalar_one() > 0

    def idea_exists(self, idea_id: int) -> bool:
        return self.db.execute(
            select(func.count()).select_from(Ideja).where(Ideja.id == idea_id)
        ).scalar_one() > 0

    # ------------------------------------------------------------ Admin (citanje)
    def _recipient_counts_subquery(self):
        return (
            select(
                ObavestenjePrimalac.obavestenje_id.label("oid"),
                func.count().label("ukupno"),
                func.sum(case((ObavestenjePrimalac.procitano == "D", 1), else_=0)).label(
                    "procitano"
                ),
            )
            .group_by(ObavestenjePrimalac.obavestenje_id)
            .subquery()
        )

    def admin_list(
        self,
        status: str | None,
        category: str | None,
        datum_od: datetime.datetime | None,
        datum_do: datetime.datetime | None,
        page: int,
        page_size: int,
    ):
        # Namerno selektujemo pojedinacne kolone (BEZ NCLOB SADRZAJ) + agregatne
        # brojeve preko LEFT JOIN subquery-ja (jedan upit, bez N+1).
        rc = self._recipient_counts_subquery()
        base = (
            select(
                Obavestenje.id.label("id"),
                Obavestenje.kategorija_sifra.label("kategorija_sifra"),
                ObavestenjeKategorija.naziv.label("kategorija_naziv"),
                Obavestenje.naslov.label("naslov"),
                Obavestenje.kratak_tekst.label("kratak_tekst"),
                Obavestenje.status.label("status"),
                Obavestenje.akcija_tip.label("akcija_tip"),
                Obavestenje.resurs_id.label("resurs_id"),
                Obavestenje.akcija_url.label("akcija_url"),
                Obavestenje.kreirao_platni_broj.label("kreirao_platni_broj"),
                Obavestenje.datum_objave.label("datum_objave"),
                Obavestenje.datum_isteka.label("datum_isteka"),
                Obavestenje.datum_kreiranja.label("datum_kreiranja"),
                Obavestenje.datum_izmene.label("datum_izmene"),
                func.coalesce(rc.c.ukupno, 0).label("broj_primalaca"),
                func.coalesce(rc.c.procitano, 0).label("broj_procitanih"),
            )
            .join(ObavestenjeKategorija, ObavestenjeKategorija.sifra == Obavestenje.kategorija_sifra)
            .outerjoin(rc, rc.c.oid == Obavestenje.id)
        )
        if status is not None:
            base = base.where(Obavestenje.status == status)
        if category is not None:
            base = base.where(Obavestenje.kategorija_sifra == category)
        if datum_od is not None:
            base = base.where(Obavestenje.datum_kreiranja >= datum_od)
        if datum_do is not None:
            base = base.where(Obavestenje.datum_kreiranja <= datum_do)

        total = int(self.db.execute(select(func.count()).select_from(base.subquery())).scalar_one())
        rows = self.db.execute(
            base.order_by(Obavestenje.datum_kreiranja.desc(), Obavestenje.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(rows), total

    def recipient_counts(self, notification_id: int) -> tuple[int, int]:
        row = self.db.execute(
            select(
                func.count().label("ukupno"),
                func.coalesce(
                    func.sum(case((ObavestenjePrimalac.procitano == "D", 1), else_=0)), 0
                ).label("procitano"),
            ).where(ObavestenjePrimalac.obavestenje_id == notification_id)
        ).one()
        return int(row.ukupno), int(row.procitano)

    # ------------------------------------------------------------- Publishing (write)
    def delete_targets(self, notification_id: int) -> None:
        self.db.execute(
            delete(ObavestenjeCilj).where(ObavestenjeCilj.obavestenje_id == notification_id)
        )

    def get_notification(self, notification_id: int) -> Obavestenje | None:
        return self.db.get(Obavestenje, notification_id)

    def get_notification_for_update(self, notification_id: int) -> Obavestenje | None:
        stmt = select(Obavestenje).where(Obavestenje.id == notification_id).with_for_update()
        return self.db.execute(stmt).scalars().first()

    def add_notification(self, obavestenje: Obavestenje) -> Obavestenje:
        self.db.add(obavestenje)
        self.db.flush()
        return obavestenje

    def add_target(self, cilj: ObavestenjeCilj) -> ObavestenjeCilj:
        self.db.add(cilj)
        self.db.flush()
        return cilj

    def get_targets(self, notification_id: int) -> list[ObavestenjeCilj]:
        stmt = (
            select(ObavestenjeCilj)
            .where(ObavestenjeCilj.obavestenje_id == notification_id)
            .order_by(ObavestenjeCilj.id)
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_recipient(self, primalac: ObavestenjePrimalac) -> ObavestenjePrimalac:
        self.db.add(primalac)
        return primalac

    def existing_recipient_ids(self, notification_id: int) -> set[int]:
        stmt = select(ObavestenjePrimalac.korisnik_id).where(
            ObavestenjePrimalac.obavestenje_id == notification_id
        )
        return set(self.db.execute(stmt).scalars().all())

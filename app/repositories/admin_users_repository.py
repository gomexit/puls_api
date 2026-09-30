from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.models.iis_orgjed import IisOrgjed
from app.models.iis_radno_mesto import IisRadnoMesto
from app.models.korisnik import Korisnik
from app.models.korisnik_raspored import KorisnikRaspored
from app.models.korisnik_uloga import KorisnikUloga
from app.models.uloga import Uloga
from app.repositories.korisnik_repository import RasporedWithNames


def _primary_raspored_id(raspored_alias):
    """ID primarnog aktivnog rasporeda korisnika iz `raspored_alias` reda - isti prioritet
    kao batch_primary_active_rasporedi (PRIMARNI='D' pa najmanji ID). COALESCE dve MIN
    podupita umesto ORDER BY + FETCH FIRST: korelacija je samo jedan nivo duboka, pa je
    bezbedna na Oracle-u."""
    r_primarni = aliased(KorisnikRaspored)
    r_bilo_koji = aliased(KorisnikRaspored)
    min_primarni = (
        select(func.min(r_primarni.id))
        .where(
            r_primarni.korisnik_id == raspored_alias.korisnik_id,
            r_primarni.aktivan == "D",
            r_primarni.primarni == "D",
        )
        .scalar_subquery()
    )
    min_bilo_koji = (
        select(func.min(r_bilo_koji.id))
        .where(r_bilo_koji.korisnik_id == raspored_alias.korisnik_id, r_bilo_koji.aktivan == "D")
        .scalar_subquery()
    )
    return func.coalesce(min_primarni, min_bilo_koji)


class AdminUsersRepository:
    """Read/write pristup PULS_KORISNICI za admin USERS modul. Nikada ne selektuje
    LOZINKA_HASH u listi/detalju odgovora (samo za internu proveru/izmenu)."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> Korisnik | None:
        return self.db.get(Korisnik, user_id)

    def get_by_id_for_update(self, user_id: int) -> Korisnik | None:
        stmt = select(Korisnik).where(Korisnik.id == user_id).with_for_update()
        return self.db.execute(stmt).scalars().first()

    def list_users(
        self,
        search: str | None,
        status_zaposlenja: str | None,
        status_naloga: str | None,
        zakljucan: bool | None,
        uloga: str | None,
        page: int,
        page_size: int,
        orgjed: list[str] | None = None,
    ) -> tuple[list[Korisnik], int]:
        stmt = select(Korisnik)
        if search is not None:
            pattern = f"%{search.upper()}%"
            stmt = stmt.where(
                func.upper(Korisnik.platni_broj).like(pattern)
                | func.upper(Korisnik.ime).like(pattern)
                | func.upper(Korisnik.prezime).like(pattern)
            )
        if status_zaposlenja is not None:
            stmt = stmt.where(Korisnik.status_zaposlenja == status_zaposlenja)
        if status_naloga is not None:
            stmt = stmt.where(Korisnik.status_naloga == status_naloga)
        if zakljucan is not None:
            stmt = stmt.where(Korisnik.zakljucan == ("D" if zakljucan else "N"))
        if uloga is not None:
            stmt = stmt.where(
                exists(
                    select(1)
                    .select_from(KorisnikUloga)
                    .join(Uloga, Uloga.id == KorisnikUloga.uloga_id)
                    .where(
                        KorisnikUloga.korisnik_id == Korisnik.id,
                        Uloga.sifra == uloga,
                        Uloga.aktivna == "D",
                    )
                )
            )
        if orgjed:
            # Filtrira po PRIMARNOJ aktivnoj org. jedinici - istoj koja se prikazuje u listi.
            r = aliased(KorisnikRaspored)
            stmt = stmt.where(
                Korisnik.id.in_(
                    select(r.korisnik_id).where(
                        r.aktivan == "D",
                        r.orgjed_sifra.in_(orgjed),
                        r.id == _primary_raspored_id(r),
                    )
                )
            )

        total = int(self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
        rows = self.db.execute(
            stmt.order_by(Korisnik.id).offset((page - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def batch_active_role_codes(self, korisnik_ids: list[int]) -> dict[int, list[str]]:
        """Jedan upit za celu stranicu (izbegava N+1)."""
        if not korisnik_ids:
            return {}
        stmt = (
            select(KorisnikUloga.korisnik_id, Uloga.sifra)
            .join(Uloga, Uloga.id == KorisnikUloga.uloga_id)
            .where(KorisnikUloga.korisnik_id.in_(korisnik_ids), Uloga.aktivna == "D")
        )
        result: dict[int, list[str]] = {}
        for kid, sifra in self.db.execute(stmt).all():
            result.setdefault(int(kid), []).append(sifra)
        return result

    def batch_primary_active_rasporedi(self, korisnik_ids: list[int]) -> dict[int, RasporedWithNames]:
        """Batch verzija KorisnikRepository.get_primary_active_raspored_with_names - jedan
        upit za celu stranicu, sa nazivima iz IIS sifrarnika (LEFT JOIN, kao /auth/me).
        CASE prioritet PRIMARNI='D' + ID kao stabilan tie-breaker (primarni.desc() bi
        pogresno stavilo 'N' ispred 'D'). RADNO_MESTO_SIFRA je VARCHAR2 u PULS-u a NUMBER
        u IIS-u - poredi se preko TO_CHAR nad IIS stranom (izbegava ORA-01722)."""
        if not korisnik_ids:
            return {}
        primarni_prioritet = case((KorisnikRaspored.primarni == "D", 0), else_=1)
        stmt = (
            select(
                KorisnikRaspored.korisnik_id,
                KorisnikRaspored.orgjed_sifra,
                IisOrgjed.naziv,
                KorisnikRaspored.radno_mesto_sifra,
                IisRadnoMesto.naziv,
            )
            .outerjoin(IisOrgjed, IisOrgjed.sifra == KorisnikRaspored.orgjed_sifra)
            .outerjoin(
                IisRadnoMesto,
                func.to_char(IisRadnoMesto.sifra) == KorisnikRaspored.radno_mesto_sifra,
            )
            .where(KorisnikRaspored.korisnik_id.in_(korisnik_ids), KorisnikRaspored.aktivan == "D")
            .order_by(KorisnikRaspored.korisnik_id, primarni_prioritet, KorisnikRaspored.id)
        )
        result: dict[int, RasporedWithNames] = {}
        for kid, orgjed, orgjed_naziv, rm, rm_naziv in self.db.execute(stmt).all():
            result.setdefault(int(kid), RasporedWithNames(orgjed, orgjed_naziv, rm, rm_naziv))
        return result

    def list_orgjed(self) -> list[tuple[str, str | None]]:
        """Org. jedinice koje stvarno imaju korisnike (aktivan raspored), sa nazivom iz
        IIS sifrarnika - za izbor u filteru admin liste, bez praznih jedinica."""
        stmt = (
            select(KorisnikRaspored.orgjed_sifra, IisOrgjed.naziv)
            .outerjoin(IisOrgjed, IisOrgjed.sifra == KorisnikRaspored.orgjed_sifra)
            .where(KorisnikRaspored.aktivan == "D")
            .distinct()
            .order_by(IisOrgjed.naziv, KorisnikRaspored.orgjed_sifra)
        )
        return [(sifra, naziv) for sifra, naziv in self.db.execute(stmt).all()]

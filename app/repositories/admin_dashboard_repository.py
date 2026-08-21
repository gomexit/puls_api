"""Read-only agregati za admin DASHBOARD. Svaki domen (korisnici/ankete/ideje/
obavestenja) je TACNO jedan SQL upit - kad domen obuhvata vise tabela (ankete,
obavestenja), agregati se spajaju preko skalarnih pod-upita u SELECT listi (Oracle
kompajlira ovo sa "FROM DUAL"), umesto vise odvojenih round-trip-ova."""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.anketa import (
    ANKETA_STATUS_ACTIVE,
    ANKETA_STATUS_ARCHIVED,
    ANKETA_STATUS_CLOSED,
    UCESCE_SUBMITTED,
    Anketa,
)
from app.models.anketa_ucesce import AnketaUcesce
from app.models.ideja import (
    IDEJA_STATUS_ODBIJENA,
    IDEJA_STATUS_ODOBRENA,
    IDEJA_STATUS_POSLATA,
    IDEJA_STATUS_TOP_10,
    IDEJA_STATUS_U_OBRADI,
    Ideja,
)

# Unicode status ("NAGRAĐENA") - centralizovan u modelu, uvozimo ga direktno da
# izbegnemo ASCII zamenu.
from app.models.ideja import IDEJA_STATUS_NAGRADJENA
from app.models.korisnik import (
    STATUS_ZAPOSLENJA_AKTIVAN,
    STATUS_ZAPOSLENJA_NEAKTIVAN,
    Korisnik,
)
from app.models.obavestenje import OBAVESTENJE_STATUS_PUBLISHED, Obavestenje, ObavestenjePrimalac
from app.models.push import (
    PUSH_STATUS_FAILED,
    PUSH_STATUS_PENDING,
    PUSH_STATUS_SENT,
    PUSH_STATUS_SKIPPED,
    PushIsporuka,
)


class AdminDashboardRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------- korisnici
    def korisnici_counts(self) -> dict[str, int]:
        stmt = select(
            func.sum(case((Korisnik.status_zaposlenja == STATUS_ZAPOSLENJA_AKTIVAN, 1), else_=0)),
            func.sum(case((Korisnik.status_zaposlenja == STATUS_ZAPOSLENJA_NEAKTIVAN, 1), else_=0)),
            func.sum(case((Korisnik.datum_poslednje_prijave.is_not(None), 1), else_=0)),
            func.sum(case((Korisnik.zakljucan == "D", 1), else_=0)),
        ).select_from(Korisnik)
        row = self.db.execute(stmt).one()
        return {
            "aktivni": int(row[0] or 0),
            "neaktivni": int(row[1] or 0),
            "aktivirali_aplikaciju": int(row[2] or 0),
            "zakljucani": int(row[3] or 0),
        }

    # --------------------------------------------------------------- ankete
    def ankete_counts(self) -> dict[str, int]:
        aktivne_sq = (
            select(func.count()).select_from(Anketa).where(Anketa.status == ANKETA_STATUS_ACTIVE)
        ).scalar_subquery()
        zavrsene_sq = (
            select(func.count())
            .select_from(Anketa)
            .where(Anketa.status.in_((ANKETA_STATUS_CLOSED, ANKETA_STATUS_ARCHIVED)))
        ).scalar_subquery()
        # Ucesca (ne identitet anonimnih odgovora) - materijalizovana lista primalaca.
        primalaca_sq = select(func.count()).select_from(AnketaUcesce).scalar_subquery()
        predaja_sq = (
            select(func.count()).select_from(AnketaUcesce).where(AnketaUcesce.status == UCESCE_SUBMITTED)
        ).scalar_subquery()

        row = self.db.execute(select(aktivne_sq, zavrsene_sq, primalaca_sq, predaja_sq)).one()
        aktivne, zavrsene, primalaca, predaja = (int(v or 0) for v in row)
        procenat = round((predaja / primalaca * 100), 2) if primalaca else 0.0
        return {
            "aktivne": aktivne,
            "zavrsene": zavrsene,
            "broj_primalaca": primalaca,
            "broj_predaja": predaja,
            "procenat_odziva": procenat,
        }

    # ---------------------------------------------------------------- ideje
    def ideje_counts(self) -> dict[str, int]:
        stmt = select(
            func.sum(case((Ideja.status == IDEJA_STATUS_POSLATA, 1), else_=0)),
            func.sum(case((Ideja.status == IDEJA_STATUS_U_OBRADI, 1), else_=0)),
            func.sum(case((Ideja.status == IDEJA_STATUS_ODOBRENA, 1), else_=0)),
            func.sum(case((Ideja.status == IDEJA_STATUS_ODBIJENA, 1), else_=0)),
            func.sum(case((Ideja.status == IDEJA_STATUS_TOP_10, 1), else_=0)),
            func.sum(case((Ideja.status == IDEJA_STATUS_NAGRADJENA, 1), else_=0)),
        ).select_from(Ideja)
        row = self.db.execute(stmt).one()
        keys = ("nove", "u_obradi", "odobrene", "odbijene", "top_10", "nagradjene")
        return {k: int(v or 0) for k, v in zip(keys, row, strict=True)}

    # ----------------------------------------------------------- obavestenja
    def obavestenja_counts(self) -> dict[str, int]:
        objavljena_sq = (
            select(func.count())
            .select_from(Obavestenje)
            .where(Obavestenje.status == OBAVESTENJE_STATUS_PUBLISHED)
        ).scalar_subquery()
        primalaca_sq = select(func.count()).select_from(ObavestenjePrimalac).scalar_subquery()
        procitane_sq = (
            select(func.count()).select_from(ObavestenjePrimalac).where(ObavestenjePrimalac.procitano == "D")
        ).scalar_subquery()
        neprocitane_sq = (
            select(func.count()).select_from(ObavestenjePrimalac).where(ObavestenjePrimalac.procitano == "N")
        ).scalar_subquery()
        push_pending_sq = (
            select(func.count()).select_from(PushIsporuka).where(PushIsporuka.status == PUSH_STATUS_PENDING)
        ).scalar_subquery()
        # push_sent = FCM je PRIHVATIO poruku, NE potvrda dostave uredjaju.
        push_sent_sq = (
            select(func.count()).select_from(PushIsporuka).where(PushIsporuka.status == PUSH_STATUS_SENT)
        ).scalar_subquery()
        push_failed_sq = (
            select(func.count()).select_from(PushIsporuka).where(PushIsporuka.status == PUSH_STATUS_FAILED)
        ).scalar_subquery()
        push_skipped_sq = (
            select(func.count()).select_from(PushIsporuka).where(PushIsporuka.status == PUSH_STATUS_SKIPPED)
        ).scalar_subquery()

        row = self.db.execute(
            select(
                objavljena_sq,
                primalaca_sq,
                procitane_sq,
                neprocitane_sq,
                push_pending_sq,
                push_sent_sq,
                push_failed_sq,
                push_skipped_sq,
            )
        ).one()
        keys = (
            "objavljena",
            "broj_primalaca",
            "procitane",
            "neprocitane",
            "push_pending",
            "push_sent",
            "push_failed",
            "push_skipped",
        )
        return {k: int(v or 0) for k, v in zip(keys, row, strict=True)}

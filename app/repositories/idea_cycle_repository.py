import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.idea_ciklus import CIKLUS_STATUS_AKTIVAN, IdeaCiklus


class IdeaCycleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, ciklus_id: int) -> IdeaCiklus | None:
        return self.db.get(IdeaCiklus, ciklus_id)

    def get_active_cycle(self) -> IdeaCiklus | None:
        stmt = select(IdeaCiklus).where(IdeaCiklus.status == CIKLUS_STATUS_AKTIVAN)
        return self.db.execute(stmt).scalars().first()

    def get_active_cycle_for_update(self) -> IdeaCiklus | None:
        """Zakljucava red aktivnog ciklusa (SELECT ... FOR UPDATE) da bi provera limita
        i upis nove ideje bili serijalizovani po ciklusu unutar iste Oracle transakcije.
        Jednostavno resenje bez dodatne infrastrukture / distributed lock-a."""
        stmt = (
            select(IdeaCiklus)
            .where(IdeaCiklus.status == CIKLUS_STATUS_AKTIVAN)
            .with_for_update()
        )
        return self.db.execute(stmt).scalars().first()

    def list_cycles(self) -> list[IdeaCiklus]:
        stmt = select(IdeaCiklus).order_by(IdeaCiklus.datum_pocetka.desc(), IdeaCiklus.id.desc())
        return list(self.db.execute(stmt).scalars().all())

    def count_active_cycles(self) -> int:
        stmt = select(func.count()).select_from(IdeaCiklus).where(
            IdeaCiklus.status == CIKLUS_STATUS_AKTIVAN
        )
        return int(self.db.execute(stmt).scalar_one())

    def create(
        self, naziv: str, datum_pocetka: datetime.datetime, datum_zavrsetka: datetime.datetime
    ) -> IdeaCiklus:
        from app.models.idea_ciklus import CIKLUS_STATUS_PLANIRAN

        now = datetime.datetime.now()
        ciklus = IdeaCiklus(
            naziv=naziv,
            datum_pocetka=datum_pocetka,
            datum_zavrsetka=datum_zavrsetka,
            status=CIKLUS_STATUS_PLANIRAN,
            datum_kreiranja=now,
        )
        self.db.add(ciklus)
        self.db.flush()
        return ciklus
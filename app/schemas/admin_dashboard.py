from pydantic import BaseModel


class DashboardKorisniciOut(BaseModel):
    aktivni: int
    neaktivni: int
    aktivirali_aplikaciju: int
    zakljucani: int


class DashboardAnketeOut(BaseModel):
    aktivne: int
    zavrsene: int
    broj_primalaca: int
    broj_predaja: int
    procenat_odziva: float


class DashboardIdejeOut(BaseModel):
    nove: int
    u_obradi: int
    odobrene: int
    odbijene: int
    top_10: int
    nagradjene: int


class DashboardObavestenjaOut(BaseModel):
    objavljena: int
    broj_primalaca: int
    procitane: int
    neprocitane: int
    # push_sent znaci da je FCM PRIHVATIO poruku - nije potvrda dostave uredjaju.
    push_pending: int
    push_sent: int
    push_failed: int
    push_skipped: int


class AdminDashboardResponse(BaseModel):
    korisnici: DashboardKorisniciOut
    ankete: DashboardAnketeOut
    ideje: DashboardIdejeOut
    obavestenja: DashboardObavestenjaOut

-- ============================================================================
-- PULS - Modul ANKETE - TIPOVI PITANJA U BAZI (administracija bez izmene koda)
-- Oracle DDL: nova lookup tabela + seed postojecih 7 tipova + zamena hardkodovanog
-- CHECK ogranicenja stranim kljucem.
--
-- SHEMA: PORTAL           TABLESPACE: GOMEX           ORACLE: 19c
--
-- !!! VAZNO !!!
-- Ova skripta se NE izvrsava automatski iz aplikacije. Mora se RUCNO pregledati
-- i pokrenuti (SQL Developer "Run Script" / SQL*Plus) POSLE sql/002 i sql/007.
-- Bez DROP TABLE / DELETE / TRUNCATE / UPDATE. Jedini DROP je kontrolisana zamena
-- CK_PITANJA_TIP (hardkodovan spisak tipova) stranim kljucem FK_PITANJA_TIP.
--
-- ZASTO: do sada je spisak tipova pitanja bio hardkodovan na dva mesta - u kodu i u
-- CK_PITANJA_TIP. Nov raspon ocene (npr. 1-4) je zahtevao izmenu koda, DDL-a i
-- mobilne aplikacije. Od sada je TIP PITANJA red u ovoj tabeli, a backend i klijenti
-- poznaju samo KOMPONENTU (familiju UI kontrole i oblika odgovora):
--     SINGLE_CHOICE | MULTI_CHOICE | DROPDOWN | TEXT | BOOLEAN | SCALE
-- Nova komponenta i dalje zahteva izmenu koda; nov TIP postojece komponente ne.
--
-- KOMPATIBILNOST: sifre postojecih 7 tipova su NEPROMENJENE, pa postojeca pitanja,
-- onboarding seed (sql/007) i stariji backend/mobilni klijenti rade bez izmene.
-- Stariji backend upisuje samo tih 7 sifara - sve postoje u tabeli, pa FK prolazi.
--
-- ADMINISTRACIJA (direktno u bazi):
--   * Nov raspon ocene = NOV RED, npr.:
--       INSERT INTO PULS_ANKETA_TIPOVI_PITANJA
--           (SIFRA, NAZIV, KOMPONENTA, MIN_VREDNOST, MAX_VREDNOST, AKTIVAN, REDOSLED)
--       VALUES ('RATING_1_4', N'Ocena 1-4', 'SCALE', 1, 4, 'D', 55);
--     Backend ga preuzima sam (kes do 60 sekundi), bez restarta.
--   * NE MENJATI KOMPONENTA / MIN_VREDNOST / MAX_VREDNOST reda koji je vec koriscen u
--     nekom pitanju: postojeci odgovori i statistika bi izgubili smisao (npr. ocena 5
--     na skali koja je naknadno suzena na 1-4). Za drugi raspon dodati nov red.
--   * Povlacenje tipa iz upotrebe: AKTIVAN='N'. Postojeca pitanja nastavljaju da rade,
--     tip se samo vise ne nudi za nova pitanja. Red se ne brise (FK ga i stiti).
--   * Mobilna aplikacija koja jos ne cita KOMPONENTU ne poznaje nove sifre - pre
--     upotrebe novog tipa u anketi podici MIN_SUPPORTED_VERSION.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1) PULS_ANKETA_TIPOVI_PITANJA
--    SIFRA je iste sirine kao PULS_ANKETA_PITANJA.TIP_PITANJA (VARCHAR2(20)).
--    MIN/MAX su obavezni samo za SCALE i zabranjeni za ostale komponente. Gornja
--    granica 10 cuva upotrebljivost skale na telefonu i smislenu raspodelu u
--    statistici (raspodela nabraja SVAKU vrednost raspona).
-- ----------------------------------------------------------------------------
CREATE TABLE PULS_ANKETA_TIPOVI_PITANJA (
    SIFRA             VARCHAR2(20)    NOT NULL,
    NAZIV             NVARCHAR2(200)  NOT NULL,
    KOMPONENTA        VARCHAR2(20)    NOT NULL,
    MIN_VREDNOST      NUMBER(10,0),
    MAX_VREDNOST      NUMBER(10,0),
    AKTIVAN           CHAR(1)         DEFAULT 'D' NOT NULL,
    REDOSLED          NUMBER(10,0)    DEFAULT 0 NOT NULL,
    DATUM_KREIRANJA   TIMESTAMP(6)    DEFAULT SYSTIMESTAMP NOT NULL,
    DATUM_IZMENE      TIMESTAMP(6),
    CONSTRAINT PK_ANK_TIPOVI_PITANJA PRIMARY KEY (SIFRA),
    CONSTRAINT CK_ANK_TIP_PIT_KOMPONENTA CHECK (KOMPONENTA IN
        ('SINGLE_CHOICE', 'MULTI_CHOICE', 'DROPDOWN', 'TEXT', 'BOOLEAN', 'SCALE')),
    CONSTRAINT CK_ANK_TIP_PIT_AKTIVAN CHECK (AKTIVAN IN ('D', 'N')),
    CONSTRAINT CK_ANK_TIP_PIT_RASPON CHECK (
        (KOMPONENTA = 'SCALE'
            AND MIN_VREDNOST IS NOT NULL AND MAX_VREDNOST IS NOT NULL
            AND MIN_VREDNOST >= 0 AND MAX_VREDNOST <= 10
            AND MIN_VREDNOST < MAX_VREDNOST)
        OR
        (KOMPONENTA <> 'SCALE' AND MIN_VREDNOST IS NULL AND MAX_VREDNOST IS NULL))
);


-- ----------------------------------------------------------------------------
-- 2) Seed postojecih 7 tipova (idempotentno). Mora PRE FK-a iz koraka 3, jer FK
--    validira sva postojeca pitanja.
-- ----------------------------------------------------------------------------
INSERT INTO PULS_ANKETA_TIPOVI_PITANJA (SIFRA, NAZIV, KOMPONENTA, MIN_VREDNOST, MAX_VREDNOST, AKTIVAN, REDOSLED)
SELECT 'SINGLE_CHOICE', N'Jedan izbor', 'SINGLE_CHOICE', NULL, NULL, 'D', 10 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM PULS_ANKETA_TIPOVI_PITANJA WHERE SIFRA = 'SINGLE_CHOICE');

INSERT INTO PULS_ANKETA_TIPOVI_PITANJA (SIFRA, NAZIV, KOMPONENTA, MIN_VREDNOST, MAX_VREDNOST, AKTIVAN, REDOSLED)
SELECT 'MULTI_CHOICE', N'Više izbora', 'MULTI_CHOICE', NULL, NULL, 'D', 20 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM PULS_ANKETA_TIPOVI_PITANJA WHERE SIFRA = 'MULTI_CHOICE');

INSERT INTO PULS_ANKETA_TIPOVI_PITANJA (SIFRA, NAZIV, KOMPONENTA, MIN_VREDNOST, MAX_VREDNOST, AKTIVAN, REDOSLED)
SELECT 'DROPDOWN', N'Padajuća lista', 'DROPDOWN', NULL, NULL, 'D', 30 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM PULS_ANKETA_TIPOVI_PITANJA WHERE SIFRA = 'DROPDOWN');

INSERT INTO PULS_ANKETA_TIPOVI_PITANJA (SIFRA, NAZIV, KOMPONENTA, MIN_VREDNOST, MAX_VREDNOST, AKTIVAN, REDOSLED)
SELECT 'TEXT', N'Slobodan tekst', 'TEXT', NULL, NULL, 'D', 40 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM PULS_ANKETA_TIPOVI_PITANJA WHERE SIFRA = 'TEXT');

INSERT INTO PULS_ANKETA_TIPOVI_PITANJA (SIFRA, NAZIV, KOMPONENTA, MIN_VREDNOST, MAX_VREDNOST, AKTIVAN, REDOSLED)
SELECT 'BOOLEAN', N'Da / Ne', 'BOOLEAN', NULL, NULL, 'D', 50 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM PULS_ANKETA_TIPOVI_PITANJA WHERE SIFRA = 'BOOLEAN');

INSERT INTO PULS_ANKETA_TIPOVI_PITANJA (SIFRA, NAZIV, KOMPONENTA, MIN_VREDNOST, MAX_VREDNOST, AKTIVAN, REDOSLED)
SELECT 'RATING_1_5', N'Ocena 1-5', 'SCALE', 1, 5, 'D', 60 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM PULS_ANKETA_TIPOVI_PITANJA WHERE SIFRA = 'RATING_1_5');

INSERT INTO PULS_ANKETA_TIPOVI_PITANJA (SIFRA, NAZIV, KOMPONENTA, MIN_VREDNOST, MAX_VREDNOST, AKTIVAN, REDOSLED)
SELECT 'RATING_1_10', N'Ocena 1-10', 'SCALE', 1, 10, 'D', 70 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM PULS_ANKETA_TIPOVI_PITANJA WHERE SIFRA = 'RATING_1_10');

COMMIT;


-- ----------------------------------------------------------------------------
-- 3) PULS_ANKETA_PITANJA: hardkodovan spisak (CK_PITANJA_TIP iz sql/002) -> FK.
--    FK se dodaje PRVI, pa kolona ni u jednom trenutku nije bez zastite. Ako bi
--    postojalo pitanje sa sifrom van tabele, ADD CONSTRAINT pada i CHECK ostaje.
-- ----------------------------------------------------------------------------
ALTER TABLE PULS_ANKETA_PITANJA ADD CONSTRAINT FK_PITANJA_TIP
    FOREIGN KEY (TIP_PITANJA) REFERENCES PULS_ANKETA_TIPOVI_PITANJA (SIFRA);

ALTER TABLE PULS_ANKETA_PITANJA DROP CONSTRAINT CK_PITANJA_TIP;

-- Indeks za FK kolonu (zakljucavanje pri izmeni roditelja + pretraga "gde se tip koristi").
CREATE INDEX IX_PITANJA_TIP ON PULS_ANKETA_PITANJA (TIP_PITANJA);

COMMIT;

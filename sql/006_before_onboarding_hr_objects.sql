-- ============================================================================
-- PULS - Snapshot ORIGINALNIH definicija PRE onboarding izmene (DATUM_ZAPOSLENJA)
-- Datum snapshot-a: 2026-09-09
--
-- Svrha: ROLLBACK REFERENCA. Ovo je TACAN tekst objekata PULS_V_AKTIVNI_ZAPOSLENI
-- i PULS_SINHRONIZUJ_KORISNIKE preuzet READ-ONLY iz baze (DBMS_METADATA.GET_DDL)
-- PRE nego sto je dodata kolona DATUM_ZAPOSLENJA (vidi sql/006_onboarding_surveys_module.sql
-- deo 5). Ako aditivna izmena iz dela 5 zatreba rollback, ova skripta vraca
-- objekte na ovo stanje (CREATE OR REPLACE istim tekstom).
--
-- Izvor: DBMS_METADATA.GET_DDL('VIEW', 'PULS_V_AKTIVNI_ZAPOSLENI', 'PORTAL')
--        DBMS_METADATA.GET_DDL('PROCEDURE', 'PULS_SINHRONIZUJ_KORISNIKE', 'PORTAL')
-- Oba objekta su u trenutku citanja bila STATUS = VALID.
--
-- SHEMA: PORTAL           ORACLE: 19c
--
-- !!! VAZNO !!!
-- Ova skripta NE sme NIKADA da sadrzi DROP TABLE / DELETE / TRUNCATE niti
-- licne podatke zaposlenih - iskljucivo CREATE OR REPLACE tekst dva objekta,
-- doslovno onako kako je procitano iz baze (bez izmena).
-- Skripta se NE izvrsava automatski - cuva se samo kao rollback referenca.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- ORIGINAL: VIEW PULS_V_AKTIVNI_ZAPOSLENI (8 kolona, bez DATUM_ZAPOSLENJA)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FORCE EDITIONABLE VIEW "PORTAL"."PULS_V_AKTIVNI_ZAPOSLENI" ("PLATNI_BROJ", "IME", "PREZIME", "BROJ_TELEFONA", "ORGJED_SIFRA", "RADNO_MESTO_SIFRA", "DATUM_OD", "DATUM_DO") AS
SELECT
    PLATNI_BROJ,
    IME,
    PREZIME,
    BROJ_TELEFONA,
    ORGJED_SIFRA,
    RADNO_MESTO_SIFRA,
    DATUM_OD,
    DATUM_DO
FROM (
    SELECT
        TRIM(CAST(k.PLATNIBROJ AS VARCHAR2(30))) AS PLATNI_BROJ,
        TRIM(k.IME) AS IME,
        TRIM(k.PREZIME) AS PREZIME,
        TRIM(k.TELEFON) AS BROJ_TELEFONA,
        CASE
            WHEN z.ORGJED IS NULL THEN NULL
            ELSE TRIM(CAST(z.ORGJED AS VARCHAR2(50)))
        END AS ORGJED_SIFRA,
        CASE
            WHEN z.RADNOMESTO IS NULL THEN NULL
            ELSE TRIM(CAST(z.RADNOMESTO AS VARCHAR2(50)))
        END AS RADNO_MESTO_SIFRA,
        z.DATUMOD AS DATUM_OD,
        z.DATUMDO AS DATUM_DO,
        ROW_NUMBER() OVER (
            PARTITION BY k.PLATNIBROJ
            ORDER BY
                z.DATUMOD DESC,
                NVL(z.DATUMDO, DATE '9999-12-31') DESC,
                z.ORGJED NULLS LAST,
                z.RADNOMESTO NULLS LAST
        ) AS RN
    FROM HR.KADROVI k
    INNER JOIN HR.ZAPOSLENJA z
        ON z.PLATNIBROJ = k.PLATNIBROJ
    WHERE k.PLATNIBROJ IS NOT NULL
      AND z.DATUMOD IS NOT NULL
      AND TRUNC(z.DATUMOD) <= TRUNC(SYSDATE)
      AND (
            z.DATUMDO IS NULL
            OR TRUNC(z.DATUMDO) >= TRUNC(SYSDATE)
          )
)
WHERE RN = 1
/


-- ----------------------------------------------------------------------------
-- ORIGINAL: PROCEDURE PULS_SINHRONIZUJ_KORISNIKE (bez DATUM_ZAPOSLENJA logike)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE EDITIONABLE PROCEDURE "PORTAL"."PULS_SINHRONIZUJ_KORISNIKE"
IS

    /* =========================================================
       PROMENLJIVE ZA PRACENJE SINHRONIZACIJE
       ========================================================= */

    -- ID zapisa iz PULS_SINHRONIZACIJE za trenutno izvrsavanje
    v_sinhronizacija_id     PULS_SINHRONIZACIJE.ID%TYPE;

    -- ID osnovne uloge ZAPOSLENI
    v_uloga_zaposleni_id    PULS_ULOGE.ID%TYPE;


    /* =========================================================
       BROJACI REZULTATA SINHRONIZACIJE
       ========================================================= */

    v_broj_dodatih          NUMBER := 0;
    v_broj_izmenjenih       NUMBER := 0;
    v_broj_deaktiviranih    NUMBER := 0;
    v_broj_reaktiviranih    NUMBER := 0;
    v_broj_gresaka          NUMBER := 0;


    /* =========================================================
       PROMENLJIVA ZA CUVANJE TEKSTA GRESKE
       ========================================================= */

    v_greska                VARCHAR2(4000);

BEGIN

    /* =========================================================
       KORAK 1
       OTVARANJE NOVOG ZAPISA SINHRONIZACIJE

       Svako izvrsavanje procedure dobija svoj zapis u tabeli
       PULS_SINHRONIZACIJE.

       Pocetni status je U_TOKU.

       RETURNING ID vraca ID upravo kreiranog zapisa kako bismo
       ga na kraju procedure mogli azurirati rezultatom.
       ========================================================= */

    INSERT INTO PULS_SINHRONIZACIJE (
        TIP_SINHRONIZACIJE,
        STATUS,
        DATUM_POCETKA
    )
    VALUES (
        'KORISNICI',
        'U_TOKU',
        SYSTIMESTAMP
    )
    RETURNING ID
    INTO v_sinhronizacija_id;


    /* =========================================================
       COMMIT JE OVDE NAMERAN

       Zelimo da zapis o pocetku sinhronizacije ostane sacuvan
       cak i ako kasnije procedura zavrsi greskom.

       Ako kasnije dode do ROLLBACK-a, ovaj zapis ostaje u bazi
       i mozemo mu postaviti STATUS = GRESKA.
       ========================================================= */

    COMMIT;



    /* =========================================================
       KORAK 2
       PRONALAZENJE OSNOVNE ULOGE ZAPOSLENI

       Svaki korisnik PULS aplikacije mora imati ulogu ZAPOSLENI.

       Trazimo aktivnu ulogu sa sifrom ZAPOSLENI i cuvamo njen ID.
       ========================================================= */

    BEGIN

        SELECT ID
          INTO v_uloga_zaposleni_id
          FROM PULS_ULOGE
         WHERE SIFRA = 'ZAPOSLENI'
           AND AKTIVNA = 'D';


    /* ---------------------------------------------------------
       Ako uloga ne postoji, prekidamo sinhronizaciju.

       Nema smisla kreirati korisnike kojima ne mozemo dodeliti
       osnovnu ulogu.
       --------------------------------------------------------- */

    EXCEPTION

        WHEN NO_DATA_FOUND THEN

            RAISE_APPLICATION_ERROR(
                -20001,
                'Nije pronadjena aktivna PULS uloga ZAPOSLENI.'
            );


        /* -----------------------------------------------------
           Ovo prakticno ne bi trebalo da se desi jer SIFRA ima
           UNIQUE ogranicenje, ali zastita ostaje.
           ----------------------------------------------------- */

        WHEN TOO_MANY_ROWS THEN

            RAISE_APPLICATION_ERROR(
                -20002,
                'Postoji vise aktivnih PULS uloga sa sifrom ZAPOSLENI.'
            );

    END;



    /* =========================================================
       KORAK 3
       PROVERA NEKOMPLETNIH HR PODATAKA

       Proveravamo da li medju aktivnim zaposlenima postoje zapisi
       bez imena ili prezimena.

       Takvi korisnici se kasnije nece kreirati.

       Broj takvih zapisa evidentiramo kao broj gresaka.
       ========================================================= */

    SELECT COUNT(*)
      INTO v_broj_gresaka
      FROM PULS_V_AKTIVNI_ZAPOSLENI
     WHERE IME IS NULL
        OR PREZIME IS NULL;



    /* =========================================================
       KORAK 4
       KREIRANJE NOVIH PULS KORISNIKA

       Uzimamo trenutno aktivne zaposlene iz view-a
       PULS_V_AKTIVNI_ZAPOSLENI.

       Korisnik se kreira samo ako:
       - ima ime
       - ima prezime
       - jos ne postoji u PULS_KORISNICI

       Identifikacija se vrsi preko PLATNI_BROJ.
       ========================================================= */

    INSERT INTO PULS_KORISNICI (
        PLATNI_BROJ,
        IME,
        PREZIME,
        BROJ_TELEFONA,
        LOZINKA_HASH,
        STATUS_ZAPOSLENJA,
        STATUS_NALOGA,
        OBAVEZNA_PROMENA_LOZINKE,
        TELEFON_POTVRDJEN,
        BROJ_NEUSPESNIH_PRIJAVA,
        ZAKLJUCAN,
        DATUM_SINHRONIZACIJE
    )
    SELECT
        s.PLATNI_BROJ,
        s.IME,
        s.PREZIME,
        s.BROJ_TELEFONA,

        -- Lozinku nece generisati Oracle procedura.
        -- To ce naknadno uraditi backend.
        NULL,

        -- Korisnik postoji u aktivnim HR zaposlenjima.
        'AKTIVAN',

        -- Novi nalog je po default-u omogucen.
        'OMOGUCEN',

        -- Pri prvom login-u mora promeniti pocetnu lozinku.
        'D',

        -- Telefon jos nije potvrdjen kroz aplikaciju.
        'N',

        -- Novi korisnik nema neuspesnih login pokusaja.
        0,

        -- Novi korisnik nije zakljucan.
        'N',

        SYSTIMESTAMP

    FROM PULS_V_AKTIVNI_ZAPOSLENI s

    WHERE s.IME IS NOT NULL
      AND s.PREZIME IS NOT NULL

      /* -------------------------------------------------------
         Sprecavamo dupliranje korisnika.

         Ako platni broj vec postoji u PULS_KORISNICI,
         INSERT se ne radi.
         ------------------------------------------------------- */
      AND NOT EXISTS (
            SELECT 1
              FROM PULS_KORISNICI k
             WHERE k.PLATNI_BROJ = s.PLATNI_BROJ
      );


    /* =========================================================
       SQL%ROWCOUNT vraca broj redova koje je prethodni INSERT
       dodao u tabelu.
       ========================================================= */

    v_broj_dodatih := SQL%ROWCOUNT;



    /* =========================================================
       KORAK 5
       AZURIRANJE POSTOJECIH KORISNIKA

       Za korisnike koji vec postoje u PULS-u proveravamo da li
       su se promenili:
       - IME
       - PREZIME

       Telefon ima posebno pravilo.

       Ako PULS vec ima broj telefona -> NE DIRAMO GA.

       Ako je PULS broj NULL, a HR ima telefon -> dopunjujemo ga.

       Razlog je sto korisnik kroz aplikaciju moze sam da ispravi
       svoj broj telefona i HR sync ne sme kasnije da ga pregazi.
       ========================================================= */

    MERGE INTO PULS_KORISNICI k

    USING (
        SELECT
            PLATNI_BROJ,
            IME,
            PREZIME,
            BROJ_TELEFONA
        FROM PULS_V_AKTIVNI_ZAPOSLENI
        WHERE IME IS NOT NULL
          AND PREZIME IS NOT NULL
    ) s

    ON (
        k.PLATNI_BROJ = s.PLATNI_BROJ
    )

    WHEN MATCHED THEN

        UPDATE SET

            /* Ime uvek prati HR podatke. */
            k.IME = s.IME,

            /* Prezime uvek prati HR podatke. */
            k.PREZIME = s.PREZIME,

            /* -------------------------------------------------
               Telefon menjamo samo ako u PULS-u jos ne postoji.

               Ako korisnik vec ima broj, ostavljamo postojeci.
               ------------------------------------------------- */
            k.BROJ_TELEFONA =
                CASE
                    WHEN k.BROJ_TELEFONA IS NULL
                    THEN s.BROJ_TELEFONA
                    ELSE k.BROJ_TELEFONA
                END

        /* -----------------------------------------------------
           UPDATE se izvrsava samo ako zaista postoji promena.

           Time izbegavamo nepotrebne UPDATE operacije.
           ----------------------------------------------------- */
        WHERE
               NVL(k.IME, '[NULL]')
                    <> NVL(s.IME, '[NULL]')

            OR NVL(k.PREZIME, '[NULL]')
                    <> NVL(s.PREZIME, '[NULL]')

            OR (
                k.BROJ_TELEFONA IS NULL
                AND s.BROJ_TELEFONA IS NOT NULL
            );


    /* Broj stvarno azuriranih korisnika. */
    v_broj_izmenjenih := SQL%ROWCOUNT;



    /* =========================================================
       KORAK 6
       REAKTIVACIJA KORISNIKA

       Korisnik je ranije mogao napustiti firmu i imati:

           STATUS_ZAPOSLENJA = NEAKTIVAN

       Ako se sada ponovo nalazi u view-u aktivnih zaposlenih,
       ponovo ga aktiviramo.

       Ne kreiramo novi nalog.
       ========================================================= */

    UPDATE PULS_KORISNICI k

       SET k.STATUS_ZAPOSLENJA = 'AKTIVAN',
           k.DATUM_SINHRONIZACIJE = SYSTIMESTAMP

     WHERE k.STATUS_ZAPOSLENJA = 'NEAKTIVAN'

       AND EXISTS (
            SELECT 1
              FROM PULS_V_AKTIVNI_ZAPOSLENI s
             WHERE s.PLATNI_BROJ = k.PLATNI_BROJ
       );


    /* Broj korisnika koji su ponovo aktivirani. */
    v_broj_reaktiviranih := SQL%ROWCOUNT;



    /* =========================================================
       KORAK 7
       DEAKTIVACIJA KORISNIKA

       Ako korisnik trenutno ima STATUS_ZAPOSLENJA = AKTIVAN,
       ali vise ne postoji u view-u aktivnih HR zaposlenja,
       menjamo mu status u NEAKTIVAN.

       Korisnik se NE BRISE iz baze.

       Njegova istorija ostaje sacuvana.
       ========================================================= */

    UPDATE PULS_KORISNICI k

       SET k.STATUS_ZAPOSLENJA = 'NEAKTIVAN',
           k.DATUM_SINHRONIZACIJE = SYSTIMESTAMP

     WHERE k.STATUS_ZAPOSLENJA = 'AKTIVAN'

       AND NOT EXISTS (
            SELECT 1
              FROM PULS_V_AKTIVNI_ZAPOSLENI s
             WHERE s.PLATNI_BROJ = k.PLATNI_BROJ
       );


    /* Broj korisnika koji su deaktivirani. */
    v_broj_deaktiviranih := SQL%ROWCOUNT;



    /* =========================================================
       KORAK 8
       OSVEZAVANJE DATUMA SINHRONIZACIJE

       Za sve trenutno zaposlene korisnike postavljamo vreme
       poslednje uspesne obrade HR podataka.

       Ovo ne racunamo kao poslovnu izmenu korisnika.
       ========================================================= */

    UPDATE PULS_KORISNICI k

       SET k.DATUM_SINHRONIZACIJE = SYSTIMESTAMP

     WHERE EXISTS (
            SELECT 1
              FROM PULS_V_AKTIVNI_ZAPOSLENI s
             WHERE s.PLATNI_BROJ = k.PLATNI_BROJ
       );



    /* =========================================================
       KORAK 9
       DODELA OSNOVNE ULOGE ZAPOSLENI

       Svaki aktivni PULS korisnik mora imati osnovnu ulogu
       ZAPOSLENI.

       Ako je vec ima, ne dodajemo novi zapis.

       ADMIN i HR uloge se kasnije mogu dodati kao dodatne uloge.
       ========================================================= */

    INSERT INTO PULS_KORISNIK_ULOGE (
        KORISNIK_ID,
        ULOGA_ID,
        DODELIO_KORISNIK_ID,
        DATUM_DODELE
    )
    SELECT
        k.ID,
        v_uloga_zaposleni_id,

        /* NULL znaci da je ulogu dodelio sistem/sinhronizacija. */
        NULL,

        SYSTIMESTAMP

    FROM PULS_KORISNICI k

    /* Korisnik mora trenutno biti zaposlen. */
    WHERE EXISTS (
            SELECT 1
              FROM PULS_V_AKTIVNI_ZAPOSLENI s
             WHERE s.PLATNI_BROJ = k.PLATNI_BROJ
    )

    /* Korisnik ne sme vec imati istu ulogu. */
      AND NOT EXISTS (
            SELECT 1
              FROM PULS_KORISNIK_ULOGE ku
             WHERE ku.KORISNIK_ID = k.ID
               AND ku.ULOGA_ID = v_uloga_zaposleni_id
    );



    /* =========================================================
       KORAK 10
       DEAKTIVACIJA RASPOREDA NEAKTIVNIH KORISNIKA

       Ako je korisniku istekao radni odnos, svi njegovi trenutno
       aktivni rasporedi se oznacavaju kao neaktivni.

       Istorija rasporeda se cuva.
       ========================================================= */

    UPDATE PULS_KORISNIK_RASPOREDI kr

       SET kr.AKTIVAN = 'N',
           kr.PRIMARNI = 'N',
           kr.DATUM_SINHRONIZACIJE = SYSTIMESTAMP

     WHERE kr.AKTIVAN = 'D'

       AND EXISTS (
            SELECT 1
              FROM PULS_KORISNICI k
             WHERE k.ID = kr.KORISNIK_ID
               AND k.STATUS_ZAPOSLENJA = 'NEAKTIVAN'
       );



    /* =========================================================
       KORAK 11
       DEAKTIVACIJA STAROG RASPOREDA

       Proveravamo aktivne rasporede korisnika koji su jos
       zaposleni.

       Ako trenutni PULS raspored vise ne odgovara HR podacima
       po kombinaciji:

           ORGJED + RADNO_MESTO

       stari raspored postaje neaktivan.

       Primer:

           Staro:
           ORGJED 101 / RM 25

           Novo u HR:
           ORGJED 205 / RM 30

       Stari red ostaje u istoriji sa AKTIVAN = N.
       ========================================================= */

    UPDATE PULS_KORISNIK_RASPOREDI kr

       SET kr.AKTIVAN = 'N',
           kr.PRIMARNI = 'N',
           kr.DATUM_SINHRONIZACIJE = SYSTIMESTAMP

     WHERE kr.AKTIVAN = 'D'


       /* ------------------------------------------------------
          Korisnik i dalje postoji medju aktivnim zaposlenima.
          ------------------------------------------------------ */
       AND EXISTS (
            SELECT 1
              FROM PULS_KORISNICI k

              JOIN PULS_V_AKTIVNI_ZAPOSLENI s
                ON s.PLATNI_BROJ = k.PLATNI_BROJ

             WHERE k.ID = kr.KORISNIK_ID
       )


       /* ------------------------------------------------------
          Ali trenutni PULS raspored vise ne postoji u HR stanju.
          ------------------------------------------------------ */
       AND NOT EXISTS (
            SELECT 1
              FROM PULS_KORISNICI k

              JOIN PULS_V_AKTIVNI_ZAPOSLENI s
                ON s.PLATNI_BROJ = k.PLATNI_BROJ

             WHERE k.ID = kr.KORISNIK_ID

               AND s.ORGJED_SIFRA IS NOT NULL

               AND kr.ORGJED_SIFRA = s.ORGJED_SIFRA

               AND NVL(
                       kr.RADNO_MESTO_SIFRA,
                       '[NULL]'
                   )
                   =
                   NVL(
                       s.RADNO_MESTO_SIFRA,
                       '[NULL]'
                   )
       );



    /* =========================================================
       KORAK 12
       SINHRONIZACIJA TRENUTNOG RASPOREDA

       MERGE proverava da li postoji aktivni PULS raspored koji
       odgovara trenutnom HR zaposlenju.

       Kljuc poredjenja je:

       - KORISNIK_ID
       - ORGJED_SIFRA
       - RADNO_MESTO_SIFRA
       - AKTIVAN = D
       ========================================================= */

    MERGE INTO PULS_KORISNIK_RASPOREDI kr

    USING (
        SELECT
            k.ID AS KORISNIK_ID,
            s.ORGJED_SIFRA,
            s.RADNO_MESTO_SIFRA,
            s.DATUM_OD,
            s.DATUM_DO

        FROM PULS_KORISNICI k

        INNER JOIN PULS_V_AKTIVNI_ZAPOSLENI s
            ON s.PLATNI_BROJ = k.PLATNI_BROJ

        /* -----------------------------------------------------
           Raspored kreiramo samo ako HR ima organizacionu
           jedinicu i korisnik je trenutno aktivan.
           ----------------------------------------------------- */
        WHERE s.ORGJED_SIFRA IS NOT NULL
          AND k.STATUS_ZAPOSLENJA = 'AKTIVAN'

    ) s

    ON (
           kr.KORISNIK_ID = s.KORISNIK_ID

       AND kr.ORGJED_SIFRA = s.ORGJED_SIFRA

       /* ------------------------------------------------------
          NVL omogucava da dva NULL radna mesta tretiramo kao
          jednake vrednosti pri poredjenju.
          ------------------------------------------------------ */
       AND NVL(
               kr.RADNO_MESTO_SIFRA,
               '[NULL]'
           )
           =
           NVL(
               s.RADNO_MESTO_SIFRA,
               '[NULL]'
           )

       AND kr.AKTIVAN = 'D'
    )


    /* =========================================================
       Ako raspored vec postoji:
       osvezavamo njegove podatke.
       ========================================================= */

    WHEN MATCHED THEN

        UPDATE SET

            kr.PRIMARNI = 'D',

            kr.DATUM_OD = s.DATUM_OD,

            kr.DATUM_DO = s.DATUM_DO,

            kr.DATUM_SINHRONIZACIJE = SYSTIMESTAMP


    /* =========================================================
       Ako aktivni raspored ne postoji:
       kreiramo novi istorijski zapis.
       ========================================================= */

    WHEN NOT MATCHED THEN

        INSERT (
            KORISNIK_ID,
            ORGJED_SIFRA,
            RADNO_MESTO_SIFRA,
            PRIMARNI,
            AKTIVAN,
            DATUM_OD,
            DATUM_DO,
            DATUM_SINHRONIZACIJE
        )

        VALUES (
            s.KORISNIK_ID,
            s.ORGJED_SIFRA,
            s.RADNO_MESTO_SIFRA,

            -- Trenutni raspored je primarni.
            'D',

            -- Novi raspored je aktivan.
            'D',

            s.DATUM_OD,
            s.DATUM_DO,

            SYSTIMESTAMP
        );



    /* =========================================================
       KORAK 13
       ZATVARANJE SINHRONIZACIJE

       Ako nije bilo nekvalitetnih HR zapisa:
           STATUS = USPESNA

       Ako postoje aktivni zaposleni bez imena/prezimena:
           STATUS = DELIMICNA

       U zapis sinhronizacije upisujemo sve brojace.
       ========================================================= */

    UPDATE PULS_SINHRONIZACIJE

       SET STATUS =
            CASE
                WHEN v_broj_gresaka > 0
                THEN 'DELIMICNA'
                ELSE 'USPESNA'
            END,

           DATUM_ZAVRSETKA = SYSTIMESTAMP,

           BROJ_DODATIH = v_broj_dodatih,

           BROJ_IZMENJENIH = v_broj_izmenjenih,

           BROJ_DEAKTIVIRANIH = v_broj_deaktiviranih,

           BROJ_REAKTIVIRANIH = v_broj_reaktiviranih,

           BROJ_GRESAKA = v_broj_gresaka,

           OPIS_GRESKE =
            CASE
                WHEN v_broj_gresaka > 0
                THEN
                    'Postoje aktivni HR zapisi bez IMENA ili PREZIMENA. '
                    || 'Takvi novi korisnici nisu kreirani.'
                ELSE
                    NULL
            END

     WHERE ID = v_sinhronizacija_id;



    /* =========================================================
       Sve izmene ovog izvrsavanja procedure postaju trajne.
       ========================================================= */

    COMMIT;



/* =============================================================
   GLOBALNI EXCEPTION HANDLER

   Ako se bilo gde u proceduri dogodi neocekivana greska,
   ulazimo u ovaj blok.
   ============================================================= */

EXCEPTION

    WHEN OTHERS THEN


        /* =====================================================
           Ponistavamo sve poslovne izmene trenutnog izvrsavanja.

           Pocetni zapis u PULS_SINHRONIZACIJE ostaje sacuvan
           zato sto je ranije zasebno commit-ovan.
           ===================================================== */

        ROLLBACK;



        /* =====================================================
           Formiramo detaljan opis Oracle greske.

           SQLCODE
           -> Oracle kod greske.

           SQLERRM
           -> tekst greske.

           FORMAT_ERROR_BACKTRACE
           -> linija/mesto u PL/SQL kodu gde je greska nastala.
           ===================================================== */

        v_greska :=
              'SQLCODE='
           || SQLCODE
           || '; SQLERRM='
           || SUBSTR(
                SQLERRM,
                1,
                1500
              )
           || '; BACKTRACE='
           || SUBSTR(
                DBMS_UTILITY.FORMAT_ERROR_BACKTRACE,
                1,
                2000
              );



        /* =====================================================
           Oznacavamo ovu sinhronizaciju kao neuspesnu.

           Posto je poslovna transakcija rollback-ovana,
           svi brojaci se vracaju na 0.

           BROJ_GRESAKA = 1 oznacava tehnicku gresku procedure.
           ===================================================== */

        UPDATE PULS_SINHRONIZACIJE

           SET STATUS = 'GRESKA',

               DATUM_ZAVRSETKA = SYSTIMESTAMP,

               BROJ_DODATIH = 0,

               BROJ_IZMENJENIH = 0,

               BROJ_DEAKTIVIRANIH = 0,

               BROJ_REAKTIVIRANIH = 0,

               BROJ_GRESAKA = 1,

               OPIS_GRESKE = v_greska

         WHERE ID = v_sinhronizacija_id;



        /* Cuvamo podatak o neuspesnom izvrsavanju. */
        COMMIT;



        /* =====================================================
           Ponovo prosledjujemo originalnu Oracle gresku pozivaocu.

           Ovo je vazno kada proceduru bude pokretao
           DBMS_SCHEDULER, jer ce i Scheduler tada videti da je
           izvrsavanje zavrsilo greskom.
           ===================================================== */

        RAISE;

END;
/

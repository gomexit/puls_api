-- ============================================================================
-- PULS - Modul ONBOARDING ANKETE - SEED sadrzaja (tip ankete + 4 ankete:
-- 7/30/60/90 dana + struktura sekcija/pitanja/opcija + pravila automatske
-- dodele PULS_ANKETA_AUTOMATIKA). Infrastruktura (DDL) je u
-- sql/006_onboarding_surveys_module.sql i MORA biti izvrsena PRE ove skripte.
--
-- SHEMA: PORTAL           TABLESPACE: GOMEX           ORACLE: 19c
--
-- !!! VAZNO !!!
-- Ova skripta se NE izvrsava automatski iz aplikacije. Mora se RUCNO pregledati
-- i pokrenuti tek nakon nezavisnog pregleda, POSLE sql/006.
--
-- NACIN POKRETANJA: kao CEO SKRIPT (SQL Developer "Run Script" / F5, ili
-- SQL*Plus @007_onboarding_surveys_seed.sql), NE naredba-po-naredba. Fajl je
-- UTF-8 - u SQL Developer-u podesiti Encoding = UTF-8 pre otvaranja, da bi
-- srpska slova (c, c, s, z, dj) u N'...' literalima ostala ispravna.
--
-- TRANSAKCIJA: cela skripta je JEDNA transakcija. Nema medju-COMMIT-a; jedini
-- COMMIT je na samom kraju, tek posle provere sve 4 ankete i 4 pravila.
-- WHENEVER SQLERROR ispod prekida izvrsavanje na PRVOJ gresci i radi ROLLBACK,
-- pa greska u bilo kom bloku ostavlja bazu netaknutu (nema polovicnog seed-a).
-- Autocommit u klijentu mora biti ISKLJUCEN (SQL Developer default).
--
-- Idempotentnost: svaki blok proverava da li cilj vec postoji (WHERE NOT EXISTS
-- za prost INSERT tipa, PL/SQL provera za anketa+strukturu) pre upisa. Ponovno
-- pokretanje nad vec seed-ovanom bazom ne dupli redove i ne menja postojecu
-- strukturu - ako anketa istog naziva vec postoji ali NE odgovara ocekivanoj
-- strukturi (broj pitanja), ili ako milestone vec ima AKTIVNO pravilo za DRUGU
-- anketu, skripta PREKIDA sa RAISE_APPLICATION_ERROR (bez ikakve izmene).
--
-- Bez DROP / DELETE / TRUNCATE / UPDATE. Bez PULS_ANKETA_CILJEVI redova.
--
-- Izvor sadrzaja: interni Excel fajl "7 30 60 90.xlsx" (4 lista - jedan po
-- onboarding milestone-u), sadrzi ISKLJUCIVO tekst pitanja/opcija ankete -
-- BEZ licnih/HR podataka zaposlenih. Tekst pitanja i opcija je prenet DOSLOVNO,
-- ukljucujuci srpska slova (N'...' literali, NVARCHAR2/NCLOB kolone).
--
-- Namerne korekcije u odnosu na sirovi Excel sadrzaj (JEDINE izmene):
--   1) List "7 dana" ima pogresan naslov celije "30 dana " - NAZIV ankete je
--      ovde ispravno "Onboarding - 7 dana" (sadrzaj lista je tacan).
--   2) Numericki prefiksi ("1.", "2.", ...) su uklonjeni iz teksta pitanja u
--      sva 4 lista; redosled nosi kolona REDOSLED (Excel top-to-bottom).
--   3) Listovi "60 dana" i "90 dana" imaju duplu numeraciju "3." na dva
--      uzastopna pitanja - reseno iskljucivo kroz REDOSLED 1..6.
--   4) Ocigledna gramaticka greska "Kakavi" -> "Kakvi" (listovi 30/60/90).
-- Znacenje, broj, redosled, tipovi i opcije pitanja NISU menjani.
--
-- Tipovi pitanja: SINGLE_CHOICE i RATING_1_5 su OBAVEZNO='D'; sva TEXT pitanja
-- (slobodan odgovor) su OBAVEZNO='N'.
-- ============================================================================

SET DEFINE OFF
WHENEVER SQLERROR EXIT FAILURE ROLLBACK


-- ----------------------------------------------------------------------------
-- 1) PULS_ANKETA_TIPOVI - tip 'ONBOARDING' (idempotentno)
-- ----------------------------------------------------------------------------
INSERT INTO PULS_ANKETA_TIPOVI (SIFRA, NAZIV, AKTIVAN)
SELECT 'ONBOARDING', N'Onboarding ankete', 'D'
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM PULS_ANKETA_TIPOVI WHERE SIFRA = 'ONBOARDING'
);


-- ----------------------------------------------------------------------------
-- 2) Anketa "Onboarding - 7 dana" - Excel list "7 dana"
--    2 pitanja: 1x SINGLE_CHOICE (5 opcija), 1x TEXT
-- ----------------------------------------------------------------------------
DECLARE
    v_anketa_id     PULS_ANKETE.ID%TYPE;
    v_sekcija_id    PULS_ANKETA_SEKCIJE.ID%TYPE;
    v_pitanje_id    PULS_ANKETA_PITANJA.ID%TYPE;
    v_broj_pitanja  NUMBER;
    c_ocekivano     CONSTANT NUMBER := 2;
BEGIN
    SELECT ID INTO v_anketa_id
      FROM PULS_ANKETE
     WHERE NAZIV = N'Onboarding - 7 dana';

    -- Anketa vec postoji - proveri da struktura odgovara ocekivanoj, ne diraj nista.
    SELECT COUNT(*)
      INTO v_broj_pitanja
      FROM PULS_ANKETA_PITANJA p
      JOIN PULS_ANKETA_SEKCIJE s ON p.SEKCIJA_ID = s.ID
     WHERE s.ANKETA_ID = v_anketa_id;

    IF v_broj_pitanja <> c_ocekivano THEN
        RAISE_APPLICATION_ERROR(-20001,
            'Anketa "Onboarding - 7 dana" vec postoji sa neocekivanom strukturom ('
            || v_broj_pitanja || ' pitanja, ocekivano ' || c_ocekivano
            || ') - prekidam bez izmene.');
    END IF;

EXCEPTION
    WHEN NO_DATA_FOUND THEN
        -- Anketa ne postoji - kreiraj kompletnu strukturu.
        INSERT INTO PULS_ANKETE (
            TIP_SIFRA, NAZIV, ANONIMNA, STATUS, DATUM_POCETKA, DATUM_ZAVRSETKA
        ) VALUES (
            'ONBOARDING', N'Onboarding - 7 dana', 'N', 'ACTIVE',
            CAST(TRUNC(SYSDATE) AS TIMESTAMP), TIMESTAMP '2099-12-31 23:59:59'
        )
        RETURNING ID INTO v_anketa_id;

        INSERT INTO PULS_ANKETA_SEKCIJE (ANKETA_ID, NAZIV, REDOSLED)
        VALUES (v_anketa_id, N'Onboarding - 7 dana', 1)
        RETURNING ID INTO v_sekcija_id;

        -- Pitanje 1 - SINGLE_CHOICE, 5 opcija
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Kako ocenjuješ svoje prve utiske o kompaniji?',
                'SINGLE_CHOICE', 'D', 1)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Odlični', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Dobri', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Zadovoljavajući', 3);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Loši', 4);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Izuzetno loši', 5);

        -- Pitanje 2 - TEXT, slobodan komentar (neobavezno)
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id,
                N'Budi slobodan da sa nama podeliš utiske, sugestije, zapažanja...',
                'TEXT', 'N', 2);

        -- Automatika: 7 dana od zaposlenja, rok 7 dana
        INSERT INTO PULS_ANKETA_AUTOMATIKA (
            ANKETA_ID, DANI_OD_ZAPOSLENJA, ROK_DANA, DATUM_PRIMENE_OD, AKTIVNA
        ) VALUES (
            v_anketa_id, 7, 7, TRUNC(SYSDATE), 'D'
        );
END;
/


-- ----------------------------------------------------------------------------
-- 3) Anketa "Onboarding - 30 dana" - Excel list "30 dana"
--    6 pitanja: 1x SINGLE_CHOICE (5 opcija), 1x SINGLE_CHOICE (3 opcije),
--    2x RATING_1_5, 1x SINGLE_CHOICE (3 opcije), 1x TEXT
-- ----------------------------------------------------------------------------
DECLARE
    v_anketa_id     PULS_ANKETE.ID%TYPE;
    v_sekcija_id    PULS_ANKETA_SEKCIJE.ID%TYPE;
    v_pitanje_id    PULS_ANKETA_PITANJA.ID%TYPE;
    v_broj_pitanja  NUMBER;
    c_ocekivano     CONSTANT NUMBER := 6;
BEGIN
    SELECT ID INTO v_anketa_id
      FROM PULS_ANKETE
     WHERE NAZIV = N'Onboarding - 30 dana';

    SELECT COUNT(*)
      INTO v_broj_pitanja
      FROM PULS_ANKETA_PITANJA p
      JOIN PULS_ANKETA_SEKCIJE s ON p.SEKCIJA_ID = s.ID
     WHERE s.ANKETA_ID = v_anketa_id;

    IF v_broj_pitanja <> c_ocekivano THEN
        RAISE_APPLICATION_ERROR(-20001,
            'Anketa "Onboarding - 30 dana" vec postoji sa neocekivanom strukturom ('
            || v_broj_pitanja || ' pitanja, ocekivano ' || c_ocekivano
            || ') - prekidam bez izmene.');
    END IF;

EXCEPTION
    WHEN NO_DATA_FOUND THEN
        INSERT INTO PULS_ANKETE (
            TIP_SIFRA, NAZIV, ANONIMNA, STATUS, DATUM_POCETKA, DATUM_ZAVRSETKA
        ) VALUES (
            'ONBOARDING', N'Onboarding - 30 dana', 'N', 'ACTIVE',
            CAST(TRUNC(SYSDATE) AS TIMESTAMP), TIMESTAMP '2099-12-31 23:59:59'
        )
        RETURNING ID INTO v_anketa_id;

        INSERT INTO PULS_ANKETA_SEKCIJE (ANKETA_ID, NAZIV, REDOSLED)
        VALUES (v_anketa_id, N'Onboarding - 30 dana', 1)
        RETURNING ID INTO v_sekcija_id;

        -- Pitanje 1 - SINGLE_CHOICE, 5 opcija (Excel "Kakavi" -> "Kakvi")
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Kakvi su ti utisci o kompaniji nakon prvih mesec dana rada?',
                'SINGLE_CHOICE', 'D', 1)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Odlični', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Dobri', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Zadovoljavajući', 3);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Loši', 4);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Izuzetno loši', 5);

        -- Pitanje 2 - SINGLE_CHOICE, 3 opcije
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id,
                N'Da li si dobio/la dovoljno informacija da možeš uspešno da obavljaš svoj posao?',
                'SINGLE_CHOICE', 'D', 2)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'U potpunosti', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Delimično', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Ne', 3);

        -- Pitanje 3 - RATING_1_5
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Kako ocenjuješ podršku svog rukovodioca tokom prvog meseca?',
                'RATING_1_5', 'D', 3);

        -- Pitanje 4 - RATING_1_5
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Kako ocenjuješ podršku kolega i prihvaćenost u timu?',
                'RATING_1_5', 'D', 4);

        -- Pitanje 5 - SINGLE_CHOICE, 3 opcije
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Da li znaš šta se od tebe očekuje na tvojoj poziciji?',
                'SINGLE_CHOICE', 'D', 5)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'U potpunosti', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Delimično', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Ne', 3);

        -- Pitanje 6 - TEXT, slobodan komentar (neobavezno)
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id,
                N'Budi slobodan da sa nama podeliš utiske, sugestije, zapažanja...',
                'TEXT', 'N', 6);

        -- Automatika: 30 dana od zaposlenja, rok 7 dana
        INSERT INTO PULS_ANKETA_AUTOMATIKA (
            ANKETA_ID, DANI_OD_ZAPOSLENJA, ROK_DANA, DATUM_PRIMENE_OD, AKTIVNA
        ) VALUES (
            v_anketa_id, 30, 7, TRUNC(SYSDATE), 'D'
        );
END;
/


-- ----------------------------------------------------------------------------
-- 4) Anketa "Onboarding - 60 dana" - Excel list "60 dana"
--    6 pitanja: 1x SINGLE_CHOICE (5 opcija), 1x SINGLE_CHOICE (5 opcija),
--    1x SINGLE_CHOICE (3 opcije), 1x RATING_1_5, 2x TEXT
--    (Excel: pitanja 3 i 4 oba nose prefiks "3." - reseno kroz REDOSLED)
-- ----------------------------------------------------------------------------
DECLARE
    v_anketa_id     PULS_ANKETE.ID%TYPE;
    v_sekcija_id    PULS_ANKETA_SEKCIJE.ID%TYPE;
    v_pitanje_id    PULS_ANKETA_PITANJA.ID%TYPE;
    v_broj_pitanja  NUMBER;
    c_ocekivano     CONSTANT NUMBER := 6;
BEGIN
    SELECT ID INTO v_anketa_id
      FROM PULS_ANKETE
     WHERE NAZIV = N'Onboarding - 60 dana';

    SELECT COUNT(*)
      INTO v_broj_pitanja
      FROM PULS_ANKETA_PITANJA p
      JOIN PULS_ANKETA_SEKCIJE s ON p.SEKCIJA_ID = s.ID
     WHERE s.ANKETA_ID = v_anketa_id;

    IF v_broj_pitanja <> c_ocekivano THEN
        RAISE_APPLICATION_ERROR(-20001,
            'Anketa "Onboarding - 60 dana" vec postoji sa neocekivanom strukturom ('
            || v_broj_pitanja || ' pitanja, ocekivano ' || c_ocekivano
            || ') - prekidam bez izmene.');
    END IF;

EXCEPTION
    WHEN NO_DATA_FOUND THEN
        INSERT INTO PULS_ANKETE (
            TIP_SIFRA, NAZIV, ANONIMNA, STATUS, DATUM_POCETKA, DATUM_ZAVRSETKA
        ) VALUES (
            'ONBOARDING', N'Onboarding - 60 dana', 'N', 'ACTIVE',
            CAST(TRUNC(SYSDATE) AS TIMESTAMP), TIMESTAMP '2099-12-31 23:59:59'
        )
        RETURNING ID INTO v_anketa_id;

        INSERT INTO PULS_ANKETA_SEKCIJE (ANKETA_ID, NAZIV, REDOSLED)
        VALUES (v_anketa_id, N'Onboarding - 60 dana', 1)
        RETURNING ID INTO v_sekcija_id;

        -- Pitanje 1 - SINGLE_CHOICE, 5 opcija (Excel "Kakavi" -> "Kakvi")
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Kakvi su ti utisci o kompaniji nakon dva meseca rada?',
                'SINGLE_CHOICE', 'D', 1)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Odlični', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Dobri', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Zadovoljavajući', 3);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Loši', 4);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Izuzetno loši', 5);

        -- Pitanje 2 - SINGLE_CHOICE, 5 opcija
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Da li bi Gomex kao poslodavca preporučio prijateljima?',
                'SINGLE_CHOICE', 'D', 2)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Svakako', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Preporučio bih', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Verovatno bih preporučio', 3);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Ne bih preporučio', 4);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Nikako', 5);

        -- Pitanje 3 - SINGLE_CHOICE, 3 opcije
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Koliko si sada samostalan u obavljanju svog posla?',
                'SINGLE_CHOICE', 'D', 3)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'U potpunosti', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Delimično', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Nisam samostalan', 3);

        -- Pitanje 4 - RATING_1_5
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Kako ocenjuješ timski rad u tvom timu?',
                'RATING_1_5', 'D', 4);

        -- Pitanje 5 - TEXT, slobodan odgovor (neobavezno)
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id,
                N'Šta bi ti mogao/la da uradiš da tim radi još bolje i efikasnije?',
                'TEXT', 'N', 5);

        -- Pitanje 6 - TEXT, slobodan komentar (neobavezno)
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id,
                N'Budi slobodan da sa nama podeliš utiske, sugestije, zapažanja...',
                'TEXT', 'N', 6);

        -- Automatika: 60 dana od zaposlenja, rok 7 dana
        INSERT INTO PULS_ANKETA_AUTOMATIKA (
            ANKETA_ID, DANI_OD_ZAPOSLENJA, ROK_DANA, DATUM_PRIMENE_OD, AKTIVNA
        ) VALUES (
            v_anketa_id, 60, 7, TRUNC(SYSDATE), 'D'
        );
END;
/


-- ----------------------------------------------------------------------------
-- 5) Anketa "Onboarding - 90 dana" - Excel list "90 dana"
--    6 pitanja: 1x SINGLE_CHOICE (5 opcija), 1x SINGLE_CHOICE (5 opcija),
--    1x RATING_1_5, 1x SINGLE_CHOICE (3 opcije), 2x TEXT
--    (Excel: pitanja 3 i 4 oba nose prefiks "3." - reseno kroz REDOSLED)
-- ----------------------------------------------------------------------------
DECLARE
    v_anketa_id     PULS_ANKETE.ID%TYPE;
    v_sekcija_id    PULS_ANKETA_SEKCIJE.ID%TYPE;
    v_pitanje_id    PULS_ANKETA_PITANJA.ID%TYPE;
    v_broj_pitanja  NUMBER;
    c_ocekivano     CONSTANT NUMBER := 6;
BEGIN
    SELECT ID INTO v_anketa_id
      FROM PULS_ANKETE
     WHERE NAZIV = N'Onboarding - 90 dana';

    SELECT COUNT(*)
      INTO v_broj_pitanja
      FROM PULS_ANKETA_PITANJA p
      JOIN PULS_ANKETA_SEKCIJE s ON p.SEKCIJA_ID = s.ID
     WHERE s.ANKETA_ID = v_anketa_id;

    IF v_broj_pitanja <> c_ocekivano THEN
        RAISE_APPLICATION_ERROR(-20001,
            'Anketa "Onboarding - 90 dana" vec postoji sa neocekivanom strukturom ('
            || v_broj_pitanja || ' pitanja, ocekivano ' || c_ocekivano
            || ') - prekidam bez izmene.');
    END IF;

EXCEPTION
    WHEN NO_DATA_FOUND THEN
        INSERT INTO PULS_ANKETE (
            TIP_SIFRA, NAZIV, ANONIMNA, STATUS, DATUM_POCETKA, DATUM_ZAVRSETKA
        ) VALUES (
            'ONBOARDING', N'Onboarding - 90 dana', 'N', 'ACTIVE',
            CAST(TRUNC(SYSDATE) AS TIMESTAMP), TIMESTAMP '2099-12-31 23:59:59'
        )
        RETURNING ID INTO v_anketa_id;

        INSERT INTO PULS_ANKETA_SEKCIJE (ANKETA_ID, NAZIV, REDOSLED)
        VALUES (v_anketa_id, N'Onboarding - 90 dana', 1)
        RETURNING ID INTO v_sekcija_id;

        -- Pitanje 1 - SINGLE_CHOICE, 5 opcija (Excel "Kakavi" -> "Kakvi")
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Kakvi su ti utisci o kompaniji nakon tri meseca rada?',
                'SINGLE_CHOICE', 'D', 1)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Odlični', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Dobri', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Zadovoljavajući', 3);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Loši', 4);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Izuzetno loši', 5);

        -- Pitanje 2 - SINGLE_CHOICE, 5 opcija
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Da li bi Gomex kao poslodavca preporučio prijateljima?',
                'SINGLE_CHOICE', 'D', 2)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Svakako', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Preporučio bih', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Verovatno bih preporučio', 3);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Ne bih preporučio', 4);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Nikako', 5);

        -- Pitanje 3 - RATING_1_5
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Kako ocenjuješ kvalitet svog rada?',
                'RATING_1_5', 'D', 3);

        -- Pitanje 4 - SINGLE_CHOICE, 3 opcije
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id, N'Da li je tvoj nadređeni zadovoljan tvojim radom?',
                'SINGLE_CHOICE', 'D', 4)
        RETURNING ID INTO v_pitanje_id;
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Da', 1);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Ne', 2);
        INSERT INTO PULS_ANKETA_OPCIJE (PITANJE_ID, TEKST, REDOSLED) VALUES (v_pitanje_id, N'Nisam siguran/na', 3);

        -- Pitanje 5 - TEXT, slobodan odgovor (neobavezno)
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id,
                N'Šta ti je potrebno da bi posao obavljao još bolje?',
                'TEXT', 'N', 5);

        -- Pitanje 6 - TEXT, slobodan komentar (neobavezno)
        INSERT INTO PULS_ANKETA_PITANJA (SEKCIJA_ID, TEKST, TIP_PITANJA, OBAVEZNO, REDOSLED)
        VALUES (v_sekcija_id,
                N'Budi slobodan da sa nama podeliš utiske, sugestije, zapažanja...',
                'TEXT', 'N', 6);

        -- Automatika: 90 dana od zaposlenja, rok 7 dana
        INSERT INTO PULS_ANKETA_AUTOMATIKA (
            ANKETA_ID, DANI_OD_ZAPOSLENJA, ROK_DANA, DATUM_PRIMENE_OD, AKTIVNA
        ) VALUES (
            v_anketa_id, 90, 7, TRUNC(SYSDATE), 'D'
        );
END;
/


-- ----------------------------------------------------------------------------
-- 6) Zavrsna provera pre COMMIT-a: sve 4 ankete moraju postojati (ACTIVE,
--    neanonimne, tip ONBOARDING, ocekivan broj pitanja, bez ciljeva) i svaka
--    mora imati TACNO JEDNO svoje AKTIVNA='D' pravilo za svoj milestone.
--    Ako pravilo nedostaje (npr. milestone je vec zauzet DRUGOM anketom i INSERT
--    iz gornjeg bloka nije izvrsen jer anketa vec postoji), prekini - ROLLBACK
--    preko WHENEVER SQLERROR, bez izmene postojeceg pravila.
-- ----------------------------------------------------------------------------
DECLARE
    v_cnt  NUMBER;
BEGIN
    FOR rec IN (
        SELECT NAZIV, DANI, PITANJA FROM (
            SELECT N'Onboarding - 7 dana'  AS NAZIV,  7 AS DANI, 2 AS PITANJA FROM DUAL
            UNION ALL SELECT N'Onboarding - 30 dana', 30, 6 FROM DUAL
            UNION ALL SELECT N'Onboarding - 60 dana', 60, 6 FROM DUAL
            UNION ALL SELECT N'Onboarding - 90 dana', 90, 6 FROM DUAL
        )
    ) LOOP
        SELECT COUNT(*)
          INTO v_cnt
          FROM PULS_ANKETE a
         WHERE a.NAZIV = rec.NAZIV
           AND a.TIP_SIFRA = 'ONBOARDING'
           AND a.ANONIMNA = 'N'
           AND a.STATUS = 'ACTIVE'
           AND rec.PITANJA = (
                SELECT COUNT(*)
                  FROM PULS_ANKETA_PITANJA p
                  JOIN PULS_ANKETA_SEKCIJE s ON p.SEKCIJA_ID = s.ID
                 WHERE s.ANKETA_ID = a.ID)
           AND NOT EXISTS (
                SELECT 1 FROM PULS_ANKETA_CILJEVI c WHERE c.ANKETA_ID = a.ID)
           AND 1 = (
                SELECT COUNT(*)
                  FROM PULS_ANKETA_AUTOMATIKA au
                 WHERE au.ANKETA_ID = a.ID
                   AND au.AKTIVNA = 'D'
                   AND au.DANI_OD_ZAPOSLENJA = rec.DANI
                   AND au.ROK_DANA = 7);

        IF v_cnt <> 1 THEN
            RAISE_APPLICATION_ERROR(-20002,
                'Zavrsna provera nije prosla za anketu "' || rec.NAZIV
                || '" (milestone ' || rec.DANI || ' dana) - ocekivano tacno 1 '
                || 'ACTIVE neanonimna anketa sa ' || rec.PITANJA || ' pitanja, bez '
                || 'ciljeva i sa tacno jednim aktivnim pravilom. Prekidam - ROLLBACK.');
        END IF;
    END LOOP;
END;
/


-- Jedini COMMIT u skripti - tek posle uspesne provere sve 4 ankete i 4 pravila.
COMMIT;

"""Admin CONFIGURATION modul: read (batch, bez zaključavanja) + write (jedna
transakcija, SELECT FOR UPDATE, jedan commit) nad allowlist-om iz
app.core.configuration_definitions. Nikada ne dira redove van te allowlist-e."""

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.configuration_definitions import (
    ALLOWED_CONFIGURATION_KEYS,
    CONFIGURATION_DEFINITIONS,
    compare_versions,
)
from app.core.exceptions import ConfigurationKeyNotAllowedError, ValidationBusinessError
from app.models.konfiguracija import Konfiguracija
from app.models.korisnik import Korisnik
from app.repositories.admin_configuration_repository import AdminConfigurationRepository
from app.repositories.audit_repository import AuditRepository
from app.services.audit_service import AuditAction, AuditService

CURRENT_VERSION_KEY = "CURRENT_VERSION"
MIN_SUPPORTED_VERSION_KEY = "MIN_SUPPORTED_VERSION"
_VERSION_PAIR_KEYS = (CURRENT_VERSION_KEY, MIN_SUPPORTED_VERSION_KEY)


class AdminConfigurationService:
    def __init__(
        self,
        db: Session,
        repository: AdminConfigurationRepository | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.repo = repository or AdminConfigurationRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=get_settings().audit_source
        )

    # ---------------------------------------------------------------- citanje
    def list_configuration(self) -> dict:
        rows = self.repo.list_active_by_keys(list(ALLOWED_CONFIGURATION_KEYS))
        items = []
        for key in ALLOWED_CONFIGURATION_KEYS:
            definition = CONFIGURATION_DEFINITIONS[key]
            row = rows.get(key)
            if row is not None:
                items.append(
                    {
                        "kljuc": key,
                        "vrednost": row.vrednost,
                        "tip_podatka": definition.tip_podatka,
                        "opis": definition.opis,
                        "koristi_podrazumevanu_vrednost": False,
                        "izmenio_korisnik_id": row.izmenio_korisnik_id,
                    }
                )
            else:
                items.append(
                    {
                        "kljuc": key,
                        "vrednost": definition.default,
                        "tip_podatka": definition.tip_podatka,
                        "opis": definition.opis,
                        "koristi_podrazumevanu_vrednost": True,
                        "izmenio_korisnik_id": None,
                    }
                )
        return {"items": items}

    # --------------------------------------------------------------- izmena
    def update_configuration(self, actor: Korisnik, key: str, vrednost: str | None) -> dict:
        normalized_key = key.strip().upper()
        definition = CONFIGURATION_DEFINITIONS.get(normalized_key)
        if definition is None:
            raise ConfigurationKeyNotAllowedError()

        if vrednost is None:
            if not definition.nullable:
                raise ValidationBusinessError(f"{normalized_key} ne sme biti null.")
            normalized_value = None
        else:
            normalized_value = definition.validate(vrednost)

        try:
            if normalized_key in _VERSION_PAIR_KEYS:
                # Zakljucaj OBA verzijska kljuca zajedno (stabilan redosled po KLJUC u
                # repository-ju) i proveri konzistentnost nad ZAKLJUCANIM vrednostima -
                # nezakljucani get_active_value bi mogao videti vrednost koju paralelni
                # PUT jos uvek menja.
                locked = self.repo.get_for_update_batch(list(_VERSION_PAIR_KEYS))
                self._validate_version_consistency_locked(normalized_key, normalized_value, locked)
                row = locked.get(normalized_key)
            else:
                row = self.repo.get_for_update(normalized_key)

            old_effective = row.vrednost if (row is not None and row.aktivna == "D") else definition.default
            is_noop = old_effective == normalized_value

            if row is None:
                row = Konfiguracija(kljuc=normalized_key)
                self.db.add(row)
            row.vrednost = normalized_value
            row.tip_podatka = definition.tip_podatka
            row.opis = definition.opis
            row.aktivna = "D"
            row.izmenio_korisnik_id = actor.id

            if not is_noop:
                # DETALJI namerno NE sadrze staru/novu vrednost - moglo bi biti
                # DOWNLOAD_URL ili druga vrednost koja ne sme zavrsiti u audit logu.
                self.audit_service.log(
                    AuditAction.ADMIN_CONFIGURATION_UPDATED,
                    korisnik_id=actor.id,
                    platni_broj=actor.platni_broj,
                    tip_entiteta="KONFIGURACIJA",
                    entitet_id=normalized_key,
                )

            # Response se sastavlja PRE commit-a - posle commit-a nema DB upita.
            result = {
                "kljuc": normalized_key,
                "vrednost": normalized_value,
                "tip_podatka": definition.tip_podatka,
                "opis": definition.opis,
                "koristi_podrazumevanu_vrednost": False,
                "izmenio_korisnik_id": actor.id,
            }
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def _locked_effective_value(row: Konfiguracija | None, key: str) -> str:
        if row is not None and row.aktivna == "D":
            return row.vrednost
        return CONFIGURATION_DEFINITIONS[key].default

    def _validate_version_consistency_locked(
        self, key: str, normalized_value: str | None, locked: dict[str, Konfiguracija]
    ) -> None:
        current_effective = self._locked_effective_value(locked.get(CURRENT_VERSION_KEY), CURRENT_VERSION_KEY)
        min_effective = self._locked_effective_value(
            locked.get(MIN_SUPPORTED_VERSION_KEY), MIN_SUPPORTED_VERSION_KEY
        )
        if key == CURRENT_VERSION_KEY:
            if compare_versions(normalized_value, min_effective) < 0:
                raise ValidationBusinessError(
                    "CURRENT_VERSION ne sme biti spušten ispod MIN_SUPPORTED_VERSION."
                )
        elif key == MIN_SUPPORTED_VERSION_KEY:
            if compare_versions(normalized_value, current_effective) > 0:
                raise ValidationBusinessError(
                    "MIN_SUPPORTED_VERSION ne sme biti veći od CURRENT_VERSION."
                )

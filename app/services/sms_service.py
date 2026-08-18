import datetime
import logging
from abc import ABC, abstractmethod

from sqlalchemy.engine import Engine

from app.core.phone import is_valid_local_mobile_phone, mask_phone

logger = logging.getLogger("puls.sms")

ORACLE_MSG_HEAD = "Gomex Puls"


class SmsProvider(ABC):
    @abstractmethod
    def send_sms(self, phone_number: str, message: str) -> bool:
        """Returns True if the message was accepted for delivery.

        Implementations MUST NOT log the message body, the temporary password,
        the reset code, or the full phone number.
        """


class ConsoleSmsProvider(SmsProvider):
    """Development-time provider. Logs only a masked phone and delivery status,
    never the message body (which contains the password or reset code)."""

    def send_sms(self, phone_number: str, message: str) -> bool:
        logger.info("SMS event=send channel=console to=%s status=accepted", mask_phone(phone_number))
        return True


class OracleProcedureSmsProvider(SmsProvider):
    """Sends SMS through the existing PORTAL.MSG_SALJI procedure."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def send_sms(self, phone_number: str, message: str) -> bool:
        if not is_valid_local_mobile_phone(phone_number):
            logger.warning(
                "SMS event=send channel=oracle to=%s status=rejected_invalid_phone",
                mask_phone(phone_number),
            )
            return False

        raw_conn = self.engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.callproc(
                "PORTAL.MSG_SALJI",
                ["SMS", phone_number.strip(), datetime.date.today(), ORACLE_MSG_HEAD, message],
            )
            raw_conn.commit()
            logger.info("SMS event=send channel=oracle to=%s status=accepted", mask_phone(phone_number))
            return True
        except Exception:
            raw_conn.rollback()
            logger.exception(
                "SMS event=send channel=oracle to=%s status=failed", mask_phone(phone_number)
            )
            return False
        finally:
            raw_conn.close()


def get_sms_provider(provider_name: str, engine: Engine | None = None) -> SmsProvider:
    if provider_name == "console":
        return ConsoleSmsProvider()
    if provider_name == "oracle":
        if engine is None:
            raise ValueError("Oracle SMS provider requires a database engine.")
        return OracleProcedureSmsProvider(engine)
    raise ValueError(f"Unknown SMS provider: {provider_name}")

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _parse_dsn(dsn: str) -> tuple[str, int, str]:
    """DSN format expected from .env: host:port/service_name (Oracle Easy Connect)."""
    host_port, _, service_name = dsn.partition("/")
    host, _, port = host_port.partition(":")
    if not service_name:
        raise ValueError(f"DB_DSN must be in 'host:port/service_name' format, got: {dsn!r}")
    return host, int(port), service_name


def _build_engine():
    settings = get_settings()
    host, port, service_name = _parse_dsn(settings.db_dsn)

    url = URL.create(
        "oracle+oracledb",
        username=settings.db_user,
        password=settings.db_password,
        host=host,
        port=port,
        query={"service_name": service_name},
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

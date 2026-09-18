import pytest

from app.services import question_types


@pytest.fixture(autouse=True)
def _question_types_without_database():
    """Testovi ne citaju PULS_ANKETA_TIPOVI_PITANJA - registar koristi ugradjene tipove."""
    question_types.use_builtin_types()
    yield
    question_types.use_builtin_types()

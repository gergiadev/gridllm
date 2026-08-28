import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def examples() -> Path:
    return ROOT / "examples" / "vm"


@pytest.fixture
def quiet_logger() -> logging.Logger:
    logger = logging.getLogger("tests")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger

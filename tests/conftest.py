from pathlib import Path
import pytest
from app.core.scenarios import Catalog
from app.services.actions import MockBackend

@pytest.fixture
def catalog():
    return Catalog(Path(__file__).resolve().parents[1] / 'case' / 'voice_router_dataset')

@pytest.fixture
def backend(catalog):
    return MockBackend(catalog)

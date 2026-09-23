from pathlib import Path
import pytest
from app.core.scenarios import Catalog
from app.services.actions import MockBackend

@pytest.fixture(autouse=True)
def isolated_session_archive(tmp_path, monkeypatch):
    # Tests must never read, close or overwrite real user conversation archives.
    from app.config import settings
    monkeypatch.setattr(settings, 'session_archive_dir', tmp_path / 'sessions')

@pytest.fixture
def catalog():
    return Catalog(Path(__file__).resolve().parents[1] / 'case' / 'voice_router_dataset')

@pytest.fixture
def backend(catalog):
    return MockBackend(catalog)

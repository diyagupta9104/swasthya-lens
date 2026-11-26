import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from assistant import METRICS, CONSULTATIONS
from server import SESSIONS


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(config, 'api_key', lambda: '')
    monkeypatch.setattr(config, 'SEMANTIC', False)
    METRICS.clear()
    CONSULTATIONS.clear()
    SESSIONS.clear()


@pytest.fixture
def report():
    return (config.ROOT / 'sample_report.txt').read_text(encoding='utf-8')

import pytest
from optipool.config import Settings
from optipool.demo import DemoCollector


@pytest.fixture
def settings(tmp_path):
    return Settings(database=str(tmp_path / "test.db"))


@pytest.fixture
def saved(settings):
    demo = DemoCollector(settings)
    pool = demo.discover()[0][0]
    return {"id": "saved-snapshot", "saved_at": 1728000000, **demo.collect(pool)}

"""Synthetic external monitoring response boundary; no Google credentials/network."""

from optipool.app import create_app
from optipool.config import load_settings
from optipool.demo import DemoCollector
from test_upstream_history import adapter, configured


class UpstreamCollector(DemoCollector):
    def __init__(self, settings):
        super().__init__(settings)
        self.settings = configured(settings)
        self.calls = 0
        self.cloud_requests = []
        self.fail = False

    def discover(self):
        pools, projects, errors = super().discover()
        return pools[:2], projects, errors

    def collect(self, pool):
        self.calls += 1
        collector, core, requests = adapter(
            self.settings, {"pool": pool}, failure="permission denied" if self.fail else None
        )
        core["metrics"] = collector.metrics(pool, core)
        core["pricing"] = {"components": [], "source": "Synthetic unavailable prices"}
        self.cloud_requests.extend(requests)
        return core


def upstream_app():
    settings = load_settings()
    return create_app(settings, UpstreamCollector(settings))

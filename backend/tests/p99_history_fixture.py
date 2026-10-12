"""Synthetic rollout boundary for saved-data API and browser journeys."""

from optipool.app import create_app
from optipool.config import load_settings
from optipool.demo import DemoCollector


class RolloutCollector(DemoCollector):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls = 0

    def discover(self):
        pools, projects, errors = super().discover()
        return pools[:1], projects, errors

    def collect(self, pool):
        self.calls += 1
        saved = super().collect(pool)
        uid = saved["context"]["pods"][0]["uid"]
        for sample in saved["metrics"]["samples"]:
            if sample["replica"] == uid:
                sample["cpu"] = 9
        if self.calls > 1:
            saved["context"]["pods"] = [p for p in saved["context"]["pods"] if p["uid"] != uid]
            saved["metrics"]["samples"] = [p for p in saved["metrics"]["samples"] if p["replica"] != uid]
            saved["metrics"]["replica_evidence"].pop(uid)
            saved["workloads"][0]["pool_replicas"] = 2
            saved["workloads"][0]["running"] = 2
        return saved


def history_app():
    settings = load_settings()
    return create_app(settings, RolloutCollector(settings))

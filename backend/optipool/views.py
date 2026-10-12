"""Bounded immutable response cache; SQLite snapshot IDs are the freshness authority."""

import json
import threading
from collections import OrderedDict

from .metrics import summarize
from .pods import selected_pods


class SavedViews:
    def __init__(
        self,
        store,
        minimum=20,
        max_bytes=64 * 1024**2,
        minimum_observation_seconds=86400,
        minimum_coverage=0.9,
        risk_policy=None,
    ):
        self.store, self.minimum, self.max_bytes = store, minimum, max_bytes
        self.risk_policy = dict(risk_policy or {})
        self.minimum_observation_seconds, self.minimum_coverage = (
            minimum_observation_seconds,
            minimum_coverage,
        )
        self.entries = OrderedDict()
        self.bytes = 0
        # Stripes deduplicate simultaneous cold reads without an unbounded lock registry.
        self.build_locks = [threading.Lock() for _ in range(16)]
        self.lock = threading.Lock()

    def get(self, pool_id, days, snapshot_id=None):
        sid = snapshot_id or self.store.latest_snapshot_id(pool_id)
        if snapshot_id and self.store.snapshot_pool_id(snapshot_id) != pool_id:
            return None
        if sid is None:
            return None
        key = (
            sid,
            days,
            self.minimum,
            self.minimum_observation_seconds,
            self.minimum_coverage,
            tuple(sorted(self.risk_policy.items())),
        )
        with self.build_locks[hash(key) % len(self.build_locks)]:
            with self.lock:
                if key in self.entries:
                    self.entries.move_to_end(key)
                    return self.entries[key]
            value = self.store.snapshot(snapshot_id=sid)
            if value is None:
                return None
            view = {
                **{k: v for k, v in value.items() if k not in {"metrics", "context"}},
                "usage": summarize(
                    value,
                    days,
                    self.minimum,
                    self.minimum_observation_seconds,
                    self.minimum_coverage,
                    self.risk_policy,
                ),
                "pods": selected_pods(value),
                "context_warnings": value.get("context", {}).get("uncertainties", []),
                "pending_demand": len(value.get("context", {}).get("pending", [])),
            }
            content = json.dumps(view, separators=(",", ":"), allow_nan=False).encode()
            with self.lock:
                if len(content) <= self.max_bytes:
                    while self.entries and self.bytes + len(content) > self.max_bytes:
                        self.bytes -= len(self.entries.popitem(last=False)[1])
                    self.entries[key] = content
                    self.bytes += len(content)
            return content

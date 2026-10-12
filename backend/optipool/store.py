"""Single SQLite owner, short atomic publications; network work stays outside transactions."""

import json
import sqlite3
import threading
import time
import uuid
import zlib
from pathlib import Path

from filelock import FileLock, Timeout


def pack(value):
    return zlib.compress(json.dumps(value, separators=(",", ":"), allow_nan=False).encode())


def unpack(value):
    return json.loads(zlib.decompress(value))


def overview(snapshot):
    nodes = snapshot["nodes"]
    factor = 0.8 if snapshot["pool"]["environment"] == "production" else 0.9
    pool = {
        k: v
        for k, v in snapshot["pool"].items()
        if k not in {"snapshot_summary", "snapshot_pool", "snapshot_id", "snapshot_at", "available"}
    }
    return {
        "pool": pool,
        "summary": {
            "node_count": len(nodes),
            "cpu": sum(n["requested"]["cpu"] for n in nodes),
            "memory": sum(n["requested"]["memory"] for n in nodes),
            "cpu_allocatable": sum(n["allocatable"]["cpu"] for n in nodes),
            "memory_allocatable": sum(n["allocatable"]["memory"] for n in nodes),
            "violations": sum(
                any(n["requested"][k] > n["allocatable"][k] * factor for k in ["cpu", "memory"])
                for n in nodes
            ),
        },
    }


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.owner_lock = FileLock(str(Path(path).resolve()) + ".owner.lock", thread_local=False)
        try:
            self.owner_lock.acquire(timeout=0)
        except Timeout:
            raise ValueError("SQLite already has an OptiPool owner; run one application instance") from None
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        if self.db.execute("SELECT name FROM sqlite_master WHERE name='schema_version'").fetchone():
            version = self.db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            if version != 1:
                self.db.close()
                self.owner_lock.release()
                raise ValueError(f"Unsupported database schema version: {version}")
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            PRAGMA busy_timeout=15000;
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
            INSERT OR IGNORE INTO schema_version VALUES (1);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS inventory (
                id TEXT PRIMARY KEY, payload BLOB NOT NULL, available INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY, pool_id TEXT NOT NULL, created REAL NOT NULL, payload BLOB NOT NULL);
            CREATE INDEX IF NOT EXISTS snapshots_pool ON snapshots(pool_id, created DESC);
            CREATE TABLE IF NOT EXISTS snapshot_overviews (
                snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE, payload BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshot_core (
                snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE, payload BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, error TEXT, actor TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS active_job ON jobs(scope,kind)
                WHERE state IN ('queued','running');
            CREATE INDEX IF NOT EXISTS jobs_history ON jobs(scope,kind,created DESC);
            CREATE TABLE IF NOT EXISTS estimates (
                id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                created REAL NOT NULL, actor TEXT NOT NULL, input BLOB NOT NULL, result BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS estimate_details (
                estimate_id TEXT PRIMARY KEY REFERENCES estimates(id) ON DELETE CASCADE, kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS estimate_sources (
                estimate_id TEXT REFERENCES estimates(id) ON DELETE CASCADE,
                snapshot_id TEXT REFERENCES snapshots(id) ON DELETE CASCADE,
                PRIMARY KEY (estimate_id, snapshot_id));
            CREATE INDEX IF NOT EXISTS estimate_sources_snapshot ON estimate_sources(snapshot_id);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, created REAL NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, scope TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS estimates_snapshot ON estimates(snapshot_id,created DESC);
        """)
        self.db.execute(
            "UPDATE jobs SET state='failed',error='Collection interrupted by restart',updated=? "
            "WHERE state IN ('queued','running')",
            (time.time(),),
        )
        self.db.commit()
        # Backfill latest local prerelease snapshots once; no network reads or new observations.
        latest = self.db.execute(
            "SELECT id,payload FROM snapshots s WHERE id NOT IN "
            "(SELECT snapshot_id FROM snapshot_overviews) AND created="
            "(SELECT MAX(created) FROM snapshots WHERE pool_id=s.pool_id)"
        ).fetchall()
        for row in latest:
            with self.db:
                self.db.execute(
                    "INSERT INTO snapshot_overviews VALUES (?,?)",
                    (row["id"], pack(overview(unpack(row["payload"])))),
                )

    def close(self):
        with self.lock:
            self.db.close()
            self.owner_lock.release()

    def metadata(self, key):
        with self.lock:
            row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def set_metadata(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, str(value)))

    def publish_inventory(self, pools, successful_projects, errors):
        # Only mark resources deleted in projects whose complete GKE discovery succeeded.
        with self.lock, self.db:
            for row in self.db.execute("SELECT id,payload FROM inventory").fetchall():
                if unpack(row["payload"])["project"] in successful_projects:
                    self.db.execute("UPDATE inventory SET available=0 WHERE id=?", (row["id"],))
            for pool in pools:
                self.db.execute("INSERT OR REPLACE INTO inventory VALUES (?,?,1)", (pool["id"], pack(pool)))
            self.db.execute(
                "INSERT OR REPLACE INTO metadata VALUES ('inventory_errors',?)", (json.dumps(errors),)
            )
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('inventory_at',?)", (str(time.time()),))

    def inventory(self, pool_id=None):
        # One indexed query; never load full metric histories for inventory or pool lookup.
        with self.lock:
            rows = self.db.execute(
                "SELECT i.*,s.id AS snapshot_id,s.created AS snapshot_at,o.payload AS overview "
                "FROM inventory i LEFT JOIN snapshots s ON s.id=(SELECT id FROM snapshots "
                "WHERE pool_id=i.id ORDER BY created DESC LIMIT 1) "
                "LEFT JOIN snapshot_overviews o ON o.snapshot_id=s.id "
                + ("WHERE i.id=? " if pool_id is not None else "")
                + "ORDER BY i.id",
                (pool_id,) if pool_id is not None else (),
            ).fetchall()
        result = []
        # Decode outside the SQLite connection lock so readers do not block publications.
        for row in rows:
            item = unpack(row["payload"])
            item.update(
                available=bool(row["available"]),
                snapshot_id=row["snapshot_id"],
                snapshot_at=row["snapshot_at"],
            )
            if row["overview"]:
                saved = unpack(row["overview"])
                item["snapshot_pool"], item["snapshot_summary"] = saved["pool"], saved["summary"]
            result.append(item)
        return result

    def pool(self, pool_id):
        pool = next(iter(self.inventory(pool_id)), None)
        return (
            {k: v for k, v in pool.items() if k not in {"snapshot_pool", "snapshot_summary"}}
            if pool
            else None
        )

    def publish_snapshot(self, pool_id, payload):
        if payload.get("core_complete") is not True or payload.get("pool", {}).get("id") != pool_id:
            raise ValueError("Incomplete or mismatched core snapshot cannot be published")
        ident = str(uuid.uuid4())
        packed, header = pack(payload), pack(overview(payload))
        core = pack({k: v for k, v in payload.items() if k != "metrics"})
        with self.lock, self.db:
            self.db.execute("INSERT INTO snapshots VALUES (?,?,?,?)", (ident, pool_id, time.time(), packed))
            self.db.execute("INSERT INTO snapshot_overviews VALUES (?,?)", (ident, header))
            self.db.execute("INSERT INTO snapshot_core VALUES (?,?)", (ident, core))
        return ident

    def snapshot(self, pool_id=None, snapshot_id=None, include_metrics=True):
        with self.lock:
            query = (
                "SELECT s.id,s.created,"
                + ("s.payload" if include_metrics else "COALESCE(c.payload,s.payload)")
                + " AS payload FROM snapshots s "
            )
            if not include_metrics:
                query += "LEFT JOIN snapshot_core c ON c.snapshot_id=s.id "
            if snapshot_id:
                row = self.db.execute(query + "WHERE s.id=?", (snapshot_id,)).fetchone()
            else:
                row = self.db.execute(
                    query + "WHERE s.pool_id=? ORDER BY s.created DESC LIMIT 1", (pool_id,)
                ).fetchone()
        if not row:
            return None
        result = {**unpack(row["payload"]), "id": row["id"], "saved_at": row["created"]}
        if not include_metrics:
            result.pop("metrics", None)  # Older snapshots fall back to the original immutable blob.
        return result

    def snapshots(self, pool_id, limit=100):
        with self.lock:
            rows = self.db.execute(
                "SELECT id,created FROM snapshots WHERE pool_id=? ORDER BY created DESC LIMIT ?",
                (pool_id, limit),
            ).fetchall()
        return [{"id": r["id"], "saved_at": r["created"]} for r in rows]

    def latest_snapshot_id(self, pool_id):
        with self.lock:
            row = self.db.execute(
                "SELECT id FROM snapshots WHERE pool_id=? ORDER BY created DESC LIMIT 1", (pool_id,)
            ).fetchone()
        return row["id"] if row else None

    def snapshot_pool_id(self, snapshot_id):
        with self.lock:
            row = self.db.execute("SELECT pool_id FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        return row["pool_id"] if row else None

    def enqueue(self, scope, kind, actor):
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM jobs WHERE scope=? AND kind=? AND state IN ('queued','running')", (scope, kind)
            ).fetchone()
            if row:
                return dict(row), False
            ident, now = str(uuid.uuid4()), time.time()
            self.db.execute(
                "INSERT INTO jobs VALUES (?,?,?,'queued',?,?,NULL,?)", (ident, scope, kind, now, now, actor)
            )
            self.db.execute(
                "INSERT INTO audit(created,actor,action,scope) VALUES (?,?,?,?)", (now, actor, kind, scope)
            )
            return self.job(ident), True

    def job(self, ident):
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
            return dict(row) if row else None

    def latest_job(self, scope, kind):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM jobs WHERE scope=? AND kind=? ORDER BY created DESC LIMIT 1", (scope, kind)
            ).fetchone()
            return dict(row) if row else None

    def update_job(self, ident, state, error=None):
        with self.lock, self.db:
            self.db.execute(
                "UPDATE jobs SET state=?,updated=?,error=? WHERE id=?", (state, time.time(), error, ident)
            )

    def save_estimate(self, snapshot_id, inputs, result, actor, sources=None):
        ident = str(uuid.uuid4())
        packed_input, packed_result = pack(inputs), pack(result)
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO estimates VALUES (?,?,?,?,?,?)",
                (ident, snapshot_id, time.time(), actor, packed_input, packed_result),
            )
            self.db.execute(
                "INSERT INTO estimate_details VALUES (?,?)", (ident, result.get("kind", "capacity"))
            )
            self.db.executemany(
                "INSERT INTO estimate_sources VALUES (?,?)",
                [(ident, sid) for sid in sorted(set(sources or []) | {snapshot_id})],
            )
            self.db.execute(
                "INSERT INTO audit(created,actor,action,scope) VALUES (?,?,?,?)",
                (time.time(), actor, "estimate", snapshot_id),
            )
        return ident

    def estimates(self, pool_id):
        with self.lock:
            rows = self.db.execute(
                "SELECT e.* FROM estimates e JOIN snapshots s ON s.id=e.snapshot_id "
                "LEFT JOIN estimate_details d ON d.estimate_id=e.id "
                "WHERE s.pool_id=? AND COALESCE(d.kind,'capacity')!='node_pool_design' "
                "ORDER BY e.created DESC LIMIT 20",
                (pool_id,),
            ).fetchall()
        return self.estimate_records(rows)

    def designs(self, pool_ids):
        if not pool_ids:
            return []
        with self.lock:
            rows = self.db.execute(
                "SELECT e.* FROM estimates e JOIN snapshots s ON s.id=e.snapshot_id "
                "JOIN estimate_details d ON d.estimate_id=e.id "
                "WHERE d.kind='node_pool_design' AND s.pool_id IN ("
                + ",".join("?" for _ in pool_ids)
                + ") ORDER BY e.created DESC LIMIT 20",
                pool_ids,
            ).fetchall()
        return self.estimate_records(rows)

    @staticmethod
    def estimate_records(rows):
        return [
            {
                "id": r["id"],
                "snapshot_id": r["snapshot_id"],
                "created": r["created"],
                "input": unpack(r["input"]),
                "result": unpack(r["result"]),
            }
            for r in rows
        ]

    def prune(self):
        cutoff = time.time() - 30 * 86400
        with self.lock, self.db:
            self.db.execute("DELETE FROM estimates WHERE created<?", (cutoff,))
            self.db.execute(
                "DELETE FROM snapshots WHERE created<? AND id NOT IN "
                "(SELECT snapshot_id FROM estimates) AND id NOT IN "
                "(SELECT snapshot_id FROM estimate_sources) AND id NOT IN "
                "(SELECT id FROM snapshots s WHERE created=(SELECT MAX(created) FROM snapshots "
                "WHERE pool_id=s.pool_id))",
                (cutoff,),
            )
            self.db.execute(
                "DELETE FROM jobs WHERE updated<? AND state NOT IN ('queued','running')", (cutoff,)
            )
            self.db.execute("DELETE FROM audit WHERE created<?", (cutoff,))

    def backup(self, destination):
        target = sqlite3.connect(destination)
        try:
            with self.lock:
                self.db.backup(target)
        finally:
            target.close()

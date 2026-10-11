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
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, error TEXT, actor TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS active_job ON jobs(scope,kind)
                WHERE state IN ('queued','running');
            CREATE TABLE IF NOT EXISTS estimates (
                id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                created REAL NOT NULL, actor TEXT NOT NULL, input BLOB NOT NULL, result BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, created REAL NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, scope TEXT NOT NULL);
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

    def inventory(self):
        with self.lock:
            rows = self.db.execute("SELECT * FROM inventory ORDER BY id").fetchall()
            result = []
            for row in rows:
                item = unpack(row["payload"])
                item["available"] = bool(row["available"])
                snap = self.db.execute(
                    "SELECT id,created FROM snapshots WHERE pool_id=? ORDER BY created DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                item["snapshot_id"] = snap["id"] if snap else None
                item["snapshot_at"] = snap["created"] if snap else None
                if snap:
                    header = self.db.execute(
                        "SELECT payload FROM snapshot_overviews WHERE snapshot_id=?", (snap["id"],)
                    ).fetchone()
                    if header:
                        saved = unpack(header["payload"])
                        item["snapshot_pool"], item["snapshot_summary"] = saved["pool"], saved["summary"]
                result.append(item)
            return result

    def pool(self, pool_id):
        pool = next((p for p in self.inventory() if p["id"] == pool_id), None)
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
        with self.lock, self.db:
            self.db.execute("INSERT INTO snapshots VALUES (?,?,?,?)", (ident, pool_id, time.time(), packed))
            self.db.execute("INSERT INTO snapshot_overviews VALUES (?,?)", (ident, header))
        return ident

    def snapshot(self, pool_id=None, snapshot_id=None):
        with self.lock:
            if snapshot_id:
                row = self.db.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            else:
                row = self.db.execute(
                    "SELECT * FROM snapshots WHERE pool_id=? ORDER BY created DESC LIMIT 1", (pool_id,)
                ).fetchone()
        if not row:
            return None
        return {**unpack(row["payload"]), "id": row["id"], "saved_at": row["created"]}

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

    def save_estimate(self, snapshot_id, inputs, result, actor):
        ident = str(uuid.uuid4())
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO estimates VALUES (?,?,?,?,?,?)",
                (ident, snapshot_id, time.time(), actor, pack(inputs), pack(result)),
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
                "WHERE s.pool_id=? ORDER BY e.created DESC LIMIT 20",
                (pool_id,),
            ).fetchall()
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

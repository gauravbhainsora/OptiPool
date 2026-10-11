# Operations, persistence and recovery

SQLite uses WAL, foreign keys, a busy timeout and serialized short writes. Collection runs outside transactions. One collector job runs at a time; duplicate same-pool requests join the active durable job. Interrupted jobs become failed after restart, and staged observations are never published. The latest successful snapshot is retained indefinitely. Old history and estimates expire after 30 days, with snapshots pinned by retained estimates; pruning runs after successful collections.

Initial import is recorded in the database. Later restarts reuse saved data. Inventory discovery and selected-pool refreshes are explicit actions. Collection failures are reported by scope; core failures preserve previous data and optional metrics/price failures leave those features unavailable. Structured collection logs include job ID, state and elapsed time; SQLite audit rows record actor/action/scope and saved estimates pin their inputs.

## Backup

Use SQLite's backup API from the same host as the DB owner. Never copy only the live `.db` while ignoring WAL state. The backup tool opens a read-only source and refuses an existing destination:

```bash
.venv/bin/python scripts/backup.py data/optipool.db backups/optipool-YYYYMMDD-HHMM.db
```

Create the destination directory beforehand. Move the complete backup off the data volume to your approved durable storage. Schedule backups externally; no cloud bucket uploads occur automatically. Account for sensitive inventory/identity data in access and retention policies.

In GKE, execute the packaged script in the owning Pod, writing temporarily to `/tmp`, then copy the completed backup to approved storage. `kubectl cp` requires tar in the image; alternatively use `kubectl exec` with a binary file transfer tool approved by your operators. Avoid streaming a live DB file itself. The container includes `scripts/backup.py`.

For example, using an explicitly selected context and the current owning Pod:

```bash
kubectl --context HOST_CONTEXT -n optipool exec POD_NAME -- python scripts/backup.py /data/optipool.db /tmp/optipool-backup.db
kubectl --context HOST_CONTEXT -n optipool cp POD_NAME:/tmp/optipool-backup.db ./optipool-backup.db
```

Transfer that completed backup to approved off-volume storage. Do not run another database-owning application release to perform a backup.

## Restore

1. Stop the sole application process (or scale its Deployment to zero for maintenance).
2. Keep the old DB and WAL/SHM files together as a recoverable pre-restore copy.
3. Restore a consistent backup to the configured DB path. Remove old sidecars from that path by moving them into the preserved pre-restore directory; do not mix old WAL with the restored DB.
4. Set owner/group permissions to app UID/GID 10001 on a GKE volume.
5. Check `PRAGMA integrity_check` and confirm schema compatibility, then start the compatible app.
6. Verify inventory, snapshot IDs and estimates, and run a selected nonproduction refresh.

Automated tests restore a backup into a fresh file and verify exact snapshot identity. Production restore drills must also cover off-volume backup retrieval, IAM, actual volume ownership and application/chart compatibility.

## Health and sizing

`/healthz` indicates the process is serving; `/readyz` verifies DB access. Initial import continues in the background; readiness does not mean every pool has been fetched. Inspect inventory/job state for data readiness. Probes disclose no observations and intentionally bypass browser auth.

Do not expose local-auth mode beyond trusted development. IAP verification also protects requests reaching the backend directly. Use HTTPS and approved organization/group grants. All admitted users share view, export, refresh and estimate rights.

Monitor collector errors/durations, queue latency, API latency, DB/disk size and free space, metrics coverage, snapshot age and backup/restore health. This version compresses metrics with each complete snapshot; repeated ten-day histories can grow storage materially. Measure this at actual inventory scale and configure collection scope/retention sizing before production. An incremental time-series store/deduplicated history is a future scaling option, not an implemented feature.

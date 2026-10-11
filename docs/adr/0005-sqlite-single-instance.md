---
status: accepted
---

# Use SQLite with a single database-owning application instance

Use SQLite for the shared dashboard, with a single database-owning application instance on durable block-backed storage. WAL supports concurrent reads and serialized short write transactions; collection occurs outside the write transaction and publishes a complete pool snapshot atomically. This avoids a separate database service, and the user accepts brief downtime during restarts or maintenance. Metrics volume and load performance must be measured before production rollout; the hosting platform remains to be selected.

Remote users access the application's API. API and worker processes that directly open the database must be colocated on the same host; collectors on other hosts submit results through the owning application rather than mounting its database file. Do not place the SQLite database on a shared network filesystem. Use a supported consistent-backup mechanism, off-volume backup storage, and tested restoration; copying only a live database file is not the backup design.

Reference: [SQLite appropriate uses](https://www.sqlite.org/whentouse.html), [WAL](https://www.sqlite.org/wal.html), and [online backups](https://www.sqlite.org/backup.html).

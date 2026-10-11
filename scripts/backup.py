"""Create a consistent backup from the same host as the database owner."""

import argparse
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("database")
parser.add_argument("destination")
args = parser.parse_args()
target = Path(args.destination)
if target.exists():
    parser.error("Destination exists; choose a new backup filename")
with sqlite3.connect(f"file:{Path(args.database).resolve()}?mode=ro", uri=True) as source:
    with sqlite3.connect(target) as backup:
        source.backup(backup)
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
print(f"Consistent backup saved to {target}")

"""Collect NBA data locally, validate it, and publish it to SQLite Cloud."""

import argparse
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys

from cards_tracker.sqlite_cloud import connect_cloud, publish_snapshot, read_snapshot

PROJECT_DIR = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-season", default="2000-01")
    parser.add_argument("--through-season", default="2025-26")
    parser.add_argument("--use-cache", action="store_true",
                        help="Reuse NBA responses instead of refreshing them")
    parser.add_argument("--upload-only", action="store_true",
                        help="Publish the existing local DB without NBA requests")
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect and validate locally without connecting to cloud")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--delay", type=float, default=1)
    args = parser.parse_args()
    connection_string = os.environ.get("SQLITE_CLOUD_CONNECTION_STRING", "")
    if not args.dry_run and not connection_string:
        parser.error("Set SQLITE_CLOUD_CONNECTION_STRING in your environment before syncing")
    if not args.upload_only:
        command = [sys.executable, str(Path(__file__).with_name("build_database.py")),
                   "--start-season", args.start_season, "--through-season", args.through_season,
                   "--timeout", str(args.timeout), "--delay", str(args.delay)]
        if not args.use_cache:
            command.append("--refresh")
        subprocess.run(command, check=True)
    tables = read_snapshot(PROJECT_DIR / "data/processed/leap_study.sqlite")
    metadata = dict(tables["metadata"])
    print(f"Validated {len(tables['players']):,} players and "
          f"{len(tables['player_seasons']):,} player-seasons "
          f"({metadata['start_season']} through {metadata['through_season']}).")
    if args.dry_run:
        print("Dry run complete; no cloud connection or writes made.")
        return
    try:
        with closing(connect_cloud(connection_string)) as connection:
            snapshot_id = publish_snapshot(connection, tables)
    except Exception:
        # SDK exceptions may embed credentials. Do not print their text or traceback.
        raise SystemExit("Cloud sync failed. Check connectivity, database permissions and credentials. "
                         "The active snapshot changes only after a complete upload; "
                         "if the final response was lost, check leap_active_snapshot before retrying.") from None
    print(f"Published snapshot {snapshot_id}. App queries can now read the updated leap_* views.")


if __name__ == "__main__":
    main()

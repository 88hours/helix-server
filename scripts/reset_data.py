#!/usr/bin/env python3
"""
Reset all Helix data — flushes Redis and drops all Postgres tables.
Tables are recreated automatically on next app startup via init_db().

Usage:
    python scripts/reset_data.py
    python scripts/reset_data.py --redis-only
    python scripts/reset_data.py --db-only
"""

import argparse
import os
import sys
from pathlib import Path

# Load .env from repo root
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def reset_redis():
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    print(f"  connecting to Redis: {redis_url.split('@')[-1]}")
    try:
        import redis
        r = redis.from_url(redis_url)
        r.flushall()
        print("  ✓ Redis flushed (FLUSHALL)")
    except ImportError:
        print("  ✗ redis-py not installed — run: pip install redis")
        sys.exit(1)
    except Exception as e:
        print(f"  ✗ Redis error: {e}")
        sys.exit(1)


def reset_postgres():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("  ✗ DATABASE_URL not set — skipping Postgres")
        return

    display = db_url.split("@")[-1] if "@" in db_url else db_url
    print(f"  connecting to Postgres: {display}")
    try:
        import psycopg2
    except ImportError:
        print("  ✗ psycopg2 not installed — run: pip install psycopg2-binary")
        sys.exit(1)

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            DROP TABLE IF EXISTS
                project_settings,
                projects,
                github_installations,
                user_settings,
                users
            CASCADE;
        """)
        cur.close()
        conn.close()
        print("  ✓ Postgres tables dropped (will be recreated on next startup)")
    except Exception as e:
        print(f"  ✗ Postgres error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Reset all Helix data")
    parser.add_argument("--redis-only", action="store_true", help="Only flush Redis")
    parser.add_argument("--db-only",    action="store_true", help="Only drop Postgres tables")
    args = parser.parse_args()

    do_redis = not args.db_only
    do_db    = not args.redis_only

    print("Helix data reset")
    print("=" * 40)

    if do_redis:
        print("\n[Redis]")
        reset_redis()

    if do_db:
        print("\n[Postgres]")
        reset_postgres()

    print("\nDone.")


if __name__ == "__main__":
    main()

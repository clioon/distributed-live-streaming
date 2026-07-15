import os
import time

import psycopg


USER = os.getenv("POSTGRES_USER", "streaming_app")
PASSWORD = os.getenv("POSTGRES_PASSWORD", "streaming")
DATABASE = os.getenv("POSTGRES_DB", "streaming")
PRIMARY_HOST = os.getenv("PRIMARY_HOST", "postgres")
REPLICA_HOST = os.getenv("REPLICA_HOST", "postgres-replica")
FAILURE_THRESHOLD = int(os.getenv("FAILURE_THRESHOLD", "2"))
CHECK_INTERVAL = float(os.getenv("CHECK_INTERVAL_SECONDS", "1"))


def dsn(host: str) -> str:
    return (
        f"host={host} port=5432 dbname={DATABASE} user={USER} "
        f"password={PASSWORD} connect_timeout=1"
    )


def query_recovery(host: str) -> bool:
    with psycopg.connect(dsn(host)) as connection:
        return bool(connection.execute("SELECT pg_is_in_recovery()").fetchone()[0])


def promote_replica() -> None:
    with psycopg.connect(dsn(REPLICA_HOST), autocommit=True) as connection:
        recovering = bool(
            connection.execute("SELECT pg_is_in_recovery()").fetchone()[0]
        )
        if recovering:
            promoted = connection.execute(
                "SELECT pg_promote(wait_seconds => 60)"
            ).fetchone()[0]
            if not promoted:
                raise RuntimeError("PostgreSQL replica promotion timed out")
            print("FAILOVER_PROMOTED replica to primary", flush=True)


def main() -> None:
    failures = 0
    promoted = False
    while True:
        active_host = REPLICA_HOST if promoted else PRIMARY_HOST
        try:
            if query_recovery(active_host):
                raise RuntimeError("Active PostgreSQL node is in recovery")
            failures = 0
        except (psycopg.Error, RuntimeError) as error:
            failures += 1
            print(
                f"ACTIVE_NODE_UNAVAILABLE host={active_host} failure={failures} error={error}",
                flush=True,
            )
            if failures >= FAILURE_THRESHOLD and not promoted:
                try:
                    promote_replica()
                    promoted = not query_recovery(REPLICA_HOST)
                    failures = 0
                except psycopg.Error as promotion_error:
                    print(f"FAILOVER_RETRY error={promotion_error}", flush=True)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
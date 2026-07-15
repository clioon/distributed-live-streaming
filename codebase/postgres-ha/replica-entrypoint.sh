#!/bin/sh
set -eu

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    chmod 0700 "$PGDATA"

    until gosu postgres pg_isready -h postgres -p 5432 -U "$POSTGRES_USER"; do
        sleep 1
    done

    gosu postgres env PGPASSWORD=replicator pg_basebackup \
        --host=postgres \
        --port=5432 \
        --username=replicator \
        --pgdata="$PGDATA" \
        --wal-method=stream \
        --write-recovery-conf \
        --progress
fi

exec docker-entrypoint.sh "$@"
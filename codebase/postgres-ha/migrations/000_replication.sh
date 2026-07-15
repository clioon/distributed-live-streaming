#!/bin/sh
set -eu

cat >> "$PGDATA/pg_hba.conf" <<'EOF'
host replication replicator 0.0.0.0/0 trust
EOF

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --command "CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator';"
import re
import unittest
from pathlib import Path


COMPONENT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (COMPONENT_ROOT / "migrations" / "001_initial_schema.sql").read_text(
    encoding="utf-8"
)
INDEXES = (COMPONENT_ROOT / "migrations" / "002_indexes.sql").read_text(
    encoding="utf-8"
)
PLAYBACK_FIX = (
    COMPONENT_ROOT / "migrations" / "004_fix_playback_path_constraint.sql"
).read_text(encoding="utf-8")
REPLICA_ENTRYPOINT = (COMPONENT_ROOT / "replica-entrypoint.sh").read_text(
    encoding="utf-8"
)


class SchemaTests(unittest.TestCase):
    def test_all_authoritative_tables_are_declared(self) -> None:
        tables = set(re.findall(r"CREATE TABLE ([a-z_]+)", SCHEMA))

        self.assertEqual(
            tables,
            {
                "users",
                "lives",
                "ingest_sessions",
                "worker_instances",
                "live_metadata",
                "donations",
                "outbox_events",
                "processed_events",
                "orchestrator_leases",
            },
        )

    def test_stream_secret_is_stored_only_as_validated_hash(self) -> None:
        live_table = SCHEMA.split("CREATE TABLE lives", 1)[1].split(");", 1)[0]

        self.assertIn("stream_secret_hash CHAR(64) NOT NULL", live_table)
        self.assertNotRegex(live_table, r"\bstream_secret\s")
        self.assertIn("^[0-9a-f]{64}$", live_table)

    def test_only_one_connected_ingest_and_active_worker_are_allowed(self) -> None:
        self.assertIn("ingest_sessions_one_connected_per_live", SCHEMA)
        self.assertIn("WHERE status = 'connected'", SCHEMA)
        self.assertIn("worker_instances_one_active_per_live", SCHEMA)
        self.assertIn("WHERE status IN ('provisioning', 'running')", SCHEMA)

    def test_outbox_and_inbox_have_idempotency_constraints(self) -> None:
        self.assertIn("CONSTRAINT outbox_event_once UNIQUE", SCHEMA)
        self.assertIn("PRIMARY KEY (consumer_name, event_id)", SCHEMA)
        self.assertIn("WHERE published_at IS NULL", INDEXES)

    def test_financial_and_version_values_are_constrained(self) -> None:
        self.assertIn("CHECK (amount_cents > 0)", SCHEMA)
        self.assertIn("CHECK (version > 0)", SCHEMA)
        self.assertIn("CHECK (aggregate_version > 0)", SCHEMA)

    def test_playback_path_constraint_accepts_manifest_extension(self) -> None:
        expected_pattern = "current/index\\.m3u8$"

        self.assertIn(expected_pattern, SCHEMA)
        self.assertIn(expected_pattern, PLAYBACK_FIX)
        self.assertNotIn("current/index\\\\.m3u8$", SCHEMA)


class FailoverConfigurationTests(unittest.TestCase):
    def test_replica_bootstrap_uses_official_image_user_helper(self) -> None:
        self.assertIn("gosu postgres env PGPASSWORD=replicator pg_basebackup", REPLICA_ENTRYPOINT)
        self.assertNotIn("su-exec", REPLICA_ENTRYPOINT)

    def test_patroni_uses_quorum_and_synchronous_replication(self) -> None:
        config = (COMPONENT_ROOT / "patroni.yml").read_text(encoding="utf-8")

        self.assertEqual(config.count("etcd-"), 3)
        self.assertIn("synchronous_mode: true", config)
        self.assertIn("synchronous_mode_strict: true", config)
        self.assertIn("synchronous_commit: remote_apply", config)
        self.assertIn("use_pg_rewind: true", config)
        self.assertIn("protocol: http", config)
        self.assertIn('ssl: "off"', config)
        self.assertIn("password: replicator", config)

    def test_haproxy_exposes_stable_primary_and_replica_endpoints(self) -> None:
        config = (COMPONENT_ROOT / "haproxy.cfg").read_text(encoding="utf-8")

        self.assertIn("bind *:5432", config)
        self.assertIn("server primary postgres:5432", config)
        self.assertIn("server replica postgres-replica:5432", config)
        self.assertIn("bind *:5433", config)
        self.assertIn("option tcp-check", config)
        self.assertIn("backup", config)
        self.assertNotIn("ssl verify required", config)
        self.assertNotIn("check-ssl", config)


if __name__ == "__main__":
    unittest.main()
BEGIN;

CREATE INDEX lives_public_catalog_idx
    ON lives(status, started_at DESC)
    WHERE status = 'live';

CREATE INDEX lives_owner_created_idx
    ON lives(owner_id, created_at DESC);

CREATE INDEX worker_instances_live_status_idx
    ON worker_instances(live_id, status);

CREATE INDEX donations_live_created_idx
    ON donations(live_id, created_at DESC);

CREATE INDEX outbox_events_pending_idx
    ON outbox_events(occurred_at, id)
    WHERE published_at IS NULL;

CREATE INDEX orchestrator_leases_expiry_idx
    ON orchestrator_leases(expires_at);

COMMIT;
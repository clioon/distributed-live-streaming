BEGIN;

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE user_role AS ENUM ('viewer', 'streamer', 'admin');
CREATE TYPE live_desired_state AS ENUM ('running', 'stopped');
CREATE TYPE live_status AS ENUM (
    'created',
    'ingesting',
    'provisioning',
    'live',
    'stopping',
    'ended',
    'failed'
);
CREATE TYPE ingest_session_status AS ENUM ('connected', 'disconnected', 'rejected');
CREATE TYPE worker_status AS ENUM ('provisioning', 'running', 'unhealthy', 'stopped', 'failed');
CREATE TYPE donation_status AS ENUM ('recorded', 'cancelled');

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username CITEXT NOT NULL UNIQUE,
    email CITEXT NOT NULL UNIQUE,
    display_name VARCHAR(80) NOT NULL,
    password_hash TEXT NOT NULL,
    role user_role NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT users_username_length CHECK (char_length(username) BETWEEN 3 AND 40),
    CONSTRAINT users_display_name_length CHECK (char_length(display_name) BETWEEN 1 AND 80)
);

CREATE TABLE lives (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    title VARCHAR(120) NOT NULL,
    description VARCHAR(1000) NOT NULL DEFAULT '',
    desired_state live_desired_state NOT NULL DEFAULT 'running',
    status live_status NOT NULL DEFAULT 'created',
    stream_secret_hash CHAR(64) NOT NULL,
    current_ingest_session_id UUID,
    worker_generation BIGINT NOT NULL DEFAULT 0,
    version BIGINT NOT NULL DEFAULT 1,
    playback_path TEXT,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    playback_ready_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    CONSTRAINT lives_title_length CHECK (char_length(title) BETWEEN 1 AND 120),
    CONSTRAINT lives_stream_secret_hash_format CHECK (stream_secret_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT lives_worker_generation_nonnegative CHECK (worker_generation >= 0),
    CONSTRAINT lives_version_positive CHECK (version > 0),
    CONSTRAINT lives_playback_path_format CHECK (
        playback_path IS NULL OR playback_path ~ '^/hls/[0-9a-f-]+/current/index\.m3u8$'
    )
);

CREATE TABLE ingest_sessions (
    id UUID PRIMARY KEY,
    live_id UUID NOT NULL REFERENCES lives(id) ON DELETE CASCADE,
    status ingest_session_status NOT NULL,
    client_id VARCHAR(128) NOT NULL,
    source_ip INET,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disconnected_at TIMESTAMPTZ,
    CONSTRAINT ingest_session_end_after_start CHECK (
        disconnected_at IS NULL OR disconnected_at >= connected_at
    )
);

ALTER TABLE lives
    ADD CONSTRAINT lives_current_ingest_session_fk
    FOREIGN KEY (current_ingest_session_id)
    REFERENCES ingest_sessions(id)
    ON DELETE SET NULL;

CREATE UNIQUE INDEX ingest_sessions_one_connected_per_live
    ON ingest_sessions(live_id)
    WHERE status = 'connected';

CREATE TABLE worker_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    live_id UUID NOT NULL REFERENCES lives(id) ON DELETE CASCADE,
    generation BIGINT NOT NULL,
    container_id TEXT UNIQUE,
    container_name TEXT NOT NULL UNIQUE,
    status worker_status NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    failure_reason TEXT,
    CONSTRAINT worker_generation_positive CHECK (generation > 0),
    CONSTRAINT worker_live_generation_unique UNIQUE (live_id, generation),
    CONSTRAINT worker_end_after_start CHECK (stopped_at IS NULL OR stopped_at >= started_at)
);

CREATE UNIQUE INDEX worker_instances_one_active_per_live
    ON worker_instances(live_id)
    WHERE status IN ('provisioning', 'running');

CREATE TABLE live_metadata (
    live_id UUID PRIMARY KEY REFERENCES lives(id) ON DELETE CASCADE,
    category VARCHAR(80),
    language VARCHAR(16),
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT live_metadata_tags_array CHECK (jsonb_typeof(tags) = 'array')
);

CREATE TABLE donations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    live_id UUID NOT NULL REFERENCES lives(id) ON DELETE RESTRICT,
    donor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    amount_cents BIGINT NOT NULL,
    currency CHAR(3) NOT NULL,
    message VARCHAR(300) NOT NULL DEFAULT '',
    status donation_status NOT NULL DEFAULT 'recorded',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT donations_amount_positive CHECK (amount_cents > 0),
    CONSTRAINT donations_currency_format CHECK (currency ~ '^[A-Z]{3}$')
);

CREATE TABLE outbox_events (
    id UUID PRIMARY KEY,
    aggregate_type VARCHAR(80) NOT NULL,
    aggregate_id UUID NOT NULL,
    aggregate_version BIGINT NOT NULL,
    event_type VARCHAR(160) NOT NULL,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    CONSTRAINT outbox_aggregate_version_positive CHECK (aggregate_version > 0),
    CONSTRAINT outbox_attempts_nonnegative CHECK (attempts >= 0),
    CONSTRAINT outbox_event_once UNIQUE (
        aggregate_type,
        aggregate_id,
        aggregate_version,
        event_type
    )
);

CREATE TABLE processed_events (
    consumer_name VARCHAR(120) NOT NULL,
    event_id UUID NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer_name, event_id)
);

CREATE TABLE orchestrator_leases (
    resource_key VARCHAR(200) PRIMARY KEY,
    owner_id UUID NOT NULL,
    generation BIGINT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT orchestrator_lease_generation_positive CHECK (generation > 0)
);

CREATE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER lives_set_updated_at
    BEFORE UPDATE ON lives
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER live_metadata_set_updated_at
    BEFORE UPDATE ON live_metadata
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
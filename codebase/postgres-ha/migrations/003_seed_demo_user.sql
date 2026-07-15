INSERT INTO users (
    id,
    username,
    email,
    display_name,
    password_hash,
    role
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    'demo_streamer',
    'demo@distributed-live.local',
    'Streamer Demo',
    'local-development-only',
    'streamer'
)
ON CONFLICT (id) DO NOTHING;
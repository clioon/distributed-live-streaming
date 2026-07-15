ALTER TABLE lives
    DROP CONSTRAINT IF EXISTS lives_playback_path_format;

ALTER TABLE lives
    ADD CONSTRAINT lives_playback_path_format CHECK (
        playback_path IS NULL OR playback_path ~ '^/hls/[0-9a-f-]+/current/index\.m3u8$'
    );
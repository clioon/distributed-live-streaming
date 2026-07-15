from pathlib import Path

from .config import WorkerConfig


def build_ffmpeg_command(config: WorkerConfig, output_directory: Path) -> tuple[str, ...]:
    segment_pattern = output_directory / "segment_%06d.ts"
    manifest = output_directory / "index.m3u8"
    return (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        "-i",
        config.input_url,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-force_key_frames",
        f"expr:gte(t,n_forced*{config.segment_seconds})",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-f",
        "hls",
        "-hls_time",
        str(config.segment_seconds),
        "-hls_list_size",
        str(config.playlist_size),
        "-hls_flags",
        "delete_segments+append_list+independent_segments+temp_file",
        "-hls_segment_filename",
        str(segment_pattern),
        str(manifest),
    )
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from hls_origin import HlsPublication


COMPONENT_ROOT = Path(__file__).resolve().parents[1]
LIVE_ID = UUID("b0000000-0000-0000-0000-000000000001")
POINTER_ID = UUID("b0000000-0000-0000-0000-000000000002")


class HlsPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.publication = HlsPublication(
            self.root, id_factory=lambda: POINTER_ID
        )

    def test_generation_must_have_nonempty_manifest_before_activation(self) -> None:
        generation = self.publication.generation_directory(LIVE_ID, 1)
        generation.mkdir(parents=True)

        with self.assertRaises(FileNotFoundError):
            self.publication.activate(LIVE_ID, 1)

        (generation / "index.m3u8").write_text("", encoding="ascii")
        with self.assertRaises(FileNotFoundError):
            self.publication.activate(LIVE_ID, 1)

    def test_activation_atomically_replaces_current_symlink(self) -> None:
        generation = self.publication.generation_directory(LIVE_ID, 4)
        generation.mkdir(parents=True)
        (generation / "index.m3u8").write_text("#EXTM3U", encoding="ascii")

        with patch("hls_origin.publication.os.symlink") as symlink:
            with patch("hls_origin.publication.os.replace") as replace:
                manifest = self.publication.activate(LIVE_ID, 4)

        temporary = generation.parent / f".current-{POINTER_ID.hex}"
        symlink.assert_called_once_with("g-4", temporary, target_is_directory=True)
        replace.assert_called_once_with(temporary, generation.parent / "current")
        self.assertEqual(manifest, generation.parent / "current" / "index.m3u8")

    def test_generation_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            self.publication.generation_directory(LIVE_ID, 0)

    def test_symlinked_generation_is_rejected_before_manifest_access(self) -> None:
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(ValueError):
                self.publication.activate(LIVE_ID, 1)


class NginxOriginTests(unittest.TestCase):
    def test_origin_serves_only_stable_manifest_and_segment_paths(self) -> None:
        config = (COMPONENT_ROOT / "nginx.conf").read_text(encoding="utf-8")

        self.assertIn("current/index\\.m3u8", config)
        self.assertIn("current/segment_[0-9]{6}\\.ts", config)
        self.assertIn('location ~ "^/hls/', config)
        self.assertIn("application/vnd.apple.mpegurl", config)
        self.assertIn("video/mp2t", config)
        self.assertIn("location /hls/", config)
        self.assertIn("return 404", config)
        self.assertNotIn("auth_request", config)
        self.assertNotIn("/_authorize", config)

    def test_playlists_are_not_cached_but_segments_are_short_lived(self) -> None:
        config = (COMPONENT_ROOT / "nginx.conf").read_text(encoding="utf-8")

        self.assertIn('Cache-Control "no-store"', config)
        self.assertIn('Cache-Control "public, max-age=10, immutable"', config)


if __name__ == "__main__":
    unittest.main()
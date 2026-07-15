import unittest
from pathlib import Path


COMPONENT_ROOT = Path(__file__).resolve().parents[1]


class NginxRtmpSecurityTests(unittest.TestCase):
    def test_raw_rtmp_playback_is_restricted_to_worker_network(self) -> None:
        config = (COMPONENT_ROOT / "nginx.conf").read_text(encoding="utf-8")

        self.assertIn("allow play 172.16.0.0/12", config)
        self.assertIn("deny play all", config)
        self.assertLess(config.index("allow play"), config.index("deny play"))


if __name__ == "__main__":
    unittest.main()
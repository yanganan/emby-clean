import tempfile
import unittest
from pathlib import Path

from app.fingerprints import fingerprint_media


class FingerprintTests(unittest.TestCase):
    def test_unavailable_remote_or_missing_path_is_explicit(self):
        result = fingerprint_media("/not/mounted/video.strm", "Video")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "path_unavailable")

    def test_local_file_has_exact_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "clip.bin"
            path.write_bytes(b"fingerprint")
            result = fingerprint_media(str(path), "Video")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["algorithm"], "sha256")
        self.assertEqual(len(result["value"]), 64)


if __name__ == "__main__":
    unittest.main()

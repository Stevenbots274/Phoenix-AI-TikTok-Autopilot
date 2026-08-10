import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.sys.path.insert(0, str(ROOT))

from content_director import ContentDirector
from media_engine import MediaEngine, RenderSpec
from server import password_hash, password_matches


class ContentDirectorTests(unittest.TestCase):
    def test_local_generation_returns_supported_structured_plan(self):
        plan = ContentDirector().generate(
            topic="A breaking AI announcement",
            niche="Artificial intelligence",
            requested_format="AUTO",
            duration_seconds=35,
        )
        self.assertEqual(plan.format, "VOICE_MUSIC")
        self.assertTrue(plan.voice_required)
        self.assertTrue(plan.music_required)
        self.assertGreater(len(plan.script), 50)
        self.assertTrue(all(tag.startswith("#") for tag in plan.hashtags))
        json.dumps(plan.to_dict())

    def test_requested_format_wins(self):
        plan = ContentDirector().generate(topic="A quote", requested_format="SLIDESHOW")
        self.assertEqual(plan.format, "SLIDESHOW")
        self.assertFalse(plan.voice_required)


class MediaEngineTests(unittest.TestCase):
    def test_tiktok_render_spec(self):
        MediaEngine.validate_spec(RenderSpec())

    def test_invalid_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            MediaEngine.validate_spec(RenderSpec(width=1920, height=1080))


class AuthenticationTests(unittest.TestCase):
    def test_passwords_are_salted_and_verifiable(self):
        encoded = password_hash("a-secure-test-password")
        self.assertTrue(password_matches("a-secure-test-password", encoded))
        self.assertFalse(password_matches("wrong-password", encoded))
        self.assertNotEqual(encoded, password_hash("a-secure-test-password"))


if __name__ == "__main__":
    unittest.main()

"""Uploaded media must be served regardless of DEBUG (the gateway proxies
/media/profile_pictures/ to this service)."""

from django.conf import settings
from django.test import TestCase, override_settings


class TestMediaServing(TestCase):
    def setUp(self):
        self.directory = settings.MEDIA_ROOT / "profile_pictures"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = self.directory / "zz-test-media-serving.png"
        self.file.write_bytes(b"\x89PNG-test")
        self.addCleanup(lambda: self.file.unlink(missing_ok=True))

    @override_settings(DEBUG=False)
    def test_serves_existing_file_with_debug_off(self):
        response = self.client.get("/media/profile_pictures/zz-test-media-serving.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"\x89PNG-test")

    @override_settings(DEBUG=False)
    def test_missing_file_is_404(self):
        response = self.client.get("/media/profile_pictures/does-not-exist.png")

        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_path_traversal_is_not_served(self):
        response = self.client.get("/media/../manage.py")

        self.assertIn(response.status_code, (301, 400, 404))

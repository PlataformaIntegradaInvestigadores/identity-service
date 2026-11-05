"""Uploaded media must be served regardless of DEBUG (the gateway proxies
/media/profile_pictures/ to this service), but safely: uploads are untrusted
and share the origin of the app."""

from django.conf import settings
from django.test import TestCase, override_settings


class TestMediaServing(TestCase):
    def setUp(self):
        self.directory = settings.MEDIA_ROOT / "profile_pictures"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.created = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for path in self.created:
            path.unlink(missing_ok=True)

    def _make(self, directory, name, content):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(content)
        self.created.append(path)
        return path

    @override_settings(DEBUG=False)
    def test_serves_image_with_debug_off_and_hardened_headers(self):
        self._make(self.directory, "zz-test-media.png", b"\x89PNG-test")

        response = self.client.get("/media/profile_pictures/zz-test-media.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"\x89PNG-test")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertNotIn("attachment", response.get("Content-Disposition", ""))

    @override_settings(DEBUG=False)
    def test_non_image_is_forced_to_download(self):
        self._make(self.directory, "zz-test-media.html", b"<script>1</script>")

        response = self.client.get("/media/profile_pictures/zz-test-media.html")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], "attachment")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    @override_settings(DEBUG=False)
    def test_missing_file_is_404(self):
        response = self.client.get("/media/profile_pictures/does-not-exist.png")

        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_other_media_directories_are_not_public(self):
        self._make(settings.MEDIA_ROOT / "private", "zz-secret.png", b"\x89PNG-x")

        response = self.client.get("/media/private/zz-secret.png")

        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_path_traversal_is_not_served(self):
        response = self.client.get("/media/profile_pictures/../../manage.py")

        self.assertIn(response.status_code, (301, 400, 404))

"""Unitarias de UserUpdateView / UserSerializer: campos que acepta el PATCH de
perfil de investigador."""

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from identity.models import User


@override_settings(LEGACY_SYNC_ENABLED=False)
class TestUserUpdateViewInterests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="owner@example.com",
            password="x",
            first_name="Owner",
            last_name="Test",
        )
        token = AccessToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_actualiza_interests(self):
        response = self.client.put(
            f"/api/users/{self.user.id}/update/",
            {"interests": "machine learning, nlp"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.interests, "machine learning, nlp")

    def test_patch_is_not_allowed(self):
        response = self.client.patch(
            f"/api/users/{self.user.id}/update/",
            {"interests": "nlp"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

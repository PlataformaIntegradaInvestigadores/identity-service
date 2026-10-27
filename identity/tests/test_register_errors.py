from unittest import mock

from rest_framework import status
from rest_framework.test import APITestCase


class RegisterUnexpectedErrorTests(APITestCase):
    def test_internal_error_message_is_not_exposed(self):
        payload = {
            "first_name": "Ana",
            "last_name": "Perez",
            "username": "ana@example.com",
            "password": "Str0ng-pass-phrase-2026",
        }
        with mock.patch(
            "identity.serializers.register_user",
            side_effect=RuntimeError("connection to db-internal:5432 refused"),
        ):
            response = self.client.post("/api/register/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(
            response.json(), {"error": "No se pudo completar el registro."}
        )
        self.assertNotIn("db-internal", response.content.decode())

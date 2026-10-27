from django.test import SimpleTestCase
from drf_spectacular.generators import SchemaGenerator
from rest_framework import status
from rest_framework.test import APITestCase


class OpenAPISchemaTests(APITestCase):
    def test_schema_uses_gateway_prefix(self):
        response = self.client.get("/api/schema/", {"format": "json"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        schema = response.json()
        self.assertEqual(
            schema["servers"], [{"url": "/api/identity", "description": "Gateway"}]
        )
        self.assertTrue(all(not path.startswith("/api") for path in schema["paths"]))


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


class OpenAPIDocumentationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def operations(self):
        for path, item in self.schema["paths"].items():
            for method, operation in item.items():
                if method in HTTP_METHODS:
                    yield path, method, operation

    def test_info_describes_the_service(self):
        info = self.schema["info"]
        self.assertIn("identidad", info["title"])
        self.assertIn("Cómo autenticarse", info["description"])

    def test_every_operation_has_summary_description_and_tag(self):
        for path, method, operation in self.operations():
            label = f"{method.upper()} {path}"
            self.assertTrue(operation.get("summary"), f"{label} sin summary")
            self.assertTrue(operation.get("description"), f"{label} sin descripción")
            self.assertTrue(operation.get("tags"), f"{label} sin tag")

    def test_tags_are_declared_with_a_description(self):
        declared = {tag["name"] for tag in self.schema["tags"]}
        self.assertTrue(all(tag["description"] for tag in self.schema["tags"]))
        used = {tag for _, _, op in self.operations() for tag in op["tags"]}
        self.assertEqual(used, declared)

    def test_internal_and_health_endpoints_are_not_published(self):
        for path in self.schema["paths"]:
            self.assertFalse(path.startswith(("/internal", "/health")), path)

    def test_error_responses_are_described(self):
        for path, method, operation in self.operations():
            for status_code, response in operation["responses"].items():
                if status_code.startswith(("4", "5")):
                    label = f"{method.upper()} {path} {status_code}"
                    self.assertTrue(response.get("description"), label)

    def test_operation_ids_are_unique(self):
        ids = [op["operationId"] for _, _, op in self.operations()]
        self.assertEqual(len(ids), len(set(ids)))

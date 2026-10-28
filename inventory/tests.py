import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from inventory.portal import _support_ready
from inventory.views import _has_image_column, _schema


@override_settings(ALLOWED_HOSTS=["localhost"])
class LoginPageTests(SimpleTestCase):
    @override_settings(SOCIALACCOUNT_PROVIDERS={})
    @patch(
        "allauth.socialaccount.adapter.DefaultSocialAccountAdapter.get_app",
        side_effect=AssertionError("Login page should not query Google app config"),
    )
    def test_staff_login_page_works_without_google_configuration(
        self, get_app_mock
    ):
        response = self.client.get("/login/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Вхід")
        self.assertNotContains(response, "Увійти через Google")
        get_app_mock.assert_not_called()

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "APP": {
                    "client_id": "test-client-id",
                    "secret": "test-secret",
                }
            }
        }
    )
    def test_google_button_uses_named_login_route(self):
        response = self.client.get("/login/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'action="/accounts/google/login/"')
        self.assertContains(response, "Увійти через Google")


class DatabaseIntrospectionTests(TestCase):
    @patch("inventory.views.connection.introspection.get_table_description")
    @patch("inventory.views.connection.cursor")
    def test_detects_image_column(self, cursor_mock, description_mock):
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = MagicMock()
        cursor_mock.return_value = cursor_context
        description_mock.return_value = [SimpleNamespace(name="image")]
        _has_image_column.cache_clear()

        self.assertTrue(_has_image_column())

        _has_image_column.cache_clear()
        description_mock.return_value = [SimpleNamespace(name="name")]
        self.assertFalse(_has_image_column())

    @patch("inventory.portal.connection.introspection.table_names")
    def test_detects_support_table(self, table_names_mock):
        table_names_mock.return_value = ["products", "support_tickets"]

        self.assertTrue(_support_ready())

        table_names_mock.return_value = ["products"]
        self.assertFalse(_support_ready())

    @patch("inventory.views.connection.introspection.get_field_type")
    @patch("inventory.views.connection.introspection.get_sequences")
    @patch("inventory.views.connection.introspection.get_constraints")
    @patch("inventory.views.connection.introspection.get_table_description")
    @patch("inventory.views.connection.cursor")
    def test_reads_postgresql_schema(
        self,
        cursor_mock,
        description_mock,
        constraints_mock,
        sequences_mock,
        field_type_mock,
    ):
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = MagicMock()
        cursor_mock.return_value = cursor_context
        description_mock.return_value = [
            SimpleNamespace(
                name="product_id",
                type_code=23,
                null_ok=False,
                default="nextval('products_product_id_seq'::regclass)",
            )
        ]
        constraints_mock.return_value = {
            "products_pkey": {
                "primary_key": True,
                "columns": ["product_id"],
            }
        }
        sequences_mock.return_value = [{"column": "product_id"}]
        field_type_mock.return_value = "AutoField"

        self.assertEqual(
            _schema("products"),
            [(
                "product_id",
                "int",
                False,
                "PRI",
                "nextval('products_product_id_seq'::regclass)",
                "auto_increment",
            )],
        )

    def test_admin_command_requires_password(self):
        with patch.dict(os.environ, {"ADMIN_USERNAME": "render-admin"}, clear=True):
            with self.assertRaises(CommandError):
                call_command("ensure_admin")

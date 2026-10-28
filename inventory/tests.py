from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from inventory.portal import _support_ready
from inventory.views import _has_image_column


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

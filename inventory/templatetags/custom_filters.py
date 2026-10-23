from django import template
from django.templatetags.static import static

register = template.Library()

PLACEHOLDER = "inventory/img/products/placeholder.svg"


@register.filter
def get_item(mapping, key):
    """Повертає mapping[key]; якщо ключа немає, повертає сам ключ."""
    if not mapping:
        return key
    return mapping.get(key, key)


@register.filter
def image_url(value):
    """Шлях до фото товару: повне посилання, абсолютний шлях або файл зі static."""
    if not value:
        return static(PLACEHOLDER)
    value = str(value).strip()
    if value.startswith(("http://", "https://", "/")):
        return value
    return static(value)

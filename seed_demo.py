"""Compatibility wrapper for the PostgreSQL demo catalog command."""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.core.management import call_command  # noqa: E402


if __name__ == "__main__":
    call_command("seed_demo")

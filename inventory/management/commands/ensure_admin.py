import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Creates or promotes the Render admin account from environment variables."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "")
        email = os.environ.get("ADMIN_EMAIL", "").strip()

        if not username or not password:
            raise CommandError(
                "Set ADMIN_USERNAME and ADMIN_PASSWORD in the service environment."
            )

        User = get_user_model()
        with transaction.atomic():
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "is_staff": True,
                    "is_superuser": True,
                    "is_active": True,
                },
            )
            changed_fields = []
            if not user.is_staff:
                user.is_staff = True
                changed_fields.append("is_staff")
            if not user.is_superuser:
                user.is_superuser = True
                changed_fields.append("is_superuser")
            if not user.is_active:
                user.is_active = True
                changed_fields.append("is_active")
            if email and user.email != email:
                user.email = email
                changed_fields.append("email")
            if not user.check_password(password):
                user.set_password(password)
                changed_fields.append("password")
            if changed_fields:
                user.save(update_fields=changed_fields)

        action = "Created" if created else "Verified"
        self.stdout.write(self.style.SUCCESS(f"{action} admin account: {username}"))

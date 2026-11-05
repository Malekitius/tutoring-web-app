from getpass import getpass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError

from config.cabinets import provision_cabinet


class Command(BaseCommand):
    help = "Create a teacher account and an empty local cabinet."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, username, **options):
        if not settings.TUTOR_ACCOUNTS:
            raise CommandError("Включите TUTOR_ACCOUNTS=1.")
        users = get_user_model()
        user = users(username=username)
        try:
            user.full_clean(exclude={"password"})
            password = getpass("Пароль: ")
            if password != getpass("Повторите пароль: "):
                raise CommandError("Пароли не совпадают.")
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        user.set_password(password)

        provision_cabinet(user)
        self.stdout.write(self.style.SUCCESS(f"Кабинет «{username}» создан."))

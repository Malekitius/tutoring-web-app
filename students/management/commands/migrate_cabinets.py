from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connections

from config.cabinets import cabinet_is_ready, cabinet_scope


class Command(BaseCommand):
    help = "Apply PostgreSQL migrations to the accounts and every existing cabinet."

    def handle(self, *args, **options):
        if not settings.TUTOR_POSTGRES_DB:
            raise CommandError("Укажите TUTOR_POSTGRES_DB для режима PostgreSQL.")

        migration_options = {"interactive": False, "verbosity": options["verbosity"]}
        call_command("migrate", **migration_options)
        user_ids = list(get_user_model().objects.order_by("pk").values_list("pk", flat=True))
        for user_id in user_ids:
            if not cabinet_is_ready(user_id):
                raise CommandError(f"Кабинет {user_id} отсутствует.")
            with cabinet_scope(user_id) as alias:
                try:
                    call_command("migrate", database=alias, **migration_options)
                finally:
                    connections[alias].close()
        self.stdout.write(self.style.SUCCESS(f"Миграции применены. Кабинетов: {len(user_ids)}."))

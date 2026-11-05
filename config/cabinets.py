"""Request-local database and file storage for teacher accounts."""

import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, connections, transaction

CABINET_APPS = {"students", "school", "materials", "schedule", "finances", "assignments"}
_current = ContextVar("cabinet", default=None)
_connections_lock = Lock()


def cabinet_directory(user_id):
    folder = "postgres-cabinets" if settings.TUTOR_POSTGRES_DB else "cabinets"
    return settings.DATA_DIR / folder / str(int(user_id))


def cabinet_is_ready(user_id):
    directory = cabinet_directory(user_id)
    if not settings.TUTOR_POSTGRES_DB:
        return (directory / "db.sqlite3").is_file()
    if not directory.is_dir():
        return False
    with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
        cursor.execute("SELECT to_regnamespace(%s) IS NOT NULL", [f"cabinet_{int(user_id)}"])
        return cursor.fetchone()[0]


@contextmanager
def cabinet_scope(user_id):
    directory = cabinet_directory(user_id)
    alias = f"cabinet_{int(user_id)}"
    default = connections.databases[DEFAULT_DB_ALIAS]
    if settings.TUTOR_POSTGRES_DB:
        options = {"OPTIONS": {**default["OPTIONS"], "options": f"-c search_path={alias}"}}
    else:
        options = {"NAME": directory / "db.sqlite3"}
    with _connections_lock:
        connections.databases.setdefault(alias, {**default, **options, "TEST": {}})
    token = _current.set((alias, directory))
    try:
        yield alias
    finally:
        _current.reset(token)


def provision_cabinet(user):
    """Save a new user only if their private database is ready."""
    created_directory = None
    created_schema = None
    try:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            user.save(force_insert=True, using=DEFAULT_DB_ALIAS)
            directory = cabinet_directory(user.pk)
            directory.mkdir(mode=0o700, parents=True)
            created_directory = directory
            with cabinet_scope(user.pk) as alias:
                connection = connections[alias]
                try:
                    if settings.TUTOR_POSTGRES_DB:
                        with transaction.atomic(using=alias):
                            with connection.cursor() as cursor:
                                cursor.execute(f"CREATE SCHEMA {connection.ops.quote_name(alias)}")
                            call_command("migrate", database=alias, interactive=False, verbosity=0)
                        created_schema = alias
                    else:
                        call_command("migrate", database=alias, interactive=False, verbosity=0)
                finally:
                    connection.close()
    except Exception:
        if created_schema is not None:
            connection = connections[DEFAULT_DB_ALIAS]
            with connection.cursor() as cursor:
                cursor.execute(f"DROP SCHEMA {connection.ops.quote_name(created_schema)} CASCADE")
        if created_directory is not None:
            shutil.rmtree(created_directory)
        raise


def database_alias():
    cabinet = _current.get()
    return cabinet[0] if cabinet else DEFAULT_DB_ALIAS


def data_directory():
    cabinet = _current.get()
    return cabinet[1] if cabinet else settings.DATA_DIR


def media_directory():
    cabinet = _current.get()
    return cabinet[1] / "uploads" if cabinet else settings.MEDIA_ROOT


def atomic(view=None):
    """Use the same database for the transaction and its teaching queries."""
    if view is None:
        return transaction.atomic(using=database_alias())

    @wraps(view)
    def wrapped(*args, **kwargs):
        with transaction.atomic(using=database_alias()):
            return view(*args, **kwargs)

    return wrapped


class CabinetRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label in CABINET_APPS:
            return database_alias()
        return None

    db_for_write = db_for_read

    def allow_migrate(self, db, app_label, **hints):
        if db.startswith("cabinet_"):
            return app_label in CABINET_APPS
        if settings.TUTOR_ACCOUNTS and db == DEFAULT_DB_ALIAS:
            return app_label not in CABINET_APPS
        return None


class CabinetStorage(FileSystemStorage):
    @property
    def location(self):
        return str(media_directory())

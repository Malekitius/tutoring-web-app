"""Run the local Compose deployment and copy it to a fresh project."""

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DUMP = "database.dump"
FILES_ARCHIVE = "files.tar.gz"


class Project:
    def __init__(self, name, port):
        self.name = name
        self.port = port
        self.env_file = ROOT / "data" / "deploy" / f"{name}.env"
        self.command = ["docker", "compose", "--project-name", name, "--env-file", str(self.env_file)]

    def compose(self, *args, **kwargs):
        env = {key: value for key, value in os.environ.items() if not key.startswith("TUTOR_DEPLOY_")}
        return subprocess.run([*self.command, *args], cwd=ROOT, env=env, check=True, **kwargs)

    def configure(self):
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as env:
            env.write(f"TUTOR_DEPLOY_PORT={self.port}\n")
            for name in ("SECRET_KEY", "POSTGRES_PASSWORD", "DB_PASSWORD"):
                env.write(f"TUTOR_DEPLOY_{name}={secrets.token_urlsafe(48)}\n")

    def up(self, build=True):
        if not self.env_file.is_file():
            self.configure()
        flags = ["--build"] if build else []
        self.compose("up", "--detach", "--wait", *flags)
        self.compose("port", "web", "8000")

    def ensure_fresh(self):
        label = f"label=com.docker.compose.project={self.name}"
        for command in (("volume", "ls", "-q"), ("ps", "-aq")):
            result = subprocess.run(["docker", *command, "--filter", label],
                                    check=True, capture_output=True, text=True)
            if result.stdout.strip():
                raise ValueError("Для восстановления укажите новое имя проекта через --project.")
        if self.env_file.exists():
            raise ValueError("Для восстановления укажите новое имя проекта через --project.")


def backup(project, target):
    if target.exists():
        raise ValueError("Архив с таким именем уже существует.")
    if not project.compose("ps", "--status", "running", "-q", "db", capture_output=True).stdout.strip():
        raise ValueError("Запустите проект перед созданием резервной копии.")
    web_running = project.compose("ps", "--status", "running", "-q", "web", capture_output=True).stdout.strip()
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        if web_running:
            project.compose("stop", "web")
        try:
            with (scratch / DATABASE_DUMP).open("wb") as dump:
                project.compose("exec", "-T", "db", "pg_dump", "-U", "postgres", "-d", "tutor",
                                "--format=custom", stdout=dump)
            with (scratch / FILES_ARCHIVE).open("wb") as files:
                project.compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "tar", "web",
                                "--exclude=assistant_auth.json", "--exclude=assistant_auth.json.lock",
                                "-czf", "-", "-C", "/var/lib/tutor", ".", stdout=files)
        finally:
            if web_running:
                project.compose("start", "web")
        complete = scratch / "backup.zip"
        with zipfile.ZipFile(complete, "w") as archive:
            for name in (DATABASE_DUMP, FILES_ARCHIVE):
                archive.write(scratch / name, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as output, complete.open("rb") as source:
                shutil.copyfileobj(source, output)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    print(f"Копия сохранена: {target}")


def restore(project, source):
    project.ensure_fresh()
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        with zipfile.ZipFile(source) as archive:
            if sorted(archive.namelist()) != sorted((DATABASE_DUMP, FILES_ARCHIVE)):
                raise ValueError("Выберите ZIP, созданный командой backup.")
            for name in (DATABASE_DUMP, FILES_ARCHIVE):
                with archive.open(name) as member, (scratch / name).open("wb") as output:
                    shutil.copyfileobj(member, output)
        with tarfile.open(scratch / FILES_ARCHIVE, "r:gz") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not (member.isdir() or member.isfile()):
                    raise ValueError("Недопустимый путь или тип файла в архиве.")
        project.configure()
        project.compose("up", "--detach", "--wait", "db")
        project.compose("build", "web")
        with (scratch / DATABASE_DUMP).open("rb") as dump:
            project.compose("exec", "-T", "db", "pg_restore", "-U", "postgres", "-d", "tutor",
                            "--no-owner", "--no-privileges", "--role=tutor", "--single-transaction", stdin=dump)
        with (scratch / FILES_ARCHIVE).open("rb") as files:
            project.compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "tar", "web",
                            "--no-same-owner", "-xzf", "-", "-C", "/var/lib/tutor", stdin=files)
        project.up(build=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="tutor-cabinet", help="Compose project name")
    parser.add_argument("--port", type=int, default=8769, help="Port for a new project")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("up", "stop"):
        commands.add_parser(name)
    for name in ("backup", "restore"):
        commands.add_parser(name).add_argument("archive", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", args.project):
        parser.error("Недопустимое имя проекта.")
    if not 1 <= args.port <= 65535:
        parser.error("Порт должен быть от 1 до 65535.")
    project = Project(args.project, args.port)
    try:
        if args.command == "up":
            project.up()
        elif args.command == "stop":
            project.compose("stop")
        elif args.command == "backup":
            backup(project, args.archive.resolve())
        else:
            restore(project, args.archive.resolve())
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()

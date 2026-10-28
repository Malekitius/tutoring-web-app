"""Versioned, local-only archive of tutor data and uploaded student work."""

import hashlib
import io
import json
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.serializers.base import DeserializationError
from django.db import transaction
from django.db.utils import IntegrityError

from assignments.models import Exercise, ExerciseGrade, Submission, Worksheet, WorksheetItem
from finances.models import Payment
from schedule.models import Lesson, LessonComment, WeeklyRule
from school.models import SchoolClass, SchoolLesson, SchoolStudent, SchoolWeeklyRule
from students.models import Student, Subject, Topic


ARCHIVE_FORMAT = "tutoring-web-app.backup"
ARCHIVE_VERSION = 2
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_ARCHIVE_FILES = 20_000
MAX_MANIFEST_BYTES = 5_000_000
MAX_RECORDS_BYTES = 500_000_000
MODELS = (
    Student, Subject, Topic, WeeklyRule, Lesson, LessonComment,
    SchoolClass, SchoolStudent, SchoolWeeklyRule, SchoolLesson,
    Exercise, ExerciseGrade, Worksheet, WorksheetItem, Submission, Payment,
)
MODEL_LABELS = {model._meta.label_lower for model in MODELS}
MODELS_BY_LABEL = {model._meta.label_lower: model for model in MODELS}
SCHOOL_LABELS = {model._meta.label_lower for model in (SchoolClass, SchoolStudent, SchoolWeeklyRule, SchoolLesson)}


def _safe_media_name(value):
    if not isinstance(value, str) or "\\" in value or "\x00" in value or ":" in value.split("/")[0]:
        raise ValueError("Некорректный путь загруженной работы")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("Некорректный путь загруженной работы")
    return str(path)


def _write_file(archive, source, name):
    digest = hashlib.sha256()
    size = 0
    with archive.open(name, "w") as target:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
            target.write(chunk)
    return {"sha256": digest.hexdigest(), "size": size}


def create_archive():
    """Return a seekable temporary ZIP; the caller owns and closes it."""
    output = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    try:
        with transaction.atomic():
            records = []
            counts = {}
            for model in MODELS:
                rows = json.loads(serializers.serialize("json", model.objects.order_by("pk"), ensure_ascii=False))
                records.extend(rows)
                counts[model._meta.label_lower] = len(rows)
            upload_names = sorted({_safe_media_name(name) for name in Submission.objects.values_list("file", flat=True)})
            records_bytes = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                files = {}
                with archive.open("records.json", "w") as target:
                    target.write(records_bytes)
                files["records.json"] = {"sha256": hashlib.sha256(records_bytes).hexdigest(), "size": len(records_bytes)}
                media_root = Path(settings.MEDIA_ROOT).resolve()
                for name in upload_names:
                    source_path = (media_root / name).resolve()
                    if not source_path.is_relative_to(media_root) or not source_path.is_file():
                        raise ValueError(f"Не найдена загруженная работа: {name}")
                    with source_path.open("rb") as source:
                        files[f"uploads/{name}"] = _write_file(archive, source, f"uploads/{name}")
                manifest = {
                    "format": ARCHIVE_FORMAT, "version": ARCHIVE_VERSION,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "counts": counts, "files": files,
                }
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise


def _copy_and_check(source, expected, target=None):
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_ARCHIVE_BYTES:
            raise ValueError("Архив слишком большой")
        digest.update(chunk)
        if target:
            target.write(chunk)
    if size != expected.get("size") or digest.hexdigest() != expected.get("sha256"):
        raise ValueError("Контрольная сумма архива не совпадает")


def inspect_archive(upload, media_stage=None):
    if not upload or upload.size > MAX_ARCHIVE_BYTES:
        raise ValueError("Выберите архив размером до 1 ГБ")
    try:
        with zipfile.ZipFile(upload) as archive:
            info = archive.infolist()
            names = [item.filename for item in info]
            if len(info) > MAX_ARCHIVE_FILES or len(names) != len(set(names)):
                raise ValueError("Неверная структура архива")
            if "manifest.json" not in names or "records.json" not in names:
                raise ValueError("Архив приложения неполный")
            if sum(item.file_size for item in info) > MAX_ARCHIVE_BYTES:
                raise ValueError("Распакованный архив слишком большой")
            sizes = {item.filename: item.file_size for item in info}
            if sizes["manifest.json"] > MAX_MANIFEST_BYTES or sizes["records.json"] > MAX_RECORDS_BYTES:
                raise ValueError("Служебные файлы архива слишком большие")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_FORMAT or manifest.get("version") not in (1, ARCHIVE_VERSION):
                raise ValueError("Неподдерживаемый формат резервной копии")
            files = manifest.get("files")
            if not isinstance(files, dict) or set(names) != {"manifest.json", *files}:
                raise ValueError("Неверный список файлов архива")
            for name in files:
                if name != "records.json":
                    if not name.startswith("uploads/"):
                        raise ValueError("Неверный путь файла в архиве")
                    _safe_media_name(name.removeprefix("uploads/"))
            records_bytes = archive.read("records.json")
            _copy_and_check(io.BytesIO(records_bytes), files["records.json"])
            records = json.loads(records_bytes)
            if not isinstance(records, list):
                raise ValueError("Неверные записи в архиве")
            counts = {label: 0 for label in MODEL_LABELS}
            ids = set()
            submission_files = set()
            for row in records:
                if not isinstance(row, dict) or set(row) != {"model", "pk", "fields"} or row["model"] not in MODEL_LABELS or not isinstance(row["fields"], dict):
                    raise ValueError("Неверная запись в архиве")
                key = (row["model"], str(row["pk"]))
                if key in ids:
                    raise ValueError("Повторяющийся ID в архиве")
                ids.add(key)
                counts[row["model"]] += 1
                if row["model"] == Submission._meta.label_lower:
                    submission_files.add(f"uploads/{_safe_media_name(row['fields'].get('file', ''))}")
            expected_labels = MODEL_LABELS if manifest["version"] == ARCHIVE_VERSION else MODEL_LABELS - SCHOOL_LABELS
            expected_counts = {label: counts[label] for label in expected_labels}
            if (manifest.get("counts") != expected_counts
                    or (manifest["version"] == 1 and any(counts[label] for label in SCHOOL_LABELS))
                    or submission_files != set(files) - {"records.json"}):
                raise ValueError("Содержимое архива не соответствует описанию")
            for row in records:
                model = MODELS_BY_LABEL[row["model"]]
                for field in model._meta.fields:
                    if not field.many_to_one or field.related_model not in MODELS:
                        continue
                    related_id = row["fields"].get(field.name)
                    if related_id is None:
                        if not field.null:
                            raise ValueError("В архиве отсутствует обязательная связь")
                    elif (field.related_model._meta.label_lower, str(related_id)) not in ids:
                        raise ValueError("В архиве есть ссылка на отсутствующую запись")
            try:
                for _ in serializers.deserialize("json", records_bytes.decode("utf-8")):
                    pass
            except (DeserializationError, ValidationError, ValueError, TypeError) as exc:
                raise ValueError("Некорректные записи в резервной копии") from exc
            for name in sorted(set(files) - {"records.json"}):
                with archive.open(name) as source:
                    if media_stage:
                        target_path = media_stage / name.removeprefix("uploads/")
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        with target_path.open("wb") as target:
                            _copy_and_check(source, files[name], target)
                    else:
                        _copy_and_check(source, files[name])
            return records, counts, manifest["created_at"]
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Не удалось прочитать резервную копию") from exc


def restore_archive(upload):
    """Replace all application records, retaining a local recovery copy."""
    data_root = Path(settings.DATA_DIR)
    media_root = Path(settings.MEDIA_ROOT)
    with tempfile.TemporaryDirectory(prefix="restore-", dir=data_root) as staging:
        staged_media = Path(staging) / "uploads"
        staged_media.mkdir()
        records, counts, _ = inspect_archive(upload, staged_media)
        backups = data_root / "backups"
        backups.mkdir(exist_ok=True)
        recovery_path = backups / f"before-restore-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.zip"
        current_archive = create_archive()
        try:
            with recovery_path.open("wb") as target:
                shutil.copyfileobj(current_archive, target)
        finally:
            current_archive.close()
        old_media = data_root / f"uploads-before-restore-{uuid.uuid4().hex}"
        moved_old = moved_new = False
        try:
            with transaction.atomic():
                for model in reversed(MODELS):
                    model.objects.all().delete()
                for item in serializers.deserialize("json", json.dumps(records, ensure_ascii=False)):
                    item.save()
                if media_root.exists():
                    media_root.rename(old_media)
                    moved_old = True
                staged_media.rename(media_root)
                moved_new = True
        except Exception as exc:
            if moved_new:
                shutil.rmtree(media_root)
            if moved_old:
                old_media.rename(media_root)
            if isinstance(exc, (IntegrityError, DeserializationError, ValidationError)):
                raise ValueError("Не удалось восстановить записи из архива; текущие данные сохранены") from exc
            raise
        if moved_old:
            shutil.rmtree(old_media)
    return {"counts": counts, "recovery_file": recovery_path.name}

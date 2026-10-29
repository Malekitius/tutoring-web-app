"""Validated, portable PNG figures attached to task snapshots."""

import base64
import binascii
import io

from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

from .models import TaskFigure


MAX_FIGURES = 5
MAX_FIGURE_BYTES = 2 * 1024 * 1024


def figure_data(row):
    if not isinstance(row, dict) or set(row) != {"png", "source_title", "source_page"}:
        raise ValueError("Некорректный рисунок задачи")
    encoded = row["png"]
    if not isinstance(encoded, str) or len(encoded) > MAX_FIGURE_BYTES * 4 // 3 + 100:
        raise ValueError("Рисунок слишком большой")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Некорректные данные рисунка") from None
    if len(image) > MAX_FIGURE_BYTES or not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Нужен рисунок PNG размером до 2 МБ")
    try:
        with Image.open(io.BytesIO(image)) as picture:
            if picture.format != "PNG" or not 60 <= picture.width <= 4000 or not 60 <= picture.height <= 4000:
                raise ValueError("Некорректный размер рисунка")
            picture.verify()
    except (UnidentifiedImageError, OSError):
        raise ValueError("Не удалось прочитать рисунок") from None
    title = row["source_title"]
    page = row["source_page"]
    if not isinstance(title, str) or len(title) > 160 or type(page) is not int or not 1 <= page <= 1000:
        raise ValueError("Некорректный источник рисунка")
    return image, title, page


def validate_figures(rows):
    if rows is None:
        return []
    if not isinstance(rows, list) or len(rows) > MAX_FIGURES:
        raise ValueError("К задаче можно добавить до пяти рисунков")
    return [figure_data(row) for row in rows]


def save_figures(owner, rows):
    key = "exercise" if owner._meta.model_name == "exercise" else "worksheet_item" if owner._meta.model_name == "worksheetitem" else "school_item"
    for position, (content, title, page) in enumerate(rows):
        figure = TaskFigure(**{key: owner}, position=position, source_title=title, source_page=page)
        figure.file.save("figure.png", ContentFile(content), save=False)
        figure.save()


def copy_figures(source, owner):
    rows = []
    for figure in source.figures.all():
        with figure.file.open("rb") as stream:
            rows.append((stream.read(), figure.source_title, figure.source_page))
    save_figures(owner, rows)


def serialize_figures(owner):
    return [{"id": str(item.id), "url": f"/api/assignments/figures/{item.id}/file",
             "source_title": item.source_title, "source_page": item.source_page}
            for item in owner.figures.all()]

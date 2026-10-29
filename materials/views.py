"""Local PDF attachments for individual students and school classes."""

import io
import base64
import math
import re
import uuid
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.http import HttpResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from school.models import SchoolClass
from students.models import Student
from students.views import body, fail, text

from .models import Material, MaterialPage


MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_PAGES = 1000
KINDS = {choice[0] for choice in Material.KIND_CHOICES}


def owner_from(request):
    raw_student = request.POST.get("student_id") if request.method == "POST" else request.GET.get("student_id")
    raw_class = request.POST.get("class_id") if request.method == "POST" else request.GET.get("class_id")
    if bool(raw_student) == bool(raw_class):
        raise ValueError("Выберите ученика или класс")
    try:
        owner_id = uuid.UUID(raw_student or raw_class)
    except (TypeError, ValueError):
        raise ValueError("Некорректный ID карточки") from None
    if raw_student:
        owner = Student.objects.filter(id=owner_id).first()
        field = "student"
    else:
        owner = SchoolClass.objects.filter(id=owner_id).first()
        field = "school_class"
    if owner is None:
        raise LookupError("Карточка не найдена")
    return field, owner


def serialize(item):
    return {
        "id": str(item.id), "title": item.title, "kind": item.kind,
        "original_name": item.original_name, "page_count": item.page_count,
        "text_page_count": item.text_page_count,
        "created_at": item.created_at.isoformat(),
        "url": f"/api/materials/{item.id}/file",
    }


def validate_pdf(upload):
    if not upload or upload.size < 8 or upload.size > MAX_PDF_BYTES:
        raise ValueError("Выберите PDF размером до 30 МБ")
    filename = Path(upload.name.replace("\\", "/")).name
    if not filename.lower().endswith(".pdf") or len(filename) > 255:
        raise ValueError("Загрузите файл с расширением .pdf")
    data = upload.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF-"):
        raise ValueError("Файл не является PDF")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("PDF с паролем не поддерживается")
        page_count = len(reader.pages)
        if not 1 <= page_count <= MAX_PAGES:
            raise ValueError("PDF должен содержать от 1 до 1000 страниц")
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                extracted = page.extract_text() or ""
            except (PdfReadError, ValueError, TypeError):
                extracted = ""
            cleaned = re.sub(r"[\t\r ]+", " ", extracted).strip()[:20000]
            pages.append((index, cleaned))
    except (PdfReadError, KeyError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, ValueError) and str(exc) in {"PDF с паролем не поддерживается", "PDF должен содержать от 1 до 1000 страниц"}:
            raise
        raise ValueError("Не удалось прочитать PDF. Проверьте файл") from exc
    return filename, data, pages


def collection(request):
    if request.method not in {"GET", "POST"}:
        return fail("Метод не поддерживается", 405)
    try:
        field, owner = owner_from(request)
        if request.method == "GET":
            items = Material.objects.filter(**{field: owner})
            return JsonResponse([serialize(item) for item in items], safe=False)
        title = text(request.POST.get("title", ""), "Название материала", 160, True)
        kind = request.POST.get("kind", "other")
        if kind not in KINDS:
            raise ValueError("Выберите тип материала")
        filename, data, pages = validate_pdf(request.FILES.get("file"))
        with transaction.atomic():
            item = Material(**{field: owner}, title=title, kind=kind,
                            original_name=filename, page_count=len(pages),
                            text_page_count=sum(bool(value) for _, value in pages))
            item.file.save(filename, ContentFile(data), save=False)
            try:
                item.save()
                MaterialPage.objects.bulk_create(MaterialPage(material=item, number=number, text=value)
                                                 for number, value in pages)
            except Exception:
                item.file.delete(save=False)
                raise
        return JsonResponse(serialize(item), status=201)
    except ValueError as exc:
        return fail(str(exc))
    except LookupError as exc:
        return fail(str(exc), 404)


def detail(request, material_id):
    if request.method != "DELETE":
        return fail("Метод не поддерживается", 405)
    item = Material.objects.filter(id=material_id).first()
    if item is None:
        return fail("Материал не найден", 404)
    item.delete()
    return JsonResponse({"ok": True})


@xframe_options_sameorigin
def file_view(request, material_id):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    item = Material.objects.filter(id=material_id).first()
    if item is None or not item.file:
        return fail("Материал не найден", 404)
    try:
        return FileResponse(item.file.open("rb"), content_type="application/pdf", filename=item.original_name)
    except FileNotFoundError:
        return fail("PDF отсутствует на диске", 404)


def page_image(request, material_id, page_number):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    item = Material.objects.filter(id=material_id).first()
    if item is None or not 1 <= page_number <= item.page_count:
        return fail("Страница не найдена", 404)
    try:
        document = pdfium.PdfDocument(item.file.path)
        try:
            page = document[page_number - 1]
            try:
                scale = min(1.8, 3000 / max(1, *page.get_size()))
                bitmap = page.render(scale=scale)
                try:
                    output = io.BytesIO()
                    bitmap.to_pil().save(output, format="PNG")
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            document.close()
        response = HttpResponse(output.getvalue(), content_type="image/png")
        response["Cache-Control"] = "private, max-age=300"
        return response
    except (FileNotFoundError, pdfium.PdfiumError, RuntimeError, ValueError):
        return fail("Не удалось открыть страницу PDF", 404)


def crop_figure(request, material_id):
    """Render a selected rectangle of a page; coordinates are fractions of the page."""
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    item = Material.objects.filter(id=material_id).first()
    if item is None:
        return fail("Материал не найден", 404)
    try:
        data = body(request)
        page_number = int(data.get("page"))
        bounds = [float(data.get(key)) for key in ("x", "y", "width", "height")]
        x, y, width, height = bounds
        if not 1 <= page_number <= item.page_count or not all(map(math.isfinite, bounds)):
            raise ValueError("Некорректная страница или область рисунка")
        if not (0 <= x < 1 and 0 <= y < 1 and .02 <= width <= 1 - x and .02 <= height <= 1 - y):
            raise ValueError("Выделите область рисунка на странице")
        document = pdfium.PdfDocument(item.file.path)
        try:
            page = document[page_number - 1]
            try:
                page_width, page_height = page.get_size()
                scale = min(3, 4000 / max(1, page_width, page_height))
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    crop = image.crop((round(x * image.width), round(y * image.height),
                                       round((x + width) * image.width), round((y + height) * image.height)))
                    if crop.width < 60 or crop.height < 60:
                        raise ValueError("Выделенная область слишком мала")
                    crop.thumbnail((4000, 4000), Image.Resampling.LANCZOS)
                    crop = crop.convert("RGB")
                    for _ in range(6):
                        output = io.BytesIO()
                        crop.save(output, format="PNG", optimize=True)
                        if output.tell() <= 2 * 1024 * 1024:
                            break
                        crop.thumbnail((round(crop.width * .8), round(crop.height * .8)), Image.Resampling.LANCZOS)
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            document.close()
        if output.tell() > 2 * 1024 * 1024:
            raise ValueError("Рисунок слишком большой. Выделите меньшую область")
        return JsonResponse({"png": base64.b64encode(output.getvalue()).decode("ascii"),
                             "source_title": item.title, "source_page": page_number})
    except (TypeError, ValueError, OSError, pdfium.PdfiumError):
        return fail("Не удалось вырезать рисунок. Проверьте страницу и выделенную область")

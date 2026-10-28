"""Human-operated backup and restore endpoints for the local application."""

from datetime import datetime

from django.http import FileResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from students.views import api_errors, fail

from .portability import MODELS, create_archive, inspect_archive, restore_archive


@ensure_csrf_cookie
def data_page(request):
    return render(request, "data.html")


@api_errors
def backup_export(request):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    file = create_archive()
    name = f"tutor-backup-{datetime.now():%Y-%m-%d-%H%M}.zip"
    return FileResponse(file, as_attachment=True, filename=name, content_type="application/zip")


@api_errors
def backup_preview(request):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    _, counts, created_at = inspect_archive(request.FILES.get("file"))
    current = {model._meta.label_lower: model.objects.count() for model in MODELS}
    return JsonResponse({"archive": counts, "current": current, "created_at": created_at})


@api_errors
def backup_restore(request):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    if request.POST.get("confirm") != "RESTORE":
        return fail("Подтвердите восстановление всей базы")
    return JsonResponse(restore_archive(request.FILES.get("file")))

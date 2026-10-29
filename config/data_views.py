"""Human-operated backup and restore endpoints for the local application."""

from datetime import datetime

from django.http import FileResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from students.views import api_errors, fail

from .portability import SCOPES, scope_counts, create_archive, inspect_archive, restore_archive


@ensure_csrf_cookie
def data_page(request):
    mode = "school" if request.GET.get("mode") == "school" else "tutoring"
    return render(request, "data.html", {"mode": mode})


def request_scope(request):
    scope = (request.GET if request.method == "GET" else request.POST).get("scope", "all")
    if scope not in SCOPES:
        raise ValueError("Выберите раздел данных")
    return scope


@api_errors
def backup_export(request):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    scope = request_scope(request)
    file = create_archive(scope)
    name = f"{scope}-backup-{datetime.now():%Y-%m-%d-%H%M}.zip"
    return FileResponse(file, as_attachment=True, filename=name, content_type="application/zip")


@api_errors
def backup_preview(request):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    scope = request_scope(request)
    _, counts, created_at = inspect_archive(request.FILES.get("file"), scope=scope)
    return JsonResponse({"archive": counts, "current": scope_counts(scope), "created_at": created_at, "scope": scope})


@api_errors
def backup_restore(request):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    if request.POST.get("confirm") != "RESTORE":
        return fail("Подтвердите восстановление выбранных данных")
    return JsonResponse(restore_archive(request.FILES.get("file"), request_scope(request)))

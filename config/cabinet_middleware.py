from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.cache import add_never_cache_headers

from .cabinets import cabinet_directory, cabinet_scope


class CabinetMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.TUTOR_ACCOUNTS:
            return self.get_response(request)

        if request.path_info in {reverse("login"), reverse("logout"), reverse("register")}:
            response = self.get_response(request)
        elif not request.user.is_authenticated:
            if request.path_info.startswith("/api/"):
                response = JsonResponse({"error": "Войдите в личный кабинет"}, status=401)
            elif request.get_full_path() == "/":
                response = redirect("login")
            else:
                response = redirect_to_login(request.get_full_path(), reverse("login"))
        elif not (cabinet_directory(request.user.pk) / "db.sqlite3").is_file():
            response = HttpResponse("Личный кабинет ещё не настроен.", status=403)
        else:
            request.cabinet_active = True
            words = request.user.first_name.split()
            if len(words) > 1:
                initials = words[0][0] + words[1][0]
            else:
                initials = (words[0] if words else request.user.get_username())[:2]
            request.cabinet_initials = initials.upper()
            with cabinet_scope(request.user.pk):
                response = self.get_response(request)

        add_never_cache_headers(response)
        return response

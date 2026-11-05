import logging

from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.management import CommandError
from django.db import DatabaseError, IntegrityError
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .cabinets import provision_cabinet
from .models import CabinetPreferences


logger = logging.getLogger(__name__)


@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("index")

    form = UserCreationForm(request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        try:
            provision_cabinet(user)
        except (DatabaseError, OSError, CommandError) as exc:
            if isinstance(exc, IntegrityError) and type(user).objects.filter(username__iexact=user.username).exists():
                form.add_error("username", "Этот логин уже занят.")
            else:
                logger.exception("Could not provision a cabinet during registration")
                form.add_error(None, "Не удалось создать кабинет. Попробуйте ещё раз.")
                status = 503
        else:
            login(request, user)
            return redirect("index")
    return render(request, "register.html", {"form": form}, status=status)


def preferred_mode(user):
    stored = CabinetPreferences.objects.filter(user=user).values_list("start_mode", flat=True).first()
    return stored or CabinetPreferences.Mode.TUTORING


class CabinetLoginView(LoginView):
    template_name = "login.html"

    def get_default_redirect_url(self):
        if preferred_mode(self.request.user) == CabinetPreferences.Mode.SCHOOL:
            return reverse("school_classes")
        return super().get_default_redirect_url()


class CabinetPasswordChangeView(PasswordChangeView):
    template_name = "cabinet-password.html"
    success_url = reverse_lazy("cabinet_settings")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Пароль изменён.")
        return response


class StartModeForm(forms.Form):
    start_mode = forms.ChoiceField(
        label="Раздел после входа", choices=CabinetPreferences.Mode.choices,
    )


@require_http_methods(["GET", "POST"])
def cabinet_settings(request):
    form = StartModeForm(
        request.POST if request.method == "POST" else None,
        initial={"start_mode": preferred_mode(request.user)},
    )
    if request.method == "POST" and form.is_valid():
        CabinetPreferences.objects.update_or_create(
            user=request.user, defaults={"start_mode": form.cleaned_data["start_mode"]},
        )
        messages.success(request, "Стартовый раздел сохранён.")
        return redirect("cabinet_settings")
    return render(request, "cabinet-settings.html", {"form": form})

class DisplayNameForm(forms.Form):
    display_name = forms.CharField(
        label="Отображаемое имя",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )


@require_http_methods(["GET", "POST"])
def profile(request):
    form = DisplayNameForm(
        request.POST if request.method == "POST" else None,
        initial={"display_name": request.user.first_name},
    )
    if request.method == "POST" and form.is_valid():
        request.user.first_name = form.cleaned_data["display_name"]
        request.user.save(update_fields=["first_name"])
        return redirect("/profile/?saved=1")
    return render(request, "profile.html", {
        "form": form,
        "saved": request.method == "GET" and request.GET.get("saved") == "1",
    })

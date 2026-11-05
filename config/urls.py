from django.conf import settings
from django.contrib.auth.views import LogoutView
from django.contrib import admin
from django.urls import include, path

from students.views import index
from schedule.views import schedule_page
from finances.views import finances_page
from assignments.views import assignments_page
from school.views import classes_page, schedule_page as school_schedule_page, assignments_page as school_assignments_page
from . import data_views


urlpatterns = [
    path("", index, name="index"),
    path("schedule/", schedule_page, name="schedule"),
    path("school/", classes_page, name="school_classes"),
    path("school/schedule/", school_schedule_page, name="school_schedule"),
    path("school/assignments/", school_assignments_page, name="school_assignments"),
    path("finances/", finances_page, name="finances"),
    path("assignments/", assignments_page, name="assignments"),
    path("data/", data_views.data_page, name="data"),
    path("api/data/backup/export", data_views.backup_export),
    path("api/data/backup/preview", data_views.backup_preview),
    path("api/data/backup/restore", data_views.backup_restore),
    path("api/assistant/", include("assistant.urls")),
    path("api/assignments/", include("assignments.urls")),
    path("api/finances/", include("finances.urls")),
    path("api/schedule/", include("schedule.urls")),
    path("api/school/", include("school.urls")),
    path("api/materials/", include("materials.urls")),
    path("api/", include("students.urls")),
]

if settings.TUTOR_ACCOUNTS:
    from . import profile_views

    urlpatterns += [
        path("login/", profile_views.CabinetLoginView.as_view(), name="login"),
        path("register/", profile_views.register, name="register"),
        path("logout/", LogoutView.as_view(), name="logout"),
        path("profile/", profile_views.profile, name="profile"),
        path("settings/", profile_views.cabinet_settings, name="cabinet_settings"),
        path("settings/password/", profile_views.CabinetPasswordChangeView.as_view(), name="cabinet_password"),
    ]
else:
    urlpatterns.append(path("admin/", admin.site.urls))

from django.urls import path

from . import views


urlpatterns = [
    path("status", views.status),
    path("models", views.model_options),
    path("ask", views.ask),
    path("students/<uuid:student_id>/ask", views.ask_student),
    path("generate", views.generate_exercises),
    path("accept", views.accept_exercises),
    path("auth/start", views.auth_start),
    path("auth/callback/", views.auth_callback),
    path("auth/disconnect", views.auth_disconnect),
]

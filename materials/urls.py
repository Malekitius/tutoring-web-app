from django.urls import path

from . import views


urlpatterns = [
    path("", views.collection),
    path("<uuid:material_id>", views.detail),
    path("<uuid:material_id>/file", views.file_view),
]

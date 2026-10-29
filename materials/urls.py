from django.urls import path

from . import views


urlpatterns = [
    path("", views.collection),
    path("<uuid:material_id>", views.detail),
    path("<uuid:material_id>/file", views.file_view),
    path("<uuid:material_id>/page/<int:page_number>.png", views.page_image),
    path("<uuid:material_id>/crop", views.crop_figure),
]

from django.urls import path

from . import views


urlpatterns = [
    path("overview", views.overview),
    path("library/export", views.library_export),
    path("library/import", views.library_import),
    path("exercises", views.exercises_collection),
    path("exercises/<uuid:exercise_id>", views.exercise_detail),
    path("worksheets", views.worksheets_collection),
    path("worksheets/<uuid:worksheet_id>", views.worksheet_detail),
    path("worksheets/<uuid:worksheet_id>/pdf", views.worksheet_pdf),
    path("worksheets/<uuid:worksheet_id>/items", views.worksheet_items),
    path("worksheets/<uuid:worksheet_id>/items/batch", views.worksheet_items_batch),
    path("items/<uuid:item_id>", views.item_detail),
    path("worksheets/<uuid:worksheet_id>/submissions", views.submissions_collection),
    path("submissions/<uuid:submission_id>/file", views.submission_file),
    path("submissions/<uuid:submission_id>", views.submission_detail),
    path("figures/<uuid:figure_id>/file", views.figure_file),
]

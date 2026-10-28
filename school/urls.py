from django.urls import path

from . import views


urlpatterns = [
    path("classes", views.classes_collection),
    path("classes/<uuid:class_id>", views.class_detail),
    path("classes/<uuid:class_id>/students", views.class_students),
    path("students/<uuid:student_id>", views.student_detail),
    path("schedule", views.week_view),
    path("schedule/lessons", views.lessons_collection),
    path("schedule/lessons/<uuid:lesson_id>", views.lesson_detail),
    path("schedule/rules/<uuid:rule_id>", views.rule_detail),
    path("worksheets", views.worksheets_collection),
    path("worksheets/<uuid:worksheet_id>", views.worksheet_detail),
    path("worksheets/<uuid:worksheet_id>/pdf", views.worksheet_pdf),
]

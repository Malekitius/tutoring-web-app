from django.urls import path

from . import views


urlpatterns = [
    path("students", views.students_collection),
    path("students/<uuid:student_id>", views.student_detail),
    path("students/<uuid:student_id>/notes", views.student_notes),
    path("notes/<uuid:note_id>", views.note_detail),
    path("students/<uuid:student_id>/subjects", views.student_subjects),
    path("subjects/<uuid:subject_id>", views.subject_detail),
    path("subjects/<uuid:subject_id>/topics", views.subject_topics),
    path("topics/<uuid:topic_id>", views.topic_detail),
]

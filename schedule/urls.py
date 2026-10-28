from django.urls import path

from .views import comment_detail, lesson_comments, lesson_detail, lessons_collection, rule_detail, week_view


urlpatterns = [
    path("", week_view),
    path("lessons", lessons_collection),
    path("lessons/<uuid:lesson_id>", lesson_detail),
    path("lessons/<uuid:lesson_id>/comments", lesson_comments),
    path("comments/<uuid:comment_id>", comment_detail),
    path("rules/<uuid:rule_id>", rule_detail),
]

from django.contrib import admin

from .models import Lesson, LessonComment, WeeklyRule


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("student", "subject", "date", "time", "duration_min", "status")
    list_filter = ("status", "date")


@admin.register(WeeklyRule)
class WeeklyRuleAdmin(admin.ModelAdmin):
    list_display = ("student", "subject", "weekday", "time", "start_date", "end_date")


@admin.register(LessonComment)
class LessonCommentAdmin(admin.ModelAdmin):
    list_display = ("student", "lesson", "priority", "due_date", "created_at")
    list_filter = ("priority", "due_date")

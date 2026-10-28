from django.contrib import admin

from .models import Student, Subject, Topic


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("name", "grade", "status", "price_rub")
    search_fields = ("name",)
    list_filter = ("grade", "status")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("student", "name", "level")
    list_filter = ("name", "level")


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "mastery")
    list_filter = ("mastery",)

from django.contrib import admin

from .models import SchoolClass, SchoolLesson, SchoolStudent, SchoolWeeklyRule


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "level")
    search_fields = ("name", "subject")


@admin.register(SchoolStudent)
class SchoolStudentAdmin(admin.ModelAdmin):
    list_display = ("name", "school_class", "group", "birth_date")
    list_filter = ("group",)
    search_fields = ("name",)


admin.site.register(SchoolWeeklyRule)
admin.site.register(SchoolLesson)

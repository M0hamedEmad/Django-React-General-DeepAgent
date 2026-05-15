from django.contrib import admin

from deep_agent_app.models import Thread


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "updated_at")
    search_fields = ("id", "title", "user__username")

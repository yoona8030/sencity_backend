from django.contrib import admin
from .models import Event

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "user", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("user__username",)

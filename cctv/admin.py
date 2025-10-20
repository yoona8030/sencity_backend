# cctv/admin.py
from django.contrib import admin
from .models import Camera

@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active", "stream_url")
    list_filter = ("is_active",)
    search_fields = ("name", "stream_url")

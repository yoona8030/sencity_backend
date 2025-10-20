# cctv/models.py
from django.db import models

class Camera(models.Model):
    name = models.CharField(max_length=50)
    stream_url = models.URLField(help_text="예: http://<esp32-ip>:81/stream")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.id}: {self.name}"

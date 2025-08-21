# api/models.py
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from datetime import datetime
from django.db import models

class User(AbstractUser):
    email = models.EmailField(unique=True)
    telphone = models.CharField(max_length=20, blank=True)
    user_address = models.CharField(max_length=255, blank=True)
    agree = models.BooleanField(default=False)

    def __str__(self):
        return self.username

    class Meta:
        verbose_name = 'Users'
        verbose_name_plural = 'Users'

class Animal(models.Model):
    name_kor = models.CharField(max_length=50)
    name_eng = models.CharField(max_length=50)
    image_url = models.URLField(blank=True)
    description = models.TextField(blank=True)
    features = models.JSONField(default=list, blank=True)
    precautions = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.name_kor

    class Meta:
        verbose_name = 'Animal'
        verbose_name_plural = 'Animal'


class SearchHistory(models.Model):
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='search_histories'
    )
    keyword = models.CharField(max_length=100)
    searched_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} – {self.keyword}"

    class Meta:
        verbose_name = 'SearchHistory'
        verbose_name_plural = 'SearchHistory'
        ordering = ['-searched_at']


class Location(models.Model):
    latitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    city = models.CharField(max_length=50, blank=True)        # 시
    district = models.CharField(max_length=50, blank=True)    # 구/동
    region = models.CharField(max_length=100, blank=True, default='', db_index=True)  # 랜드마크명
    address = models.CharField(max_length=255, blank=True)    # 전체 주소

    class Meta:
        ordering = ['-id']
        indexes = [
            models.Index(fields=["city", "district"]),
            models.Index(fields=["latitude", "longitude"]),
        ]
    
    constraints = [
            models.UniqueConstraint(
                fields=['latitude', 'longitude', 'city', 'district', 'region', 'address'],
                name='unique_location_lat_lon'
            )
        ]

    def __str__(self):
        return f"Location#{self.id} - {self.region or self.address or f'{self.latitude},{self.longitude}'}"

class Report(models.Model):
    STATUS_CHOICES = [
        ('checking',  '접수 완료'),
        ('on_hold',   '보류'),
        ('completed', '답변 완료'),
    ]

    user = models.ForeignKey(
        'api.User',
        on_delete=models.CASCADE,
        related_name='api_reports',
        db_index=True,
    )
    animal = models.ForeignKey(
        'api.Animal',
        on_delete=models.CASCADE,
        related_name='reports',
        db_index=True,
    )

    # 🔹 FK 방향 변경: Report → Location
    location = models.ForeignKey(
        'api.Location',
        on_delete=models.CASCADE,
        related_name='reports',
        null=True,
        db_index=True
    )

    report_date = models.DateTimeField(db_index=True)
    image = models.ImageField(upload_to='reports/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='checking') 

    def __str__(self):
        animal_name = getattr(self.animal, 'name_kor', str(self.animal)) if self.animal else "Unknown"
        if hasattr(self.report_date, "strftime"):
            date_str = self.report_date.strftime("%Y-%m-%d %H:%M")
        else:
            date_str = str(self.report_date)
        return f"{self.user} – {animal_name} ({date_str})"
    
    class Meta:
        ordering = ['-report_date']
        indexes = [
            models.Index(fields=['report_date']),
            models.Index(fields=['status', 'report_date']),
            models.Index(fields=['animal', 'report_date']),
            models.Index(fields=['user', 'report_date']),
        ]
        
class Notification(models.Model):
    TYPE_CHOICES = [
        ('group', '그룹 알림'),
        ('single', '개별 알림'),
    ]

    user = models.ForeignKey(
        'api.User',
        on_delete=models.CASCADE,
        related_name='notifications',
        db_index=True,
    )

    type = models.CharField(max_length=10, choices=TYPE_CHOICES, db_index=True)
    STATUS_CHANGE_CHOICES = [
        ('checking->on_hold', '접수 완료 → 보류'),
        ('checking->completed', '접수 완료 → 답변 완료'),
        ('on_hold->completed', '보류 → 답변 완료'),
    ]
    reply = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'type', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.get_type_display()}] to {self.user}"


class Feedback(models.Model):
    feedback_id = models.AutoField(primary_key=True)

    report = models.ForeignKey(
        'api.Report',
        on_delete=models.CASCADE,
        related_name='feedbacks',
        db_index=True
    )

    user = models.ForeignKey(
        'api.User',
        on_delete=models.CASCADE,
        related_name='user_feedbacks',
        db_index=True
    )

    admin = models.ForeignKey(
        'api.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_feedbacks',
        db_index=True
    )

    content = models.TextField()

    feedback_datetime = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-feedback_datetime']
        indexes = [
            models.Index(fields=['report', 'user', 'feedback_datetime']),
        ]

    def __str__(self):
        return f"Feedback #{self.feedback_id} on Report #{self.report_id}"


class Statistic(models.Model):
    STATE_UNIT_CHOICES = [
        ('year',  'year'),
        ('month', 'month'),
    ]

    state_unit = models.CharField(max_length=10, choices=STATE_UNIT_CHOICES)
    state_year = models.IntegerField()
    state_month = models.IntegerField(default=0)
    all_reports = models.IntegerField(default=0)
    completed = models.IntegerField(default=0)
    incomplete = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.state_year}-{self.state_month}" if self.state_unit == 'month' else f"{self.state_year}"

    class Meta:
        verbose_name = 'Statistic'
        verbose_name_plural = 'Statistic'
        ordering = ['-state_year', '-state_month']

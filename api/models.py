from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.db.models import Q
from datetime import datetime
from django.db import models
from django.conf import settings

class Admin(models.Model):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100)
    password = models.CharField(max_length=128)  # 실제 서비스에서는 해싱 필수

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='admin',
        null=True, blank=True
    )

    display_name = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.display_name or f'Admin({self.email})'

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

class AnimalGroup(models.Model):
    slug = models.SlugField(max_length=50, unique=True, db_index=True)
    name_kor = models.CharField(max_length=50)
    name_eng = models.CharField(max_length=50, blank=True)

class Animal(models.Model):
    code = models.SlugField(max_length=50, db_index=True, unique=True)
    name_kor = models.CharField(max_length=50, unique=True)
    name_eng = models.CharField(max_length=50)
    aliases_eng = models.JSONField(default=list, blank=True)
    group = models.ForeignKey('api.AnimalGroup', null=True, blank=True,
                              on_delete=models.SET_NULL, related_name='animals')

    image = models.ImageField(upload_to='animals/', blank=True, null=True)
    description = models.TextField(blank=True)
    features = models.JSONField(default=list, blank=True)
    precautions = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.name_kor

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
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'keyword'],
                name='uniq_searchhistory_user_keyword',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'keyword']),
        ]

class Location(models.Model):
    latitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    city = models.CharField(max_length=50, blank=True)
    district = models.CharField(max_length=50, blank=True)
    region = models.CharField(max_length=100, blank=True, default='', db_index=True)
    address = models.CharField(max_length=255, blank=True)

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

class SavedPlace(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_places',
        db_index=True,
    )
    name = models.CharField(max_length=100)
    location = models.ForeignKey(
        'api.Location',
        on_delete=models.CASCADE,
        related_name='saved_places',
        db_index=True,
    )
    latitude  = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    client_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'client_id'],
                                    name='uniq_user_client_id')
        ]

    def __str__(self):
        return f"{self.user} saved {self.name}"

# 지도 화면 배너 알림(앱 내 배너)
class AppBanner(models.Model):
    text = models.CharField(max_length=140)
    cta_url = models.CharField(max_length=300, blank=True, default="")
    audience = models.CharField(max_length=20, default="all")
    starts_at  = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    priority = models.IntegerField(default=0)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-priority", "-id"]

    def is_live(self):
        now = timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at   and self.ends_at   < now:
            return False
        return True

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
        null=True,
        blank=True
    )
    animal = models.ForeignKey(
        'api.Animal',
        on_delete=models.CASCADE,
        related_name='reports',
        db_index=True,
    )
    location = models.ForeignKey(
        'api.Location',
        on_delete=models.CASCADE,
        related_name='reports',
        null=True,
        db_index=True
    )

    report_date = models.DateTimeField(db_index=True)
    image = models.ImageField(upload_to='reports/%Y/%m/%d/', null=True, blank=True)
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
        ('individual', '개별 알림'),
    ]

    STATUS_CHANGE_CHOICES = [
        ('checking->on_hold', '접수 완료 → 보류'),
        ('checking->completed', '접수 완료 → 답변 완료'),
        ('on_hold->completed', '보류 → 답변 완료'),
    ]

    user = models.ForeignKey('api.User', on_delete=models.CASCADE,
                             related_name='notifications', db_index=True,
                             null=True, blank=True)

    admin = models.ForeignKey(
        'api.Admin',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
    )

    report = models.ForeignKey('Report', null=True, blank=True,
                               on_delete=models.SET_NULL, related_name='notifications')

    type = models.CharField(max_length=10, choices=TYPE_CHOICES, db_index=True)
    reply = models.TextField(null=True, blank=True)
    status_change = models.CharField(
        max_length=24, choices=STATUS_CHANGE_CHOICES,
        null=True, blank=True, db_index=True,
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'type', 'created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                name='notif_individual_requires_user',
                check=(Q(type='individual') & Q(user__isnull=False)) | ~Q(type='individual'),
            ),
            models.CheckConstraint(
                name='notif_group_requires_no_user',
                check=(Q(type='group') & Q(user__isnull=True)) | ~Q(type='group'),
            ),
        ]

    def __str__(self):
        base = f'[{self.type}]'
        if self.type == 'individual' and self.user_id:
            base += f' to {self.user_id}'
        return base

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
        ordering = ['-feedback_id']
        indexes = [
            models.Index(fields=['report', 'user', 'feedback_datetime'] ),
        ]
        constraints = [
            models.UniqueConstraint(fields=['report'], name='uniq_one_feedback_per_report'),
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

class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    consent_terms = models.BooleanField(default=False)
    consent_location = models.BooleanField(default=False)
    consent_marketing = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.user} profile'

# -------------------------------
# ✅ 공지 발송을 위한 모델 추가
# -------------------------------
class Notice(models.Model):
    """대시보드에서 작성하는 공지(푸시/WS 공통 원본)."""
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    target = models.CharField(max_length=20, default='all')  # all/group/user 등
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'[{self.target}] {self.title}'

class DeviceToken(models.Model):
    PLATFORM_CHOICES = (
      ("android", "Android"),
      ("ios", "iOS"),
      ("web", "Web"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    token = models.CharField(max_length=300, unique=True)
    platform = models.CharField(max_length=20, default='android')
    is_active = models.BooleanField(default=True)
    last_seen = models.DateTimeField(auto_now=True)  # ✅ 불량 토큰 관리/통계용

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        who = getattr(self.user, "username", None) or "anon"
        return f"{who}:{self.platform}:{(self.token or '')[:12]}…"

class NoticeDelivery(models.Model):
    """공지 × 토큰별 실제 발송 기록 (중복 방지/성공·실패 기록)."""
    notice = models.ForeignKey(Notice, on_delete=models.CASCADE, related_name='deliveries')
    device_token = models.ForeignKey(DeviceToken, on_delete=models.CASCADE, related_name='deliveries')
    status = models.CharField(max_length=20, choices=(('success','success'), ('failure','failure')))
    fcm_msg_id = models.CharField(max_length=200, blank=True, null=True)
    error_code = models.CharField(max_length=100, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('notice', 'device_token')  # ✅ 같은 공지에 같은 토큰 중복 저장 금지
        indexes = [
            models.Index(fields=['notice', 'status']),
            models.Index(fields=['device_token', 'status']),
        ]

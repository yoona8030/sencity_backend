# inquiries/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL

class Inquiry(models.Model):
    class Category(models.TextChoices):
        ACCOUNT = '계정', '계정'
        PAYMENT = '결제', '결제'
        REPORT  = '신고/제보', '신고/제보'
        BUG     = '버그', '버그'
        FEATURE = '기능요청', '기능요청'
        ETC     = '기타', '기타'

    class Status(models.TextChoices):
        OPEN     = 'open', 'open'
        PENDING  = 'pending', 'pending'
        ANSWERED = 'answered', 'answered'
        CLOSED   = 'closed', 'closed'
        DELETED  = 'deleted', 'deleted'

    class Priority(models.TextChoices):
        LOW    = 'low', 'low'
        NORMAL = 'normal', 'normal'
        HIGH   = 'high', 'high'

    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='inquiries')
    admin       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_inquiries')
    title       = models.CharField(max_length=200)
    category    = models.CharField(max_length=20, choices=Category.choices, default=Category.ETC)
    status      = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    priority    = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)

    created_at  = models.DateTimeField(default=timezone.now)
    updated_at  = models.DateTimeField(auto_now=True)
    last_user_msg_at  = models.DateTimeField(null=True, blank=True)
    last_admin_msg_at = models.DateTimeField(null=True, blank=True)
    user_last_read_at  = models.DateTimeField(null=True, blank=True)
    admin_last_read_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"[{self.pk}] {self.title} ({self.status})"

    class Meta:
        indexes = [
            models.Index(fields=['user', 'status', '-updated_at']),
        ]


class InquiryMessage(models.Model):
    class SenderType(models.TextChoices):
        USER   = 'user', 'user'
        ADMIN  = 'admin', 'admin'
        SYSTEM = 'system', 'system'

    inquiry         = models.ForeignKey(Inquiry, on_delete=models.CASCADE, related_name='messages')
    sender_type     = models.CharField(max_length=10, choices=SenderType.choices)
    sender_user     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='inquiry_messages_sent_as_user')
    sender_admin    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='inquiry_messages_sent_as_admin')
    body            = models.TextField()
    attachment_url  = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=['inquiry', 'created_at']),
        ]
        ordering = ['created_at']

class InquiryAttachment(models.Model):
    message = models.ForeignKey('InquiryMessage', on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='inquiries/%Y/%m/%d/')  # 또는 ImageField
    mime = models.CharField(max_length=100, blank=True)
    size = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)


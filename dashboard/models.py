from django.db import models
from django.conf import settings

class CCTVDevice(models.Model):
    name           = models.CharField("장치 이름", max_length=100)
    status         = models.CharField("상태", max_length=10,
                        choices=[('ONLINE','ONLINE'), ('OFFLINE','OFFLINE')])
    last_heartbeat = models.DateTimeField("마지막 신호 수신 시간", auto_now=True)

    def __str__(self):
        return self.name

class MotionSensor(models.Model):
    device      = models.ForeignKey(CCTVDevice, on_delete=models.CASCADE, related_name='sensors')
    status      = models.CharField("감지 상태", max_length=10,
                        choices=[('감지됨','감지됨'), ('오프라인','오프라인')])
    detected_at = models.DateTimeField("감지 시각", auto_now=True)

    def __str__(self):
        return f"{self.device.name} 센서"

class Animal(models.Model):
    name = models.CharField("동물명", max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Report(models.Model):
    # 새 필드
    title        = models.CharField("신고 제목", max_length=200, blank=True)
    animal       = models.ForeignKey(Animal, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="reports")

    # 기존 필드 (호환용) - 나중에 제거 예정
    animal_name  = models.CharField("동물 이름", max_length=50, blank=True)

    report_date   = models.DateTimeField("신고 일시")
    status        = models.CharField("처리 상태", max_length=20)
    report_region = models.CharField("신고 지역", max_length=255)
    user          = models.ForeignKey(settings.AUTH_USER_MODEL,
                                      on_delete=models.CASCADE, related_name='reports')
    latitude      = models.FloatField("위도")
    longitude     = models.FloatField("경도")

    def __str__(self):
        return f"[{self.animal or self.animal_name}] {self.title or ''}".strip()


class Prediction(models.Model):
    device    = models.ForeignKey(
        'CCTVDevice', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='predictions'
    )  # 어느 카메라에서 나온 결과인지(없으면 비워도 됨)
    image     = models.ImageField(upload_to="predictions/", blank=True, null=True)  # 썸네일 저장 안 쓰면 null/blank OK
    filename  = models.CharField(max_length=255, blank=True)  # 업로드 파일명 또는 "cctv:0" 같은 식별자
    label     = models.CharField(max_length=200)
    score     = models.FloatField()
    source    = models.CharField(max_length=50, default="cctv")  # "api" / "cctv" 등 구분용
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['created_at']), models.Index(fields=['label'])]

    def __str__(self):
        return f"{self.label} ({self.score:.2f})"

class DashboardSetting(models.Model):
    PERIOD = [("all","전체"),("7d","최근7일"),("30d","최근30일")]
    SORT   = [("newest","최신순"),("oldest","오래된순")]
    MAP    = [("kakao","Kakao"),("naver","Naver"),("google","Google")]

    # 기본 보기
    default_period = models.CharField(max_length=10, choices=PERIOD, default="all")
    default_sort   = models.CharField(max_length=10, choices=SORT,   default="newest")

    # 미해결/지연
    unresolved_statuses  = models.JSONField(default=list)      # ["접수","처리중",...]
    aging_threshold_days = models.PositiveSmallIntegerField(default=3)

    # 알림(대시보드용)
    notify_status_change = models.BooleanField(default=True)
    quiet_hours_start    = models.TimeField(null=True, blank=True)
    quiet_hours_end      = models.TimeField(null=True, blank=True)

    # 유지보수 배너(대시보드용)
    maintenance_mode     = models.BooleanField(default=False)
    maintenance_message  = models.CharField(max_length=200, blank=True, default="")

    # 지도(대시보드에서 미리보기 필요 시)
    map_provider         = models.CharField(max_length=10, choices=MAP, default="kakao")
    map_api_key          = models.CharField(max_length=255, blank=True, default="")

    updated_at           = models.DateTimeField(auto_now=True)

    def to_dict(self):
        return {
            "page_size": self.page_size,
            "default_period": self.default_period,
            "default_sort": self.default_sort,
            "notify_sound": self.notify_sound,
            "notify_desktop": self.notify_desktop,
            "date_format": self.date_format,
            "mask_reporter": self.mask_reporter,
        }

    def update_from_dict(self, data: dict):
        for k in ["page_size","default_period","default_sort","notify_sound",
                  "notify_desktop","date_format","mask_reporter"]:
            if k in data:
                setattr(self, k, data[k])

    class Meta:
        verbose_name = "대시보드 설정"
        verbose_name_plural = "대시보드 설정"

    def __str__(self):
        return "DashboardSetting"

    @classmethod
    def get_solo(cls):
        obj = cls.objects.first()
        if obj:
            return obj
        # 합리적 기본값
        return cls.objects.create(
            unresolved_statuses=["접수","처리중","미처리","대기"],
            aging_threshold_days=3,
        )

class Notification(models.Model):
    TYPE_CHOICES = [
        ("GLOBAL", "전체 공지"),
        ("GROUP",  "그룹 공지"),
        ("PERSON", "개인 알림"),
    ]
    STATUS_CHOICES = [
        ("POSTED",    "게시중"),
        ("SCHEDULED", "예약"),
        ("ENDED",     "종료"),
    ]

    title       = models.CharField(max_length=200)
    body        = models.TextField(blank=True)
    type        = models.CharField(max_length=10, choices=TYPE_CHOICES, default="GLOBAL")
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default="POSTED")
    start_at    = models.DateTimeField(null=True, blank=True)
    end_at      = models.DateTimeField(null=True, blank=True)
    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="notices_created")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    # 대상: 그룹/개인 (type 에 따라 사용)
    groups      = models.ManyToManyField("auth.Group", blank=True, related_name="notices")
    users       = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="personal_notices")

    class Meta:
        ordering = ["-created_at"]

class NoticeDelivery(models.Model):
    """개별 사용자 단위의 전달/읽음 상태"""
    notice      = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="deliveries")
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notice_deliveries")
    delivered_at= models.DateTimeField(auto_now_add=True)
    read_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("notice", "user")]

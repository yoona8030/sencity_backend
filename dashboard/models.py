from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


HEARTBEAT_TIMEOUT_SEC = 20  # 하트비트 기준(필요 시 조정)

class CCTVDevice(models.Model):
    name           = models.CharField("장치 이름", max_length=100, unique=True)
    status         = models.CharField(
        "상태", max_length=10,
        choices=[('ONLINE','ONLINE'), ('OFFLINE','OFFLINE')], default='OFFLINE'
    )
    last_heartbeat = models.DateTimeField("마지막 신호 수신 시간", auto_now=True)

    # ★추가: 자동신고를 위한 메타(선택)
    stream_url     = models.URLField("스트림 URL", blank=True, null=True)
    lat            = models.FloatField("위도", blank=True, null=True)
    lng            = models.FloatField("경도", blank=True, null=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["-last_heartbeat"]),
        ]

    def __str__(self):
        return f"{self.id} - {self.name}"

    # 하트비트 기반 온라인 판정(표시 용)
    @property
    def is_online(self) -> bool:
        return self.last_heartbeat and (
            timezone.now() - self.last_heartbeat <= timedelta(seconds=HEARTBEAT_TIMEOUT_SEC)
        )

    def mark_heartbeat(self, *, force_online: bool = True):
        """YOLO/게이트웨이가 하트비트 칠 때 호출"""
        self.last_heartbeat = timezone.now()
        if force_online:
            self.status = "ONLINE"
        self.save(update_fields=["last_heartbeat", "status"])


class MotionSensor(models.Model):
    device      = models.ForeignKey(CCTVDevice, on_delete=models.CASCADE, related_name='sensors')
    status      = models.CharField(
        "감지 상태", max_length=10,
        choices=[('감지됨','감지됨'), ('오프라인','오프라인')]
    )
    detected_at = models.DateTimeField("감지 시각", auto_now=True)

    class Meta:
        ordering = ["-detected_at"]
        indexes = [  # ★보완
            models.Index(fields=["status"]),
            models.Index(fields=["-detected_at"]),
            models.Index(fields=["device", "-detected_at"]),
        ]

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
    animal       = models.ForeignKey(
        Animal, on_delete=models.SET_NULL, null=True, blank=True, related_name="reports"
    )

    # 기존 필드 (호환용) - 나중에 제거 예정
    animal_name  = models.CharField("동물 이름", max_length=50, blank=True)

    report_date   = models.DateTimeField("신고 일시")
    status        = models.CharField("처리 상태", max_length=20)
    report_region = models.CharField("신고 지역", max_length=255)
    user          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports')
    latitude      = models.FloatField("위도")
    longitude     = models.FloatField("경도")

    # === YOLO 자동신고 지원을 위한 '추가' 필드들 (기존 화면과 충돌 없음) ===
    prob          = models.FloatField("신뢰도(0~1)", null=True, blank=True)  # NEW
    source        = models.CharField("출처", max_length=20, default="app")   # NEW: app|cctv
    device        = models.ForeignKey(                                     # NEW
        CCTVDevice, on_delete=models.SET_NULL, null=True, blank=True, related_name="reports"
    )

    class Meta:
        ordering = ["-report_date", "-id"]
        indexes = [
            models.Index(fields=["-report_date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["user", "-report_date"]),
            models.Index(fields=["report_region"]),
        ]

    def __str__(self):
        # animal(객체) 우선 → 이름 없으면 animal_name
        label = self.animal.name if self.animal else (self.animal_name or "미상")
        return f"[{label}] {self.title or ''}".strip()

    # 💡 대시보드 표시에 편한 통합 라벨
    @property
    def animal_label(self) -> str:
        return self.animal.name if self.animal else (self.animal_name or "미상")


class Prediction(models.Model):
    device     = models.ForeignKey(
        'CCTVDevice', on_delete=models.SET_NULL, null=True, blank=True, related_name='predictions'
    )  # 어느 카메라에서 나온 결과인지(없으면 비워도 됨)
    image      = models.ImageField(upload_to="predictions/", blank=True, null=True)  # 썸네일 저장 안 쓰면 null/blank OK
    filename   = models.CharField(max_length=255, blank=True)  # 업로드 파일명 또는 "cctv:0" 같은 식별자
    label      = models.CharField(max_length=200)
    score      = models.FloatField()
    source     = models.CharField(max_length=50, default="cctv")  # "api" / "cctv" 등 구분용
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['label']),
            models.Index(fields=['source', '-created_at']),  # ★보완: 출처별 최근 정렬
        ]

    def __str__(self):
        return f"{self.label} ({self.score:.2f})"


class DashboardSetting(models.Model):
    """
    대시보드 전역 설정 (singleton 성격).
    아래 to_dict/update_from_dict에서 참조하는 필드들을 실제로 정의합니다.  # ★핵심 수정
    """
    PERIOD = [("all","전체"),("7d","최근7일"),("30d","최근30일")]
    SORT   = [("newest","최신순"),("oldest","오래된순")]
    MAP    = [("kakao","Kakao"),("naver","Naver"),("google","Google")]

    # 기본 보기
    default_period = models.CharField(max_length=10, choices=PERIOD, default="all")
    default_sort   = models.CharField(max_length=10, choices=SORT,   default="newest")

    # ★추가: 리스트 페이지 사이즈/표시 관련
    page_size      = models.PositiveSmallIntegerField(default=10)  # to_dict에서 사용

    # 미해결/지연
    unresolved_statuses  = models.JSONField(default=list)      # ["접수","처리중",...]
    aging_threshold_days = models.PositiveSmallIntegerField(default=3)

    # 알림(대시보드용)
    notify_status_change = models.BooleanField(default=True)
    quiet_hours_start    = models.TimeField(null=True, blank=True)
    quiet_hours_end      = models.TimeField(null=True, blank=True)

    # ★추가: 사용자 알림 선호 (to_dict에서 사용)
    notify_sound   = models.BooleanField(default=True)
    notify_desktop = models.BooleanField(default=True)

    # 유지보수 배너(대시보드용)
    maintenance_mode     = models.BooleanField(default=False)
    maintenance_message  = models.CharField(max_length=200, blank=True, default="")

    # 지도(대시보드에서 미리보기 필요 시)
    map_provider         = models.CharField(max_length=10, choices=MAP, default="kakao")
    map_api_key          = models.CharField(max_length=255, blank=True, default="")

    # ★추가: 날짜 포맷, 개인정보 마스킹 (to_dict에서 사용)
    date_format    = models.CharField(max_length=32, default="%Y-%m-%d %H:%M")
    mask_reporter  = models.BooleanField(default=False)

    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "대시보드 설정"
        verbose_name_plural = "대시보드 설정"

    def __str__(self):
        return "DashboardSetting"

    def to_dict(self):
        # ★수정: 실제 존재하는 필드만 직렬화
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
        # ★수정: 동일 키만 반영
        for k in ["page_size","default_period","default_sort","notify_sound",
                  "notify_desktop","date_format","mask_reporter"]:
            if k in data:
                setattr(self, k, data[k])

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
        indexes = [  # ★보완
            models.Index(fields=["type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["-created_at"]),
            models.Index(fields=["start_at", "end_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"


class NoticeDelivery(models.Model):
    """개별 사용자 단위의 전달/읽음 상태"""
    notice       = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="deliveries")
    user         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notice_deliveries")
    delivered_at = models.DateTimeField(auto_now_add=True)
    read_at      = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("notice", "user")]
        indexes = [  # ★보완
            models.Index(fields=["user", "notice"]),
            models.Index(fields=["-delivered_at"]),
            models.Index(fields=["read_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} ← {self.notice_id}"

class Content(models.Model):
    """
    대시보드에서 생성/관리할 공통 콘텐츠(앱 배너 공지 포함).
    - recent_list_partial()에서 최근 생성 목록으로 사용
    """
    # 기본 정보
    title         = models.CharField(max_length=200, default="제목 없음")
    kind          = models.CharField(max_length=50, blank=True, default="")   # 예: "앱 배너 공지", "신규 기능 카드"
    status_label  = models.CharField(max_length=20, blank=True, default="임시저장")  # "공개"/"임시저장" 등
    is_live       = models.BooleanField(default=False)                         # 실제 공개 여부

    # 작성자(있으면 표시)
    owner         = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="contents"
    )

    # 타임스탬프
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes  = [
            models.Index(fields=["-updated_at"]),
            models.Index(fields=["kind"]),
            models.Index(fields=["is_live"]),
        ]

    def __str__(self):
        return f"[{self.kind or '콘텐츠'}] {self.title}"

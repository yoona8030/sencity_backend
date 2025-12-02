from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from .models import CCTVDevice, MotionSensor, Report, Prediction, Animal, DashboardSetting, Notification, NoticeDelivery, Content

admin.site.site_header = "SENCITY 관리자"
admin.site.site_title  = "SENCITY 관리자"
admin.site.index_title = "사이트 관리"


@admin.register(CCTVDevice)
class CCTVDeviceAdmin(admin.ModelAdmin):
    list_display  = ('id', 'name', 'status', 'last_heartbeat')
    list_filter   = ('status',)
    search_fields = ('name',)


@admin.register(MotionSensor)
class MotionSensorAdmin(admin.ModelAdmin):
    list_display  = ('id', 'device', 'status', 'detected_at')
    list_filter   = ('status',)
    search_fields = ('device__name',)


@admin.register(Animal)
class AnimalAdmin(admin.ModelAdmin):
    list_display = ("id","name")
    search_fields = ("name",)

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_animal_label",   # ← 변경: animal_label → get_animal_label
        "title",
        "status",
        "report_region",
        "user",
        "report_date",
    )
    list_filter = ("status", "report_region")
    search_fields = ("title", "animal_name", "report_region", "user__username", "user__email")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # 성능 개선: animal/user 조인
        return qs.select_related("animal", "user")

    @admin.display(description="동물", ordering="animal__name")
    def get_animal_label(self, obj):
        """
        Admin에서 안전하게 동물 라벨 보여주기:
        - obj.animal.name_kor > name > label > title
        - 없으면 obj.animal_name
        - 그래도 없으면 '미상'
        """
        a = getattr(obj, "animal", None)
        if a:
            for cand in ("name_kor", "name", "label", "title"):
                v = getattr(a, cand, None)
                if v:
                    return v
        return getattr(obj, "animal_name", None) or "미상"

    def mark_handled(self, request, queryset):
        updated = queryset.update(status='처리완료')  # ← 공백 없이(아래 2번 참고)
        self.message_user(request, f"{updated}건의 신고를 처리완료로 변경했습니다.")
    mark_handled.short_description = "선택한 신고를 처리완료로 변경"


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display  = ("id", "device", "filename", "label", "score", "source", "created_at")
    list_filter   = ("source", "device", "created_at")
    search_fields = ("filename", "label")


@admin.register(DashboardSetting)
class DashboardSettingAdmin(admin.ModelAdmin):
    # 목록 컬럼(실제로는 목록 페이지로 잘 가지 않게 리다이렉트 처리함)
    list_display = (
        "id",
        "default_period",
        "default_sort",
        "page_size",           # 추가 필드
        "notify_sound",        # 추가 필드
        "notify_desktop",      # 추가 필드
        "maintenance_mode",
        "map_provider",
        "updated_at",
    )

    # 좌측 필드 그룹 구성
    fieldsets = (
        ("기본 보기", {
            "fields": ("default_period", "default_sort", "page_size", "date_format")  # page_size, date_format 추가
        }),
        ("미해결/지연", {
            "fields": ("unresolved_statuses", "aging_threshold_days")
        }),
        ("알림", {
            "fields": (
                "notify_status_change",
                "notify_sound",      # 추가
                "notify_desktop",    # 추가
                "quiet_hours_start",
                "quiet_hours_end",
            )
        }),
        ("유지보수", {
            "fields": ("maintenance_mode", "maintenance_message")
        }),
        ("지도", {
            "fields": ("map_provider", "map_api_key")
        }),
        ("개인정보/표현", {
            "fields": ("mask_reporter",)  # 추가
        }),
    )

    readonly_fields = ("updated_at",)  # 필요 시 우측 사이드 패널로 옮길 수도 있음

    # ─────────────────────────────
    # 싱글톤 제약: 1개만 존재하도록
    # ─────────────────────────────
    def has_add_permission(self, request):
        """레코드가 없을 때만 추가 허용"""
        exists = DashboardSetting.objects.exists()
        return not exists

    def has_delete_permission(self, request, obj=None):
        """삭제는 금지(싱글톤 유지)"""
        return False

    # 목록 화면 접근 시, 곧바로 단일 레코드 수정 화면으로 라우팅
    def changelist_view(self, request, extra_context=None):
        obj = DashboardSetting.get_solo()
        url = reverse("admin:dashboard_dashboardsetting_change", args=[obj.pk])
        return redirect(url)

    # 추가 화면 접근 시에도 이미 있으면 변경 화면으로 이동
    def add_view(self, request, form_url="", extra_context=None):
        if DashboardSetting.objects.exists():
            obj = DashboardSetting.get_solo()
            url = reverse("admin:dashboard_dashboardsetting_change", args=[obj.pk])
            return redirect(url)
        return super().add_view(request, form_url, extra_context)

    # 저장 후에도 목록으로 돌아가면 다시 변경화면으로 라우팅되므로 UX 일관
    # (필요시 message 추가 가능)

@admin.register(Content)
class ContentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "kind", "status_label", "is_live", "owner", "updated_at", "created_at")
    list_filter  = ("kind", "status_label", "is_live")
    search_fields = ("title", "kind")
    ordering = ("-updated_at", "-id")

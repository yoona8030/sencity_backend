from django.contrib import admin
from .models import CCTVDevice, MotionSensor, Report, Prediction, Animal, DashboardSetting

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
    list_display   = ('id','report_date','title','animal','status','report_region','user')
    list_filter    = ('status','report_date','animal')
    search_fields  = ('title','animal__name','report_region','user__username')
    actions            = ['mark_handled']
    date_hierarchy     = 'report_date'     # ← 날짜 네비게이션 추가(편의)
    list_per_page      = 30
    ordering           = ('-report_date',)

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
    list_display = ("id","default_period","default_sort","maintenance_mode","updated_at")

    fieldsets = (
        ("기본 보기", {"fields": ("default_period","default_sort")}),
        ("미해결/지연", {"fields": ("unresolved_statuses","aging_threshold_days")}),
        ("알림", {"fields": ("notify_status_change","quiet_hours_start","quiet_hours_end")}),
        ("유지보수", {"fields": ("maintenance_mode","maintenance_message")}),
        ("지도", {"fields": ("map_provider","map_api_key")}),
    )

    def has_add_permission(self, request):
        # 싱글톤: 하나만 허용
        return not DashboardSetting.objects.exists()
from django.contrib import admin
from .models import CCTVDevice, MotionSensor, Report, Prediction

admin.site.site_header  = "SENCITY 관리자"
admin.site.site_title   = "SENCITY 관리자"
admin.site.index_title  = "사이트 관리"

@admin.register(CCTVDevice)
class CCTVDeviceAdmin(admin.ModelAdmin):
    list_display   = ('id', 'name', 'status', 'last_heartbeat')
    list_filter    = ('status',)
    search_fields  = ('name',)

@admin.register(MotionSensor)
class MotionSensorAdmin(admin.ModelAdmin):
    list_display   = ('id', 'device', 'status', 'detected_at')
    list_filter    = ('status',)
    search_fields  = ('device__name',)

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display   = ('id', 'report_date', 'animal_name', 'status', 'report_region', 'user')
    list_filter    = ('status', 'report_date')
    search_fields  = ('animal_name', 'report_region', 'user__username')
    actions        = ['mark_handled']

    def mark_handled(self, request, queryset):
        updated = queryset.update(status='처리 완료')
        self.message_user(request, f"{updated}건의 신고를 처리 완료 상태로 변경했습니다")
    mark_handled.short_description = "선택한 신고를 처리 완료로 변경"

@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display  = ("id", "device", "filename", "label", "score", "source", "created_at")
    list_filter   = ("source", "device", "created_at")
    search_fields = ("filename", "label")

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from .models import (
    User,
    Animal,
    SearchHistory,
    Location,
    AppBanner,
    Report,
    Notification,
    Feedback,
    Statistic,
    SavedPlace,
    DeviceToken,
    Notice,
    NoticeDelivery,
)

# --------------------------
# DeviceToken
# --------------------------
@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'platform', 'is_active', 'last_seen', 'created_at')
    list_filter  = ('platform', 'is_active')
    search_fields = ('user__username', 'token')
    ordering = ('-last_seen',)

# --------------------------
# Notice / NoticeDelivery (공지)
# --------------------------
@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display  = ('id', 'title', 'target', 'created_at')
    search_fields = ('title', 'body')
    ordering      = ('-id',)

@admin.register(NoticeDelivery)
class NoticeDeliveryAdmin(admin.ModelAdmin):
    list_display  = ('id', 'notice', 'device_token', 'status', 'fcm_msg_id', 'error_code', 'created_at')
    list_filter   = ('status', 'device_token__platform')
    search_fields = ('notice__title', 'device_token__token', 'error_code')
    ordering      = ('-id',)

# --------------------------
# User / Animal / SearchHistory / Location / AppBanner / Report
# --------------------------
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display   = ('username', 'email', 'telphone', 'user_address', 'agree')
    search_fields  = ('username', 'email', 'telphone')

@admin.register(Animal)
class AnimalAdmin(admin.ModelAdmin):
    list_display   = ('name_kor', 'name_eng')
    search_fields  = ('name_kor', 'name_eng')

@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display   = ('user', 'keyword', 'searched_at')
    search_fields  = ('keyword',)
    list_filter    = ('user',)

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display  = ("id", "city", "district", "region", "latitude", "longitude", "reports_count")
    list_filter   = ("city", "district")
    search_fields = ('region', "address", "reports__id")
    ordering      = ('-id',)

    def reports_count(self, obj):
        return obj.reports.count()
    reports_count.short_description = 'Reports Count'

@admin.register(AppBanner)
class AppBannerAdmin(admin.ModelAdmin):
    list_display = ("id", "text", "is_active", "priority", "starts_at", "ends_at")
    list_filter  = ("is_active",)
    search_fields = ("text", "cta_url")

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'report_date', 'animal', 'status', 'user', 'location_display')
    list_filter  = ('status', 'report_date', 'animal')
    search_fields = ('user__username', 'animal__name_kor', 'location__region', 'location__address')
    date_hierarchy = 'report_date'

    def location_display(self, obj):
        if obj.location:
            return f"{obj.location.region} ({obj.location.city} {obj.location.district})"
        return "-"
    location_display.short_description = 'Location'

# --------------------------
# Notification (폼 정규화)
# --------------------------
class NotificationAdminForm(forms.ModelForm):
    class Meta:
        model = Notification
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = getattr(self, "instance", None)
        for fname in ("type", "status_change"):
            if fname not in self.fields:
                continue
            field = self.fields[fname]
            field.choices = [(v, l) for (v, l) in field.choices if str(v) != ""]
            field.required = True
            if inst and getattr(inst, "pk", None):
                cur = getattr(inst, fname, None)
                if cur is None:
                    continue
                cur_norm = str(cur).strip().lower()
                value_map = {str(v).strip().lower(): v for (v, _) in field.choices}
                if cur_norm in value_map:
                    field.initial = value_map[cur_norm]

    def _normalize_choice(self, name):
        v = str(self.cleaned_data.get(name, "")).strip().lower()
        field = self.fields[name]
        value_map = {str(val).strip().lower(): val for val, _ in field.choices}
        if v in value_map:
            return value_map[v]
        raise ValidationError("허용되지 않은 값입니다.")

    def clean_type(self):
        return self._normalize_choice("type")

    def clean_status_change(self):
        return self._normalize_choice("status_change")

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    form = NotificationAdminForm
    list_display  = ('id', 'user', 'type_display', 'status_change_display', 'reply_short', 'created_at')
    list_filter   = ('type', 'status_change', 'created_at')
    search_fields = ('user__username', 'status_change', 'reply')
    ordering      = ('-created_at',)

    def type_display(self, obj):
        return obj.get_type_display() or '-'
    type_display.short_description = 'type'
    type_display.admin_order_field = 'type'

    def status_change_display(self, obj):
        return obj.get_status_change_display() or '-'
    status_change_display.short_description = 'status_change'
    status_change_display.admin_order_field = 'status_change'

    def reply_short(self, obj):
        return (obj.reply or '')[:30]
    reply_short.short_description = 'reply'

# --------------------------
# Feedback / Statistic / SavedPlace
# --------------------------
@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("feedback_id","report_id","report","user","admin","feedback_datetime")
    ordering = ("-feedback_datetime","-feedback_id")
    list_select_related = ("report","user","admin")
    def get_queryset(self, request):
        return (super().get_queryset(request)
                .select_related("report","user","admin")
                .distinct())

@admin.register(Statistic)
class StatisticAdmin(admin.ModelAdmin):
    list_display   = ('state_unit', 'state_year', 'state_month', 'all_reports', 'completed', 'incomplete')
    list_filter    = ('state_unit', 'state_year')

@admin.register(SavedPlace)
class SavedPlaceAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'name', 'location', 'latitude', 'longitude', 'client_id', 'created_at')
    list_filter   = ('user', 'location')
    search_fields = ('name', 'client_id', 'location__address')

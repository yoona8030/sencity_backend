from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from .models import (
    User,
    Animal,
    SearchHistory,
    Location,
    Report,
    Notification,
    Feedback,
    Statistic, 
    SavedPlace
)

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

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'report_date', 'animal', 'status', 'user', 'location_display')
    list_filter = ('status', 'report_date', 'animal')
    search_fields = ('user__username', 'animal__name_kor', 'location__region', 'location__address')
    date_hierarchy = 'report_date'

    def location_display(self, obj):
        if obj.location:
            return f"{obj.location.region} ({obj.location.city} {obj.location.district})"
        return "-"
    location_display.short_description = 'Location'

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

            # 1) 빈 옵션 제거 + 필수화
            field.choices = [(v, l) for (v, l) in field.choices if str(v) != ""]
            field.required = True

            # 2) 현재 값으로만 '선택' 설정 (choices 추가 금지)
            if inst and getattr(inst, "pk", None):
                cur = getattr(inst, fname, None)
                if cur is None:
                    continue
                cur_norm = str(cur).strip().lower()
                value_map = {str(v).strip().lower(): v for (v, _) in field.choices}
                if cur_norm in value_map:
                    field.initial = value_map[cur_norm]   # 존재하는 값으로만 초기화

    # 저장 시 정규화 + 유효성 점검
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
        # choices 라벨을 보여줍니다. 값이 없으면 '-'
        return obj.get_type_display() or '-'
    type_display.short_description = 'type'
    type_display.admin_order_field = 'type'  # 정렬 유지

    def status_change_display(self, obj):
        return obj.get_status_change_display() or '-'
    status_change_display.short_description = 'status_change'
    status_change_display.admin_order_field = 'status_change'

    def reply_short(self, obj):
        return (obj.reply or '')[:30]
    reply_short.short_description = 'reply'

@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display  = ('feedback_id', 'report', 'user', 'admin', 'feedback_datetime')
    list_filter   = ('feedback_datetime',)
    search_fields = ('content', 'user__username', 'admin__username')
    ordering      = ('-feedback_datetime',)

@admin.register(Statistic)
class StatisticAdmin(admin.ModelAdmin):
    list_display   = ('state_unit', 'state_year', 'state_month', 'all_reports', 'completed', 'incomplete')
    list_filter    = ('state_unit', 'state_year')

@admin.register(SavedPlace)
class SavedPlaceAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'name', 'location', 'latitude', 'longitude', 'client_id', 'created_at')
    list_filter   = ('user', 'location')
    search_fields = ('name', 'client_id', 'location__address')
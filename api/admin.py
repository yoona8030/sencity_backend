from django.contrib import admin
from .models import (
    User,
    Animal,
    SearchHistory,
    Location,
    Report,
    Notification,
    Feedback,
    Statistic
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

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'type', 'status_change_short', 'reply_short', 'created_at')
    list_filter   = ('type', 'created_at')
    search_fields = ('user__username', 'status_change', 'reply')
    ordering      = ('-created_at',)

    def status_change_short(self, obj):
        return (obj.status_change or '')[:30]
    status_change_short.short_description = 'status_change'

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

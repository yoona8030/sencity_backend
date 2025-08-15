# reports filter
import django_filters
from .models import Report, Notification

class ReportFilter(django_filters.FilterSet):
    start_date = django_filters.IsoDateTimeFilter(field_name='report_date', lookup_expr='gte')
    end_date   = django_filters.IsoDateTimeFilter(field_name='report_date', lookup_expr='lte')
    status     = django_filters.CharFilter(field_name='status', lookup_expr='iexact')
    animal_id  = django_filters.NumberFilter(field_name='animal_id')
    # ✅ region → address (부분 검색도 필요하면 icontains로 교체)
    user_address    = django_filters.CharFilter(field_name='user_address', lookup_expr='iexact')
    user_id    = django_filters.NumberFilter(field_name='user_id')

    class Meta:
        model = Report
        fields = ['status', 'animal_id', 'user_address', 'user_id', 'start_date', 'end_date']

class NotificationFilter(django_filters.FilterSet):
    user_id    = django_filters.NumberFilter(field_name='user_id')
    type       = django_filters.CharFilter(field_name='type', lookup_expr='iexact')
    created_after  = django_filters.IsoDateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.IsoDateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = Notification
        fields = ['user_id', 'type', 'created_after', 'created_before']
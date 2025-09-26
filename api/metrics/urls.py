# api/metrics/urls.py
from django.urls import path
from .views import EventIngestView, StatsView, PingView, KPIView

urlpatterns = [
    path("events/", EventIngestView.as_view(), name="metrics-event-ingest"),
    path("stats/", StatsView.as_view(), name="metrics-stats"),
    path("kpi/",    KPIView.as_view(), name="metrics-kpi"),
    path("ping/", PingView.as_view(), name="metrics-ping"),
]

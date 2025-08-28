from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_home, name='home'),
    path('cctv/stream/', views.cctv_stream, name='cctv-stream'),
    path('api/classify-image/', views.classify_image, name='classify-image'),
]

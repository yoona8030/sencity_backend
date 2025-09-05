# inquiries/urls.py
from django.urls import path
from rest_framework_nested import routers
from .views import InquiryViewSet, InquiryMessageViewSet, whoami

router = routers.SimpleRouter()
router.register(r'inquiries', InquiryViewSet, basename='inquiry')

nested = routers.NestedSimpleRouter(router, r'inquiries', lookup='inquiry')
nested.register(r'messages', InquiryMessageViewSet, basename='inquiry-messages')

urlpatterns = [
    path('whoami/', whoami),
]
urlpatterns += router.urls + nested.urls

# inquiries/views.py
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone  # mark_read에서 사용
from rest_framework.parsers import MultiPartParser, FormParser  # ✅ 파일 업로드 파서

from .models import Inquiry, InquiryMessage, InquiryAttachment
from .serializers import (
    InquiryListSerializer, InquiryDetailSerializer, InquiryCreateSerializer,
    InquiryMessageSerializer
)
from .permissions import IsOwnerOrStaff

class InquiryViewSet(viewsets.ModelViewSet):
    """
    /api/inquiries/  (GET list, POST create)
    /api/inquiries/{id}/  (GET retrieve, PATCH update, DELETE destroy)
    /api/inquiries/{id}/assign/  (PATCH, 관리자만: 담당자 배정)
    """
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]
    queryset = Inquiry.objects.all().select_related('user', 'admin')

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # 일반 유저는 본인 문의만, 스태프는 전체
        if not user.is_staff:
            qs = qs.filter(user=user)
        else:
            if self.request.query_params.get('all') == '1':
                pass  # 그대로 전체
        # 필터(옵션)
        status_q = self.request.query_params.get('status')
        if status_q:
            qs = qs.filter(status=status_q)
        category_q = self.request.query_params.get('category')
        if category_q:
            qs = qs.filter(category=category_q)
        return qs.order_by('-updated_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return InquiryListSerializer
        if self.action == 'create':
            return InquiryCreateSerializer
        return InquiryDetailSerializer

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['patch'], url_path='assign')
    def assign_admin(self, request, pk=None):
        """관리자만 담당자 배정 가능"""
        if not request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        inquiry = self.get_object()
        admin_id = request.data.get('admin_id')
        if not admin_id:
            return Response({"detail": "admin_id required"}, status=400)
        from django.contrib.auth import get_user_model
        Admin = get_user_model()
        admin = get_object_or_404(Admin, pk=admin_id)
        inquiry.admin = admin
        # open이면 pending으로
        if inquiry.status == Inquiry.Status.OPEN:
            inquiry.status = Inquiry.Status.PENDING
        inquiry.save(update_fields=['admin', 'status', 'updated_at'])
        return Response(InquiryDetailSerializer(inquiry).data, status=200)
    
    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        inquiry = self.get_object()
        now = timezone.now()
        if request.user.is_staff:
            inquiry.admin_last_read_at = now
            inquiry.save(update_fields=['admin_last_read_at','updated_at'])
        else:
            inquiry.user_last_read_at = now
            inquiry.save(update_fields=['user_last_read_at','updated_at'])
        return Response({"ok": True, "read_at": now.isoformat()})


class InquiryMessageViewSet(mixins.ListModelMixin,
                            mixins.CreateModelMixin,
                            viewsets.GenericViewSet):
    """
    /api/inquiries/{inquiry_pk}/messages/  (GET list, POST create)
    """
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]
    serializer_class = InquiryMessageSerializer
    parser_classes = [MultiPartParser, FormParser] 

    def get_queryset(self):
        inquiry_id = self.kwargs['inquiry_pk']
        qs = InquiryMessage.objects.filter(inquiry_id=inquiry_id).select_related('inquiry')
        user = self.request.user
        # 권한: 일반 유저는 자신의 문의만
        if not user.is_staff:
            qs = qs.filter(inquiry__user=user)
        return qs.order_by('created_at')

    def perform_create(self, serializer):
        inquiry = get_object_or_404(Inquiry, pk=self.kwargs['inquiry_pk'])
        user = self.request.user

        # 1) 메시지 먼저 저장 (보낸이 자동 셋업)
        if not user.is_staff:
            msg = serializer.save(inquiry=inquiry, sender_type=InquiryMessage.SenderType.USER, sender_user=user)
        else:
            msg = serializer.save(inquiry=inquiry, sender_type=InquiryMessage.SenderType.ADMIN, sender_admin=user)

        # 2) 업로드 파일 배열 꺼내기 (키 이름은 'files' 또는 'attachments' 중 택1)
        files = self.request.FILES.getlist('files')
        if not files:
            files = self.request.FILES.getlist('attachments')

        # 3) 첨부 레코드 생성
        for f in files:
            InquiryAttachment.objects.create(
                message=msg,
                file=f,
                mime=getattr(f, 'content_type', '') or '',
                size=getattr(f, 'size', None),
            )
            
@api_view(['GET'])
def whoami(request):
    u = request.user
    return Response({
        "is_authenticated": u.is_authenticated,
        "id": u.id if u.is_authenticated else None,
        "username": u.username if u.is_authenticated else None,
        "is_staff": bool(getattr(u, "is_staff", False)) if u.is_authenticated else False,
    })
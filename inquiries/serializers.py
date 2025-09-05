# inquiries/serializers.py
from rest_framework import serializers
from .models import Inquiry, InquiryMessage, InquiryAttachment

class InquiryMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = InquiryMessage
        fields = [
            'id', 'inquiry', 'sender_type',
            'sender_user', 'sender_admin',
            'body', 'attachment_url', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'inquiry', 'sender_type', 'sender_user', 'sender_admin']

class InquiryListSerializer(serializers.ModelSerializer):
    last_message_preview = serializers.SerializerMethodField()

    class Meta:
        model = Inquiry
        fields = [
            'id', 'user', 'admin', 'title', 'category',
            'status', 'priority', 'created_at', 'updated_at',
            'last_user_msg_at', 'last_admin_msg_at',
            'last_message_preview'
        ]

    def get_last_message_preview(self, obj):
        msg = obj.messages.order_by('-created_at').first()
        if not msg:
            return None
        t = (msg.body or '').strip().replace('\n', ' ')
        return t[:80] + ('…' if len(t) > 80 else '')

class InquiryDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = [
            'id', 'user', 'admin', 'title', 'category',
            'status', 'priority', 'created_at', 'updated_at',
            'last_user_msg_at', 'last_admin_msg_at'
        ]
        read_only_fields = ['user', 'created_at', 'updated_at', 'last_user_msg_at', 'last_admin_msg_at']

class InquiryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquiry
        fields = ['title', 'category', 'priority']

    def create(self, validated_data):
        user = self.context['request'].user
        return Inquiry.objects.create(user=user, **validated_data)

class InquiryAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InquiryAttachment
        fields = ['id', 'file', 'mime', 'size', 'created_at']
        read_only_fields = ['id','mime','size','created_at']

class InquiryMessageSerializer(serializers.ModelSerializer):
    attachments = InquiryAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = InquiryMessage
        fields = [
            'id','inquiry','sender_type','sender_user','sender_admin',
            'body','created_at',
            'attachments',  # ✅ 포함
        ]
        read_only_fields = ['id','inquiry','sender_type','sender_user','sender_admin','created_at']
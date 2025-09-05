# Register your models here.
from django.contrib import admin
from .models import Inquiry, InquiryMessage

@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ('id','title','user','admin','status','priority','updated_at')
    list_filter = ('status','priority','category')
    search_fields = ('title','user__username','admin__username')

@admin.register(InquiryMessage)
class InquiryMessageAdmin(admin.ModelAdmin):
    list_display = ('id','inquiry','sender_type','created_at')
    list_filter = ('sender_type',)
    search_fields = ('body',)

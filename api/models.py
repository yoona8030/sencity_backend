from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    email = models.EmailField(unique=True)
    telphone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    agree = models.BooleanField(default=False)

    class Meta: 
        verbose_name = 'Users'
        verbose_name_plural = 'Users'


    def __str__(self):
        return self.username

class Animal(models.Model):
    name_kor = models.CharField(max_length=50)       # 한글 이름 
    name_eng = models.CharField(max_length=50)       # 영어 이름 
    image_url = models.URLField(blank=True)          # 이미지 링크
    description = models.TextField(blank=True)       # 설명
    features = models.JSONField(default=list, blank=True) # 주의사항
    precautions = models.JSONField(default=list, blank=True) # 조치

    def __str__(self):
        return self.name_kor

# 기존 SearchHistory 모델은 아래에 그대로 두세요!
class SearchHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='search_histories')
    keyword = models.CharField(max_length=100)
    searched_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.keyword}"

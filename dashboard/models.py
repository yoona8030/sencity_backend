from django.db import models
from django.conf import settings

class CCTVDevice(models.Model):
    name           = models.CharField("장치 이름", max_length=100)
    status         = models.CharField("상태", max_length=10,
                        choices=[('ONLINE','ONLINE'), ('OFFLINE','OFFLINE')])
    last_heartbeat = models.DateTimeField("마지막 신호 수신 시간", auto_now=True)

    def __str__(self):
        return self.name

class MotionSensor(models.Model):
    device      = models.ForeignKey(CCTVDevice, on_delete=models.CASCADE, related_name='sensors')
    status      = models.CharField("감지 상태", max_length=10,
                        choices=[('감지됨','감지됨'), ('오프라인','오프라인')])
    detected_at = models.DateTimeField("감지 시각", auto_now=True)

    def __str__(self):
        return f"{self.device.name} 센서"

class Report(models.Model):
    # ERD에 정의된 필드 순서: report_id, report_date, animal_name, status, report_region, user_id, latitude, longitude :contentReference[oaicite:2]{index=2}
    report_date   = models.DateTimeField("신고 일시")
    animal_name   = models.CharField("동물 이름", max_length=50)
    status        = models.CharField("처리 상태", max_length=20)
    report_region = models.CharField("신고 지역", max_length=255)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                         on_delete=models.CASCADE,
                         related_name='reports')
    latitude      = models.FloatField("위도")
    longitude     = models.FloatField("경도")

    def __str__(self):
        return f"{self.report_date:%Y-%m-%d %H:%M} - {self.animal_name}"


class Prediction(models.Model):
    device    = models.ForeignKey(
        'CCTVDevice', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='predictions'
    )  # 어느 카메라에서 나온 결과인지(없으면 비워도 됨)
    image     = models.ImageField(upload_to="predictions/", blank=True, null=True)  # 썸네일 저장 안 쓰면 null/blank OK
    filename  = models.CharField(max_length=255, blank=True)  # 업로드 파일명 또는 "cctv:0" 같은 식별자
    label     = models.CharField(max_length=200)
    score     = models.FloatField()
    source    = models.CharField(max_length=50, default="cctv")  # "api" / "cctv" 등 구분용
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['created_at']), models.Index(fields=['label'])]

    def __str__(self):
        return f"{self.label} ({self.score:.2f})"
# dashboard/serializers.py
from rest_framework import serializers
from api.models import Report

class DashboardReportListSerializer(serializers.ModelSerializer):
    animal_name = serializers.SerializerMethodField()
    reporter = serializers.SerializerMethodField()
    region = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            "id",
            "animal_name",
            "reporter",
            "region",
            "status",
            "created_at",
            "image_url",
        ]

    def get_animal_name(self, obj):
        """
        animal 관계 또는 문자열 필드에서 안전하게 이름 반환
        """
        # 1) FK 관계가 있을 때
        a = getattr(obj, "animal", None)
        if a:
            for field in ("name_kor", "name", "label", "species"):
                if hasattr(a, field):
                    v = getattr(a, field)
                    if v:
                        return v

        # 2) 직접 필드로 존재할 경우
        for name in ("animal_name", "animal_label", "animal"):
            v = getattr(obj, name, None)
            if isinstance(v, str) and v.strip():
                return v

        return "(알수없음)"

    def get_reporter(self, obj):
        u = getattr(obj, "user", None)
        if not u:
            return "익명"
        for field in ("nickname", "username", "email"):
            v = getattr(u, field, None)
            if v:
                return v
        return f"사용자#{u.id}"

    def get_region(self, obj):
        for name in ("report_region", "region", "address", "location_name"):
            v = getattr(obj, name, None)
            if v:
                return v
        return ""

    def get_image_url(self, obj):
        """
        첫 번째 이미지 URL 반환 (photo, image, img, photo1 순서)
        """
        request = self.context.get("request")
        for name in ("photo", "image", "img", "photo1", "photo_url"):
            if not hasattr(obj, name):
                continue
            f = getattr(obj, name)
            if not f:
                continue
            # FileField
            if hasattr(f, "url"):
                try:
                    url = f.url
                    return request.build_absolute_uri(url) if request else url
                except Exception:
                    continue
            # 문자열 URL
            if isinstance(f, str) and f.strip():
                url = f.strip()
                return request.build_absolute_uri(url) if request and url.startswith("/") else url
        return ""

    def get_created_at(self, obj):
        for name in ("created_at", "report_date", "submitted_at"):
            v = getattr(obj, name, None)
            if v:
                return v.strftime("%Y-%m-%d %H:%M")
        return ""

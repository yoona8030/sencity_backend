# api/serializers.py
from decimal import Decimal
from rest_framework import serializers
from django.apps import apps
from urllib.parse import urlencode
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from .models import (
    Animal, SearchHistory, Location, Report,
    Notification, Feedback, Admin, Statistic, SavedPlace,
    Profile
)

User = get_user_model()
SearchHistory = apps.get_model('api', 'SearchHistory')
Animal = apps.get_model('api', 'Animal')


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'telphone', 'user_address', 'agree')


class UserSignUpSerializer(serializers.ModelSerializer):
    password  = serializers.CharField(write_only=True, min_length=6)
    email     = serializers.EmailField()
    telphone  = serializers.CharField()
    user_address   = serializers.CharField(required=False, allow_blank=True)
    agree     = serializers.BooleanField()

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'telphone', 'user_address', 'agree')

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("이미 등록된 이메일입니다.")
        return value

    def create(self, validated_data):
        user = User(
            username=validated_data['username'],
            email=validated_data['email'],
            telphone=validated_data['telphone'],
            user_address=validated_data.get('user_address', ''),
            agree=validated_data['agree'],
        )
        user.set_password(validated_data['password'])
        user.save()
        return user

class AnimalSerializer(serializers.ModelSerializer):
    # 프론트가 image_url 대신 image/imageUrl를 기대해도 깨지지 않도록 alias 제공
    image = serializers.CharField(source='image_url', read_only=True)
    imageUrl = serializers.CharField(source='image_url', read_only=True)
    proxied_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Animal
        fields = [
            'id',
            'name_kor', 'name_eng',
            'image_url', 'image', 'imageUrl',  # ← 세 키 전부 노출
            'features',
            'precautions',  # ← 대처법
            'description',
            'proxied_image_url',
        ]

    def get_proxied_image_url(self, obj):
        url = getattr(obj, 'image_url', None)
        if not url:
            return None
        q = urlencode({'url': url})
        req = self.context.get('request')
        path = f'/api/image-proxy/?{q}'
        return req.build_absolute_uri(path) if req else path

class SearchHistorySerializer(serializers.ModelSerializer):
    created_at = serializers.SerializerMethodField()
    animal_info = serializers.SerializerMethodField()

    class Meta:
        model = apps.get_model('api','SearchHistory')
        fields = ['id','keyword','created_at','animal_info']

    def get_created_at(self, obj):
        # 프로젝트마다 다를 수 있는 생성시각 필드 유연 매핑
        for name in ('created_at', 'created', 'created_on', 'created_time',
                     'timestamp', 'searched_at', 'search_datetime'):
            if hasattr(obj, name):
                return getattr(obj, name)
        return None

    def get_animal_info(self, obj):
        a = Animal.objects.filter(name_kor=obj.keyword).order_by('id').first()
        if not a:
            return None

        feats = getattr(a, 'features', None)
        if isinstance(feats, list):
            features = feats
        elif isinstance(feats, str) and feats.strip():
            # TextField로 저장된 경우 줄바꿈을 리스트로 정리
            features = [s.lstrip('- ').strip() for s in feats.splitlines() if s.strip()]
        else:
            features = []

        return {
            'name':        getattr(a, 'name_kor', None),
            'english':     getattr(a, 'name_eng', None),
            'image_url':   getattr(a, 'image_url', None),
            'features':    features,
            'precautions': getattr(a, 'precautions', None),   # ← 대처법 노출
            'description': getattr(a, 'description', None),
        }

    def get_proxied_image_url(self, obj):
        if not getattr(obj, 'image_url', None):
            return None
        q = urlencode({'url': obj.image_url})
        # DRF는 기본적으로 request를 context에 넣어줍니다.
        request = self.context.get('request')
        path = f'/api/image-proxy/?{q}'
        return request.build_absolute_uri(path) if request else path

class LocationSerializer(serializers.ModelSerializer):
    location_id = serializers.IntegerField(source='id', read_only=True)

    class Meta:
        model = Location
        fields = [
            'location_id',
            'latitude',
            'longitude',
            'city',
            'district',
            'region',
            'address',
        ]
        read_only_fields = ['location_id']
class LocationLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ('id', 'address', 'city', 'district', 'region', 'latitude', 'longitude')

# [REPLACE] 기존 ReportNoAuthCreateSerializer 전체를 아래로 교체
class ReportNoAuthCreateSerializer(serializers.Serializer):
    # [MOD] animalId 를 옵션으로 변경(없으면 "미상"으로 폴백)
    animalId   = serializers.IntegerField(required=False, allow_null=True)
    locationId = serializers.IntegerField(required=False, allow_null=True)
    status     = serializers.ChoiceField(
        choices=[c[0] for c in Report.STATUS_CHOICES],
        default='checking'
    )
    photo      = serializers.ImageField()
    lat = serializers.FloatField(required=False)
    lng = serializers.FloatField(required=False)

    def create(self, validated):
        # ── 0) 동물 폴백: animalId 없으면 "미상" 자동 사용
        animal = None
        animal_id = validated.get("animalId")
        if animal_id:
            animal = Animal.objects.get(id=animal_id)
        else:
            animal, _ = Animal.objects.get_or_create(
                name_kor="미상", defaults={"name_eng": "unknown"}
            )

        # ── 1) 위치 결정: locationId 우선, 없으면 lat/lng 로 Location 생성/재사용
        loc = None
        loc_id = validated.get("locationId")
        if loc_id:
            try:
                loc = Location.objects.get(id=loc_id)
            except Location.DoesNotExist:
                loc = None
        else:
            lat = validated.get("lat")
            lng = validated.get("lng")
            if lat is not None and lng is not None:
                loc, _ = Location.objects.get_or_create(
                    latitude=Decimal(str(lat)),
                    longitude=Decimal(str(lng)),
                    defaults=dict(city="", district="", region="", address="")
                )

        # ── 2) Report 생성
        report = Report.objects.create(
            user=None,                      # 무인증
            animal=animal,
            location=loc,
            status=validated.get("status") or "checking",
            image=validated["photo"],
            report_date=timezone.now(),     # ★★ [ADD] NULL 방지 핵심
        )
        return report


class SavedPlaceReadSerializer(serializers.ModelSerializer):
    # 출력 필드: 요청하신 그대로
    type      = serializers.CharField(source='name', read_only=True)
    address   = serializers.CharField(source='location.address',   read_only=True)
    region    = serializers.CharField(source='location.region',    read_only=True, allow_blank=True)
    city      = serializers.CharField(source='location.city',      read_only=True, allow_blank=True)
    district  = serializers.CharField(source='location.district',  read_only=True, allow_blank=True)
    latitude  = serializers.FloatField(source='location.latitude',  read_only=True)   # Location 기준
    longitude = serializers.FloatField(source='location.longitude', read_only=True)

    class Meta:
        model  = SavedPlace
        fields = [
            'id', 'type', 'client_id', 'created_at',
            'address', 'region', 'city', 'district',
            'latitude', 'longitude',
        ]
        read_only_fields = fields


class SavedPlaceCreateSerializer(serializers.ModelSerializer):
    """
    생성 입력:
      - location: "123" (PK) 또는 "서울특별시 중구 세종대로 110" (주소 문자열)
      - 좌표: latitude/longitude 또는 lat/lng 아무거나 OK
      - type: name의 별칭 (미제공 시 address로 대체)
    """
    location  = serializers.CharField(write_only=True)                 # PK 또는 주소 문자열
    address   = serializers.CharField(write_only=True, required=False, allow_blank=True)
    region    = serializers.CharField(write_only=True, required=False, allow_blank=True)
    city      = serializers.CharField(write_only=True, required=False, allow_blank=True)
    district  = serializers.CharField(write_only=True, required=False, allow_blank=True)
    latitude  = serializers.FloatField(write_only=True, required=False)
    longitude = serializers.FloatField(write_only=True, required=False)
    type      = serializers.CharField(write_only=True, required=False, allow_blank=True)  # name 별칭

    class Meta:
        model  = SavedPlace
        fields = [
            'id', 'name', 'type', 'client_id', 'created_at',
            'location', 'address', 'region', 'city', 'district',
            'latitude', 'longitude',
        ]
        read_only_fields = ['id', 'created_at']

    # ── 검증: PK 경로 or 주소+좌표 경로 중 하나 충족
    def validate(self, attrs):
        loc_raw = (attrs.get('location') or '').strip()
        addr    = (attrs.get('address')  or '').strip()

        # 프런트에서 lat/lng 키로 보낼 수도 있으니 보정
        raw = getattr(self, 'initial_data', {}) or {}
        if attrs.get('latitude') is None and raw.get('lat') is not None:
            try:
                attrs['latitude'] = float(raw.get('lat'))
            except (TypeError, ValueError):
                pass
        if attrs.get('longitude') is None and raw.get('lng') is not None:
            try:
                attrs['longitude'] = float(raw.get('lng'))
            except (TypeError, ValueError):
                pass

        # Case A) location이 숫자(PK)면 좌표 필요 없음
        if loc_raw.isdigit():
            return attrs

        # Case B) 주소 문자열 경로 → 좌표 필수
        use_addr = addr if addr else loc_raw
        attrs['__resolved_address__'] = use_addr
        if attrs.get('latitude') is None or attrs.get('longitude') is None:
            raise serializers.ValidationError({'detail': '주소 문자열로 생성 시 latitude/longitude(또는 lat/lng)가 필수입니다.'})
        return attrs

    # ── Location 선택/생성/보강
    def _resolve_location(self, attrs) -> Location:
        loc_raw = (attrs.get('location') or '').strip()

        # A) PK 경로
        if loc_raw.isdigit():
            try:
                return Location.objects.get(pk=int(loc_raw))
            except Location.DoesNotExist:
                raise serializers.ValidationError({'location': f'존재하지 않는 Location PK입니다: {loc_raw}'})

        # B) 주소 문자열 경로
        address  = attrs.get('__resolved_address__')
        region   = (attrs.get('region')   or '').strip()
        city     = (attrs.get('city')     or '').strip()
        district = (attrs.get('district') or '').strip()

        # ⬇️ 좌표를 Decimal로 정규화
        lat_f = float(attrs.get('latitude'))
        lng_f = float(attrs.get('longitude'))
        lat_d = Decimal(str(lat_f))
        lng_d = Decimal(str(lng_f))

        loc, created = Location.objects.get_or_create(
            address=address,
            defaults={
                'region': region, 'city': city, 'district': district,
                'latitude': lat_d, 'longitude': lng_d,
            }
        )

        # ⬇️ 기존 레코드 보강/업데이트 필요 여부 판단 (비교는 float로 오차 허용)
        def _to_float(v):
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        need_update = (
            (loc.latitude is None or loc.longitude is None) or
            abs((_to_float(loc.latitude)  or 0.0) - lat_f) > 1e-7 or
            abs((_to_float(loc.longitude) or 0.0) - lng_f) > 1e-7
        )

        if not created and need_update:
            loc.latitude = lat_d
            loc.longitude = lng_d
            if not (loc.region or '').strip() and region:     loc.region   = region
            if not (loc.city or '').strip() and city:         loc.city     = city
            if not (loc.district or '').strip() and district: loc.district = district
            loc.save(update_fields=['latitude', 'longitude', 'region', 'city', 'district'])
        return loc

    def create(self, validated_data):
        loc = self._resolve_location(validated_data)

        name_in = (validated_data.get('name') or '').strip()
        type_in = (validated_data.get('type') or '').strip()
        addr_in = (validated_data.get('__resolved_address__') or '').strip()
        final_name = name_in or type_in or addr_in or '장소'

        # ⚠️ 중복 방지: 먼저 빼고
        lat = validated_data.pop('latitude',  None)
        lng = validated_data.pop('longitude', None)
        _   = validated_data.pop('name', None)

        # 임시/쓰기 전용 키 정리
        for k in ('location','address','region','city','district','type','__resolved_address__'):
            validated_data.pop(k, None)

        # SavedPlace 모델이 DecimalField면 Decimal로, FloatField면 그대로 넣으세요.
        # (둘 다 Decimal이면 아래 두 줄처럼)
        lat_d = Decimal(str(lat)) if lat is not None else None
        lng_d = Decimal(str(lng)) if lng is not None else None

        instance = SavedPlace.objects.create(
            location=loc,
            name=final_name,
            latitude=lat_d,   # FloatField면 lat로 바꾸세요
            longitude=lng_d,  # FloatField면 lng로 바꾸세요
            **validated_data,
        )
        return instance

    # 생성 응답은 읽기 포맷으로 통일
    def to_representation(self, instance):
        return SavedPlaceReadSerializer(instance, context=self.context).data

class ReportSerializer(serializers.ModelSerializer):
    report_id   = serializers.IntegerField(source='id', read_only=True)
    animal_name = serializers.SerializerMethodField(read_only=True)

    # 🔹 이미지 절대 URL 제공
    photo_url = serializers.SerializerMethodField(read_only=True)

    # 쓰기용
    location_id = serializers.PrimaryKeyRelatedField(
        source='location',
        queryset=Location.objects.all(),
        write_only=True
    )
    animal_id = serializers.PrimaryKeyRelatedField(
        source='animal',
        queryset=Animal.objects.all(),
        write_only=True
    )

    # 읽기용
    location = LocationSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(source='user', read_only=True)

    class Meta:
        model = Report
        fields = [
            'report_id',
            'report_date',
            'animal_id', 'animal_name',
            'status',
            'user_id',
            'image',          # 원본 필드(업로드/다운로드 필요시 유지)
            'photo_url',      # ← 프런트에서 쓰기 편한 절대 URL
            'location_id',    # 쓰기
            'location',       # 읽기
        ]
        read_only_fields = ['report_id', 'animal_name', 'location', 'user_id', 'photo_url']

    def get_animal_name(self, obj):
        return getattr(obj.animal, 'name_kor', str(obj.animal))

    def get_photo_url(self, obj):
        """
        이미지가 있으면 절대 URL로 반환.
        (개발환경: /media/…, 운영: Nginx/S3 등에 맞게 그대로 작동)
        """
        if not getattr(obj, 'image', None):
            return ""
        url = obj.image.url  # ImageField가 제공
        req = self.context.get('request')
        return req.build_absolute_uri(url) if req else url

    def validate_status(self, value):
        allowed = {c[0] for c in Report.STATUS_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError('허용되지 않은 상태값입니다.')
        return value


class NotificationSerializer(serializers.ModelSerializer):
    notification_id = serializers.IntegerField(source='id', read_only=True)

    # read-only FK id들: source 지정하지 않습니다 (DRF가 obj.user_id 등을 자동으로 읽음)
    user_id   = serializers.IntegerField(read_only=True)
    admin_id  = serializers.IntegerField(read_only=True)
    report_id = serializers.IntegerField(read_only=True)

    # write-only 입력용(개인 알림 생성 시)
    user_id_in = serializers.PrimaryKeyRelatedField(
        source='user',
        queryset=User.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    # 화면에서 바로 쓰는 파생 필드들
    user_name    = serializers.SerializerMethodField()
    animal_name  = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    title        = serializers.SerializerMethodField()   # "사용자 - 동물"
    message      = serializers.SerializerMethodField()   # 본문 1줄(피드백 > reply)

    class Meta:
        model = Notification
        fields = [
            'notification_id',
            'type', 'created_at',
            'reply', 'status_change', 'status_label',
            'user_id', 'admin_id', 'report_id', 'user_id_in',
            'user_name', 'animal_name', 'title', 'message',
        ]
        read_only_fields = [
            'notification_id', 'created_at',
            'user_id', 'admin_id', 'report_id',
            'user_name', 'animal_name', 'title', 'message', 'status_label',
        ]

    # ---------- 표기용 helpers ----------
    def _pick_user(self, obj):
        # 알림 user가 없으면 report.user 사용
        u = getattr(obj, 'user', None)
        if u is None:
            rpt = getattr(obj, 'report', None)
            if rpt is not None:
                u = getattr(rpt, 'user', None)
        return u

    def get_user_name(self, obj):
        u = self._pick_user(obj)
        if not u:
            return '사용자'
        return (u.first_name or u.username or f'사용자 #{u.id}')

    def get_animal_name(self, obj):
        rpt = getattr(obj, 'report', None)
        if rpt and getattr(rpt, 'animal', None):
            return getattr(rpt.animal, 'name_kor', None) or '미상'
        return '미상'

    def get_status_label(self, obj):
        try:
            sc = getattr(obj, "status_change", None)
            if sc:
                sc_map = dict(Notification.STATUS_CHANGE_CHOICES)
                if sc in sc_map:
                    return sc_map[sc]
        except Exception:
            pass

        try:
            rep = getattr(obj, "report", None)
            if rep and getattr(rep, "status", None):
                rep_map = dict(Report.STATUS_CHOICES)
                if rep.status in rep_map:
                    return rep_map[rep.status]
        except Exception:
            pass
        return None

    def get_title(self, obj):
        t = getattr(obj, 'type', None)

        # ✅ 그룹 공지(전체 공지) 전용 타이틀
        if t == 'group':
            label = self.get_status_label(obj)
            if label:
                return f"전체 공지 · {label}"

            rep = (obj.reply or '').strip()
            if rep:
                first_line = rep.splitlines()[0].strip()
                # 30자 내 요약
                if len(first_line) > 30:
                    first_line = first_line[:29] + '…'
                return f"전체 공지 · {first_line}"

            return "전체 공지"

        # ✅ 개인 알림은 기존 포맷 유지
        return f"{self.get_user_name(obj)} - {self.get_animal_name(obj)}"

    def _report_status_label(self, obj):
        try:
            rep = getattr(obj, "report", None)
            if rep:
                return dict(Report.STATUS_CHOICES).get(getattr(rep, "status", None))
        except Exception:
            pass
        return None

    def get_message(self, obj):
        # t = getattr(obj, "type", None)

        # # ✅ 그룹 공지: 본문(reply) 보여주기
        # if t == "group":
        #     txt = (obj.reply or "").strip()
        #     if txt:
        #         return txt
        #     # 드물게 reply가 없고 status_change만 있는 경우 라벨로라도 표시
        #     sl = self.get_status_label(obj)
        #     return sl or "공지"

        # # ✅ 개인 알림: 표의 동물/신고ID/상태와 '내용'을 100% 일치
        # rid = getattr(obj, "report_id", None)
        # animal = self.get_animal_name(obj) or "미상"
        # status_label = self.get_status_label(obj) or self._report_status_label(obj) or "미상"

        # parts = [f"동물: {animal}"]
        # if rid:
        #     parts.append(f"신고 ID: {rid}")
        # parts.append(f"상태: {status_label}")
        # return " / ".join(parts)
        return (obj.reply or '').strip()

    # ---------- 유효성 ----------
    def validate(self, attrs):
        t    = attrs.get('type') or getattr(self.instance, 'type', None)
        user = attrs.get('user', getattr(self.instance, 'user', None))

        if t not in ('group', 'individual'):
            raise serializers.ValidationError({'type': "type은 'group' 또는 'individual'이어야 합니다."})
        if t == 'individual' and user is None:
            raise serializers.ValidationError({'user_id_in': '개인 알림(type=individual)에는 user가 필요합니다.'})
        if t == 'group' and user is not None:
            raise serializers.ValidationError({'user_id_in': '그룹 알림(type=group)에는 user가 있으면 안 됩니다.'})

        # (선택) 관리자 계정이 개인 알림 수신자가 되지 않도록
        if user is not None and hasattr(user, 'admin') and user.admin_id:
            raise serializers.ValidationError({'user_id_in': '관리자 계정은 개인 알림 수신자가 될 수 없습니다.'})

        sc = attrs.get('status_change') if 'status_change' in attrs else getattr(self.instance, 'status_change', None)
        rp = attrs.get('reply')         if 'reply'         in attrs else getattr(self.instance, 'reply', None)
        if not sc and not rp:
            raise serializers.ValidationError({'detail': 'status_change 또는 reply 중 하나는 필요합니다.'})
        if sc and sc not in dict(Notification.STATUS_CHANGE_CHOICES):
            raise serializers.ValidationError({'status_change': f'허용되지 않은 값: {sc}'})
        return attrs

class FeedbackSerializer(serializers.ModelSerializer):
    feedback_id = serializers.IntegerField(read_only=True)
    report_id   = serializers.PrimaryKeyRelatedField(source='report', queryset=Report.objects.all())
    user_id     = serializers.PrimaryKeyRelatedField(source='user', queryset=User.objects.all())
    admin_id    = serializers.PrimaryKeyRelatedField(source='admin', queryset=User.objects.all(),
                                                     allow_null=True, required=False)
    class Meta:
        model = Feedback
        fields = [
            'feedback_id',
            'report_id',
            'user_id',
            'content',
            'feedback_datetime',
            'admin_id',
        ]
        read_only_fields = ["feedback_id", "feedback_datetime"]

    def validate(self, attrs):
        rep = attrs.get('report') or getattr(self.instance, 'report', None)
        if rep and Feedback.objects.filter(report=rep).exclude(pk=getattr(self.instance, 'pk', None)).exists():
            raise serializers.ValidationError("이 보고서에는 이미 피드백이 1건 존재합니다.")
        return attrs


class StatisticSerializer(serializers.ModelSerializer):
    class Meta:
        model = Statistic
        fields = (
            'id', 'state_unit', 'state_year',
            'state_month', 'all_reports',
            'completed', 'incomplete'
        )
        read_only_fields = ('id',)

class AdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Admin
        fields = ['id', 'email', 'name', 'created_at']
        read_only_fields = ['id', 'created_at']

class ProfileSerializer(serializers.ModelSerializer):
    # 프론트 요구사항: name, email을 User와 매핑
    name = serializers.CharField(source='user.first_name', required=False, allow_blank=True)
    email = serializers.EmailField(source='user.email', required=False)

    class Meta:
        model = Profile
        fields = (
            'name', 'email',
            'address', 'phone',
            'consent_terms', 'consent_location', 'consent_marketing'
        )

    def validate(self, attrs):
        # email unique 검사 (본인 제외)
        user_data = attrs.get('user', {})
        email = user_data.get('email')
        if email:
            user_qs = User.objects.filter(email=email)
            instance = getattr(self, 'instance', None)
            if instance:  # update
                user_qs = user_qs.exclude(pk=instance.user_id)
            if user_qs.exists():
                raise serializers.ValidationError({'email': '이미 사용 중인 이메일입니다.'})
        return attrs

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        # User.first_name <- name
        if 'first_name' in user_data:
            instance.user.first_name = user_data['first_name']
        # User.email <- email
        if 'email' in user_data:
            instance.user.email = user_data['email']
        instance.user.save(update_fields=['first_name', 'email'])

        # Profile 나머지 필드
        return super().update(instance, validated_data)

class UserProfileSerializer(serializers.ModelSerializer):
    # 프론트 별칭 → 실제 User 필드로 매핑
    name = serializers.CharField(source="first_name", required=False, allow_blank=True)
    phone = serializers.CharField(source="telphone", required=False, allow_blank=True)
    address = serializers.CharField(source="user_address", required=False, allow_blank=True)
    consent_terms = serializers.BooleanField(source="agree", required=False)

    class Meta:
        model = User
        fields = [
            "email",
            "name", "first_name",
            "telphone", "phone",
            "user_address", "address",
            "agree", "consent_terms",
            "consent_location",
            "consent_marketing",
        ]
        read_only_fields = []

    def validate_email(self, value):
        if value:
            qs = User.objects.filter(email=value)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("이미 사용 중인 이메일입니다.")
        return value

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

# api/serializers.py
from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from rest_framework import serializers
from django.apps import apps
from urllib.parse import urlencode
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.utils import OperationalError, IntegrityError
from django.conf import settings

# --- GeoDjango PointField 지원(없어도 동작)
try:
    from django.contrib.gis.geos import Point  # type: ignore
except Exception:  # GeoDjango 미사용 환경
    Point = None  # type: ignore

from .models import (
    Animal, SearchHistory, Location, Report,
    Notification, Feedback, Admin, Statistic, SavedPlace,
    Profile, DeviceToken, AppBanner
)
from django.db.models.fields.files import FieldFile

# 허용 플랫폼 집합 (모델의 CHOICES를 그대로 사용)
ALLOWED_PLATFORMS = {p for p, _ in getattr(DeviceToken, "PLATFORM_CHOICES", [])} or {"android", "ios", "web"}

# 재시도 횟수(경합 시)
RETRIES = 3

User = get_user_model()
SearchHistory = apps.get_model('api', 'SearchHistory')
Animal = apps.get_model('api', 'Animal')


# =========================
# 공통: Location 스키마-무관 생성기
# =========================
# >>> CHANGED: Location 스키마가 lat/lng, latitude/longitude, point, address 등
# 어떤 조합이어도 안전하게 생성/재사용하도록 헬퍼를 둔다.

def _to_float_or_none(v):
    try:
        if v in (None, ""):
            return None
        return float(v)
    except Exception:
        return None

def _first_key(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

def _to_decimal(v):
    try:
        if v in (None, ""):
            return None
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None

def _fields(model):
    return {getattr(f, "name", None) for f in model._meta.get_fields()}

def _create_location_safely(lat: float | None, lng: float | None, addr: str | None) -> Location | None:
    """
    Location 스키마에 맞춰 안전하게 Location을 반환.
    - 좌표가 둘 다 없으면: latitude/longitude(또는 lat/lng)가 모델에서 nullable일 때만 '주소만'으로 생성.
      그렇지 않으면 None 반환(=> Report.location FK 비움)
    - 좌표가 있으면: latitude/longitude > lat/lng > point 순서로 생성/재사용
    """
    fields = _fields(Location)

    # ----- 좌표가 없는 경우 -----
    if lat is None or lng is None:
        # 모델의 null 허용 여부 확인
        def _nullable(fn: str) -> bool:
            try:
                f = Location._meta.get_field(fn)
                return bool(getattr(f, "null", False))
            except Exception:
                return False

        can_addr_only = (
            # latitude/longitude 필드가 아예 없거나,
            (not {'latitude', 'longitude'} <= fields) and (not {'lat', 'lng'} <= fields) and ('point' not in fields)
        ) or (
            # 있긴 한데 둘 다 nullable
            ({'latitude', 'longitude'} <= fields and _nullable('latitude') and _nullable('longitude')) or
            ({'lat', 'lng'} <= fields and _nullable('lat') and _nullable('lng'))
        )

        if not can_addr_only:
            # 좌표 없이 만들 수 없는 스키마 → 생성하지 않고 None (FK 비움)
            return None

        data = {}
        if 'address' in fields:
            data['address'] = (addr or '').strip()
        if 'name' in fields and not data.get('address'):
            data['name'] = (addr or '').strip()[:100]

        # address/name 어느 것도 저장할 수 없으면 포기
        if not data:
            return None

        # 주소만으로 생성(좌표는 NULL 허용 전제)
        return Location.objects.create(**data)

    # ----- 좌표가 있는 경우 -----
    lat_d = _to_decimal(lat)
    lng_d = _to_decimal(lng)

    # 1) latitude/longitude
    if {'latitude', 'longitude'} <= fields:
        loc, _ = Location.objects.get_or_create(
            latitude=lat_d, longitude=lng_d,
            defaults={
                **({'address': (addr or '').strip()} if 'address' in fields else {}),
                **({'region': ''} if 'region' in fields else {}),
                **({'city': ''} if 'city' in fields else {}),
                **({'district': ''} if 'district' in fields else {}),
                **({'name': (addr or '').strip()[:100]} if 'name' in fields else {}),
            }
        )
        return loc

    # 2) lat/lng
    if {'lat', 'lng'} <= fields:
        loc, _ = Location.objects.get_or_create(
            lat=lat_d, lng=lng_d,
            defaults={
                **({'address': (addr or '').strip()} if 'address' in fields else {}),
                **({'region': ''} if 'region' in fields else {}),
                **({'city': ''} if 'city' in fields else {}),
                **({'district': ''} if 'district' in fields else {}),
                **({'name': (addr or '').strip()[:100]} if 'name' in fields else {}),
            }
        )
        return loc

    # 3) point (GeoDjango)
    if 'point' in fields and Point is not None:
        try:
            return Location.objects.create(
                point=Point(float(lng), float(lat)),
                **({'address': (addr or '').strip()} if 'address' in fields else {}),
                **({'name': (addr or '').strip()[:100]} if 'name' in fields else {}),
            )
        except Exception:
            pass  # point 생성 실패 시 주소-only로 폴백 시도

    # 4) 마지막: address/name만 저장 (이 경우도 스키마가 허용(둘 다 nullable)일 때만)
    try:
        lat_field = Location._meta.get_field('latitude')
        lng_field = Location._meta.get_field('longitude')
        if not (getattr(lat_field, 'null', False) and getattr(lng_field, 'null', False)):
            return None
    except Exception:
        # latitude/longitude 필드가 없으면 패스
        pass

    data = {}
    if 'address' in fields:
        data['address'] = (addr or '').strip()
    if 'name' in fields and not data.get('address'):
        data['name'] = (addr or '').strip()[:100]
    if not data:
        return None
    return Location.objects.create(**data)


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
            'image_url', 'image', 'imageUrl',
            'features',
            'precautions',
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
            features = [s.lstrip('- ').strip() for s in feats.splitlines() if s.strip()]
        else:
            features = []

        return {
            'name':        getattr(a, 'name_kor', None),
            'english':     getattr(a, 'name_eng', None),
            'image_url':   getattr(a, 'image_url', None),
            'features':    features,
            'precautions': getattr(a, 'precautions', None),
            'description': getattr(a, 'description', None),
        }

    def get_proxied_image_url(self, obj):
        if not getattr(obj, 'image_url', None):
            return None
        q = urlencode({'url': obj.image_url})
        request = self.context.get('request')
        path = f'/api/image-proxy/?{q}'
        return request.build_absolute_uri(path) if request else path

class SearchHistoryCreateSerializer(serializers.ModelSerializer):
    """
    생성 전용: 같은 (user, keyword)은 업서트로 처리.
    응답은 읽기용 SearchHistorySerializer 포맷으로 돌려줌.
    """
    class Meta:
        model = apps.get_model('api', 'SearchHistory')
        fields = ['keyword']

    def create(self, validated_data):
        # user는 perform_create에서 넘겨주거나, context.request에서 얻습니다.
        req  = self.context.get('request')
        user = validated_data.pop('user', None) or getattr(req, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            raise serializers.ValidationError({'detail': '인증이 필요합니다.'})

        keyword = (validated_data.get('keyword') or '').strip()
        if not keyword:
            raise serializers.ValidationError({'keyword': '빈 값은 저장할 수 없습니다.'})

        SH = apps.get_model('api', 'SearchHistory')

        with transaction.atomic():
            # 동일 키 모두 조회(최신 우선)
            qs = SH.objects.select_for_update().filter(
                user=user, keyword=keyword
            ).order_by('-id')

            existing = qs.first()
            if existing:
                # (선택) “최근 검색” 의미를 살리려면 타임스탬프 갱신
                # existing.searched_at = timezone.now()
                # existing.save(update_fields=['searched_at'])

                # 중복 제거
                qs.exclude(pk=existing.pk).delete()
                return existing

            return SH.objects.create(user=user, keyword=keyword)

    def to_representation(self, instance):
        return SearchHistorySerializer(instance, context=self.context).data

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

class AppBannerSerializer(serializers.ModelSerializer): # create/update
    class Meta:
        model = AppBanner
        fields = ["id","text","cta_url","starts_at","ends_at","priority","is_active","created_at"]

class AppBannerReadSerializer(serializers.ModelSerializer): # 앱 응답용
    class Meta:
        model = AppBanner
        fields = ["id","text","cta_url"]  # 앱은 가볍게

# 활성 배너만 주는 전용 리스트
class AppBannerActiveSerializer(serializers.Serializer):
    pass  # 빈 serializer (쿼리만으로 응답)

# =========================
# 신고 생성 (무인증 라우트)
# =========================
# >>> CHANGED: Location 생성 로직을 _create_location_safely 사용으로 통일

class ReportNoAuthCreateSerializer(serializers.Serializer):
    animalId   = serializers.IntegerField(required=False, allow_null=True)
    locationId = serializers.IntegerField(required=False, allow_null=True)
    status     = serializers.ChoiceField(
        choices=[c[0] for c in Report.STATUS_CHOICES],
        default='checking'
    )
    photo      = serializers.ImageField()
    lat = serializers.FloatField(required=False)
    lng = serializers.FloatField(required=False)
    address = serializers.CharField(required=False, allow_blank=True, allow_null=True)  # <<< 주소도 허용

    def create(self, validated):
        # 0) 동물 폴백
        animal = None
        animal_id = validated.get("animalId")
        if animal_id:
            animal = Animal.objects.get(id=animal_id)
        else:
            animal, _ = Animal.objects.get_or_create(
                name_kor="미상", defaults={"name_eng": "unknown"}
            )

        # 1) 위치 결정
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
            addr = validated.get("address")
            loc = _create_location_safely(lat, lng, addr)

        # 2) Report 생성
        report = Report.objects.create(
            user=None,
            animal=animal,
            location=loc,
            status=validated.get("status") or "checking",
            image=validated["photo"],
            report_date=timezone.now(),
        )
        return report


class SavedPlaceReadSerializer(serializers.ModelSerializer):
    type      = serializers.CharField(source='name', read_only=True)
    address   = serializers.CharField(source='location.address',   read_only=True)
    region    = serializers.CharField(source='location.region',    read_only=True, allow_blank=True)
    city      = serializers.CharField(source='location.city',      read_only=True, allow_blank=True)
    district  = serializers.CharField(source='location.district',  read_only=True, allow_blank=True)
    latitude  = serializers.FloatField(source='location.latitude',  read_only=True)
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
    location  = serializers.CharField(write_only=True)
    address   = serializers.CharField(write_only=True, required=False, allow_blank=True)
    region    = serializers.CharField(write_only=True, required=False, allow_blank=True)
    city      = serializers.CharField(write_only=True, required=False, allow_blank=True)
    district  = serializers.CharField(write_only=True, required=False, allow_blank=True)
    latitude  = serializers.FloatField(write_only=True, required=False)
    longitude = serializers.FloatField(write_only=True, required=False)
    type      = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model  = SavedPlace
        fields = [
            'id', 'name', 'type', 'client_id', 'created_at',
            'location', 'address', 'region', 'city', 'district',
            'latitude', 'longitude',
        ]
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        loc_raw = (attrs.get('location') or '').strip()
        addr    = (attrs.get('address')  or '').strip()

        # lat/lng 별칭 허용
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

        # location이 PK면 통과
        if loc_raw.isdigit():
            return attrs

        # 주소 문자열로 생성하는 경우 → 좌표 필수
        use_addr = addr if addr else loc_raw
        attrs['__resolved_address__'] = use_addr
        if attrs.get('latitude') is None or attrs.get('longitude') is None:
            raise serializers.ValidationError({'detail': '주소 문자열로 생성 시 latitude/longitude(또는 lat/lng)가 필수입니다.'})
        return attrs

    def _resolve_location(self, attrs) -> Location:
        loc_raw = (attrs.get('location') or '').strip()
        if loc_raw.isdigit():
            try:
                return Location.objects.get(pk=int(loc_raw))
            except Location.DoesNotExist:
                raise serializers.ValidationError({'location': f'존재하지 않는 Location PK입니다: {loc_raw}'})

        address  = attrs.get('__resolved_address__')
        region   = (attrs.get('region')   or '').strip()
        city     = (attrs.get('city')     or '').strip()
        district = (attrs.get('district') or '').strip()

        lat_f = float(attrs.get('latitude'))
        lng_f = float(attrs.get('longitude'))
        lat_d = _to_decimal(lat_f)
        lng_d = _to_decimal(lng_f)

        fields = _fields(Location)

        # latitude/longitude 기반 모델
        if {'latitude', 'longitude'} <= fields:
            loc, created = Location.objects.get_or_create(
                address=address if 'address' in fields else None,
                defaults={
                    'region': region if 'region' in fields else '',
                    'city': city if 'city' in fields else '',
                    'district': district if 'district' in fields else '',
                    'latitude': lat_d, 'longitude': lng_d,
                }
            )
            if not created:
                # 기존 Location에 좌표 비어 있으면 채워줌
                need_update = (
                    getattr(loc, 'latitude', None) in (None, '') or
                    getattr(loc, 'longitude', None) in (None, '')
                )
                if need_update:
                    loc.latitude, loc.longitude = lat_d, lng_d
                    loc.save(update_fields=['latitude', 'longitude'])
            return loc

        # lat/lng 모델을 사용하는 경우
        if {'lat', 'lng'} <= fields:
            loc, created = Location.objects.get_or_create(
                address=address if 'address' in fields else None,
                defaults={
                    'region': region if 'region' in fields else '',
                    'city': city if 'city' in fields else '',
                    'district': district if 'district' in fields else '',
                    'lat': lat_d, 'lng': lng_d,
                }
            )
            if not created and (getattr(loc, 'lat', None) in (None, '') or getattr(loc, 'lng', None) in (None, '')):
                loc.lat, loc.lng = lat_d, lng_d
                loc.save(update_fields=['lat', 'lng'])
            return loc

        # 그 외(POINT 타입 등) → 안전 생성
        return _create_location_safely(lat_f, lng_f, address)

    def create(self, validated_data):
      loc = self._resolve_location(validated_data)

      name_in = (validated_data.get('name') or '').strip()
      type_in = (validated_data.get('type') or '').strip()
      addr_in = (validated_data.get('__resolved_address__') or '').strip()
      final_name = name_in or type_in or addr_in or '장소'

      # 불필요 필드 정리
      lat = validated_data.pop('latitude',  None)
      lng = validated_data.pop('longitude', None)
      for k in ('name','location','address','region','city','district','type','__resolved_address__'):
          validated_data.pop(k, None)

      # ✅ (user, client_id)로 업서트
      user = self.context['request'].user
      client_id = validated_data.get('client_id')
      defaults = {
          'location': loc,
          'name': final_name,
          'latitude': _to_decimal(lat) if lat is not None else None,
          'longitude': _to_decimal(lng) if lng is not None else None,
      }

      obj, created = SavedPlace.objects.update_or_create(
          user=user,
          client_id=client_id,   # 모델에 unique(user, client_id) 가정
          defaults=defaults,
      )
      return obj

    def to_representation(self, instance):
        return SavedPlaceReadSerializer(instance, context=self.context).data


# ─────────────────────────────
# ReportSerializer (리스트/읽기용)
# ─────────────────────────────

class ReportSerializer(serializers.ModelSerializer):
    report_id        = serializers.IntegerField(source='id', read_only=True)
    animal_name      = serializers.SerializerMethodField(read_only=True)
    photo_url        = serializers.SerializerMethodField(read_only=True)
    image_url        = serializers.SerializerMethodField(read_only=True)
    reporter_display = serializers.SerializerMethodField(read_only=True)

    # 쓰기용 (뷰셋에서 사용 시)
    location_id = serializers.PrimaryKeyRelatedField(
        source='location',
        queryset=Location.objects.all(),
        write_only=True,
        required=False
    )
    animal_id = serializers.PrimaryKeyRelatedField(
        source='animal',
        queryset=Animal.objects.all(),
        write_only=True,
        required=False
    )

    # 읽기용
    location = LocationSerializer(read_only=True)
    user_id  = serializers.PrimaryKeyRelatedField(source='user', read_only=True)

    class Meta:
        model = Report
        fields = [
            'report_id',
            'report_date',
            'animal_id', 'animal_name',
            'status',
            'user_id',
            'image',
            'photo_url',
            'image_url', 'reporter_display',
            'location_id',
            'location',
        ]
        read_only_fields = ['report_id', 'animal_name', 'location', 'user_id', 'photo_url', 'image_url']

    def get_image_url(self, obj):
        """
        모델의 다양한 후보 필드에서 안전하게 이미지 URL을 뽑는다.
        FileField는 name이 없으면 .url 접근 금지.
        """
        request = self.context.get('request')

        CANDIDATES = ('photo', 'image', 'img', 'picture', 'photo1', 'photo_url')
        for name in CANDIDATES:
            if not hasattr(obj, name):
                continue

            f = getattr(obj, name, None)

            # 1) File/ImageField
            if isinstance(f, FieldFile):
                if getattr(f, 'name', None):  # 파일이 실제로 존재할 때만
                    try:
                        url = f.url
                        if url:
                            return request.build_absolute_uri(url) if (request and url.startswith('/')) else url
                    except Exception:
                        pass
                continue

            # 2) 문자열 URL
            if isinstance(f, str):
                s = f.strip()
                if s:
                    return request.build_absolute_uri(s) if (request and s.startswith('/')) else s

        return None

    def get_animal_name(self, obj):
        a = getattr(obj, 'animal', None)
        if a is None:
            return '미상'
        return getattr(a, 'name_kor', None) or getattr(a, 'name_eng', None) or str(a)

    def get_photo_url(self, obj):
        f = getattr(obj, 'image', None)
        if not isinstance(f, FieldFile) or not getattr(f, 'name', None):
            return None
        req = self.context.get('request')
        try:
            url = f.url
            return req.build_absolute_uri(url) if (req and url.startswith('/')) else url
        except Exception:
            return None

    def validate_status(self, value):
        allowed = {c[0] for c in Report.STATUS_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError('허용되지 않은 상태값입니다.')
        return value

    def get_reporter_display(self, obj):
        u = getattr(obj, 'user', None)
        if u:
            full = ""
            try:
                full = u.get_full_name() or ""
            except Exception:
                pass
            return full or getattr(u, 'username', '') or getattr(u, 'email', '') or "익명"
        for k in ('reporter_name', 'reporter', 'contact_name', 'writer_name'):
            v = getattr(obj, k, None)
            if v:
                return str(v)
        return "익명"


# ─────────────────────────────
# ReportCreateSerializer (생성 전용)
# ─────────────────────────────

class ReportCreateSerializer(serializers.ModelSerializer):
    # 입력 전용 (앱에서 다양한 키를 허용)
    lat     = serializers.FloatField(write_only=True, required=False, allow_null=True)
    lng     = serializers.FloatField(write_only=True, required=False, allow_null=True)
    address = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    image   = serializers.ImageField(required=False, allow_null=True)

    # 읽기 전용 편의
    photo_url     = serializers.SerializerMethodField(read_only=True)
    animal_name   = serializers.CharField(source='animal.name_kor', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)

    class Meta:
        model = Report
        fields = [
            'id',
            'user',           # 읽기 전용으로 유지(서버에서 채움)
            'animal',         # FK: 앱은 보통 ID로 보냄 (animal=15)
            'location',       # 읽기 전용(서버에서 생성/할당)
            'report_date',    # 서버에서 now()로 채움
            'image',
            'status',
            'lat', 'lng', 'address',
            'photo_url', 'animal_name', 'location_name',
        ]
        read_only_fields = [
            'id', 'user', 'location', 'report_date',
            'photo_url', 'animal_name', 'location_name'
        ]

    def get_photo_url(self, obj):
        f = getattr(obj, 'image', None)
        if not isinstance(f, FieldFile) or not getattr(f, 'name', None):
            return None
        req = self.context.get('request')
        try:
            url = f.url
            return req.build_absolute_uri(url) if (req and url.startswith('/')) else url
        except Exception:
            return None

    def create(self, validated):
        """
        - 로그인 사용자는 user에 자동 연결
        - report_date는 서버 시각으로 강제 세팅
        - 좌표가 둘 다 있을 때만 Location 생성(없으면 FK None)
        """
        req = self.context.get('request')
        u = getattr(req, 'user', None)
        validated['user'] = (u if (u and u.is_authenticated) else None)

        # 서버 시각(앱에서 보내더라도 서버 기준으로 덮어씀)
        validated['report_date'] = timezone.now()

        # 위치
        lat = validated.pop('lat', None)
        lng = validated.pop('lng', None)
        addr = (validated.pop('address', None) or "").strip() or None
        loc = _create_location_safely(lat, lng, addr)
        validated['location'] = loc

        # status는 모델 default('checking')가 있으면 그대로 두고, 없으면 값 검사
        # animal은 앱이 ID로 보내야 함(animal=15). 이름으로 받고 싶으면 별도 매핑 로직 추가.

        return Report.objects.create(**validated)

class NotificationSerializer(serializers.ModelSerializer):
    notification_id = serializers.IntegerField(source='id', read_only=True)

    user_id   = serializers.IntegerField(read_only=True)
    admin_id  = serializers.IntegerField(read_only=True)
    report_id = serializers.IntegerField(read_only=True)

    user_id_in = serializers.PrimaryKeyRelatedField(
        source='user',
        queryset=User.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    user_name    = serializers.SerializerMethodField()
    animal_name  = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    title        = serializers.SerializerMethodField()
    message      = serializers.SerializerMethodField()

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

    def _pick_user(self, obj):
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
        if t == 'group':
            label = self.get_status_label(obj)
            if label:
                return f"전체 공지 · {label}"
            rep = (obj.reply or '').strip()
            if rep:
                first_line = rep.splitlines()[0].strip()
                if len(first_line) > 30:
                    first_line = first_line[:29] + '…'
                return f"전체 공지 · {first_line}"
            return "전체 공지"
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
        return (obj.reply or '').strip()

    def validate(self, attrs):
        t    = attrs.get('type') or getattr(self.instance, 'type', None)
        user = attrs.get('user', getattr(self.instance, 'user', None))

        if t not in ('group', 'individual'):
            raise serializers.ValidationError({'type': "type은 'group' 또는 'individual'이어야 합니다."})
        if t == 'individual' and user is None:
            raise serializers.ValidationError({'user_id_in': '개인 알림(type=individual)에는 user가 필요합니다.'})
        if t == 'group' and user is not None:
            raise serializers.ValidationError({'user_id_in': '그룹 알림(type=group)에는 user가 있으면 안 됩니다.'})

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
        user_data = attrs.get('user', {})
        email = user_data.get('email')
        if email:
            user_qs = User.objects.filter(email=email)
            instance = getattr(self, 'instance', None)
            if instance:
                user_qs = user_qs.exclude(pk=instance.user_id)
            if user_qs.exists():
                raise serializers.ValidationError({'email': '이미 사용 중인 이메일입니다.'})
        return attrs

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        if 'first_name' in user_data:
            instance.user.first_name = user_data['first_name']
        if 'email' in user_data:
            instance.user.email = user_data['email']
        instance.user.save(update_fields=['first_name', 'email'])
        return super().update(instance, validated_data)


class UserProfileSerializer(serializers.ModelSerializer):
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

RETRIES = 3

# 토큰 저장 API
class DeviceTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceToken                     # ★ 누락됐던 부분
        fields = ["id", "user", "token", "platform", "is_active", "updated_at", "created_at"]
        read_only_fields = ["id", "updated_at", "created_at"]

    def validate_token(self, value: str) -> str:
        v = (value or "").strip()
        if not v:
            raise serializers.ValidationError("token is required")
        # 모델 max_length와 일치시키세요(권장 512). 초과 시 방어.
        if len(v) > 512:
            raise serializers.ValidationError("token too long")
        return v

    def validate_platform(self, value: str) -> str:
        v = (value or "android").strip() or "android"
        if v not in ALLOWED_PLATFORMS:
            raise serializers.ValidationError(f"platform must be one of {sorted(ALLOWED_PLATFORMS)}")
        return v

    def create(self, validated_data):
        req = self.context.get("request")
        user = getattr(req, "user", None)
        user = user if (user and getattr(user, "is_authenticated", False)) else None

        token: str = validated_data["token"]
        platform: str = validated_data.get("platform", "android")

        last_exc = None
        for attempt in range(RETRIES):
            try:
                with transaction.atomic():
                    # 1) 업서트
                    obj, created = DeviceToken.objects.get_or_create(
                        token=token,
                        defaults={"platform": platform, "user": user, "is_active": True},
                    )
                    # 2) 기존이면 필요한 필드만 갱신
                    changed = False
                    if obj.platform != platform:
                        obj.platform = platform
                        changed = True
                    if user and obj.user_id != getattr(user, "id", None):
                        obj.user = user
                        changed = True
                    if not obj.is_active:         # 재등록 시 다시 활성화
                        obj.is_active = True
                        changed = True
                    if changed:
                        obj.save(update_fields=["platform", "user", "is_active", "updated_at"])
                    return obj
            except (OperationalError, IntegrityError) as e:
                last_exc = e
                time.sleep(0.15 * (attempt + 1))
        raise serializers.ValidationError({"detail": f"database busy: {last_exc}"})


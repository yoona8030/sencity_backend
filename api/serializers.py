# api/serializers.py
from rest_framework import serializers
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.apps import apps
from urllib.parse import urlencode
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
        ]

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

class SavedPlaceSerializer(serializers.ModelSerializer):
    # ✅ 프론트가 기대하는 응답 필드로 변환 (읽기 전용)
    type = serializers.CharField(source='name', read_only=True)
    location = serializers.CharField(source='location.address', read_only=True)
    lat = serializers.FloatField(source='latitude', read_only=True)
    lng = serializers.FloatField(source='longitude', read_only=True)

    class Meta:
        model = SavedPlace
        fields = ['id', 'type', 'location', 'lat', 'lng', 'client_id', 'created_at']
        read_only_fields = ['id', 'type', 'location', 'lat', 'lng', 'created_at']

    # 내부 유틸: 위/경도로 Location 확보
    def _get_or_create_location(self, *, address: str, lat: float, lng: float) -> Location:
        loc, created = Location.objects.get_or_create(
            latitude=lat,
            longitude=lng,
            defaults={'address': address or ''}  # address가 NULL 금지면 ''로
        )
        # 주소가 비어있던 기존 Location이면 채워주기(선택)
        if not created and not (loc.address or '').strip() and address:
            loc.address = address
            loc.save(update_fields=['address'])
        return loc

    def create(self, validated_data):
        # ⚠️ 프론트는 write 필드를 model 필드명과 다르게 보냄 → initial_data에서 직접 꺼냄
        raw = self.initial_data or {}
        try:
            address = (raw.get('location') or '').strip()
            name = (raw.get('type') or address or '장소').strip()
            lat = float(raw.get('lat'))
            lng = float(raw.get('lng'))
        except (TypeError, ValueError):
            raise serializers.ValidationError({'lat_lng': 'lat/lng는 숫자여야 합니다.'})

        if address == '':
            # address(문자열)가 굳이 필수는 아니지만, 있으면 좋음
            # 필수로 강제하고 싶으면 ValidationError로 막아도 OK
            pass

        client_id = raw.get('client_id') or None
        user = self.context['request'].user

        # ✅ latitude/longitude 필수로 Location 생성/획득 (NOT NULL 회피)
        loc = self._get_or_create_location(address=address, lat=lat, lng=lng)

        place = SavedPlace.objects.create(
            user=user,
            name=name,
            location=loc,
            latitude=lat,
            longitude=lng,
            client_id=client_id
        )
        return place
    
class ReportSerializer(serializers.ModelSerializer):
    report_id   = serializers.IntegerField(source='id', read_only=True)
    animal_name = serializers.SerializerMethodField(read_only=True)

    location_id = serializers.PrimaryKeyRelatedField(
        source='location',
        queryset=Location.objects.all(),
        write_only=True
    )

    location = LocationSerializer(read_only=True)  # 조회 시 상세 위치 정보 포함

    user_id = serializers.PrimaryKeyRelatedField(
        source='user',
        read_only=True
    )
    animal_id = serializers.PrimaryKeyRelatedField(
        source='animal',
        queryset=Animal.objects.all(),
        write_only=True
    )

    class Meta:
        model = Report
        fields = [
            'report_id',
            'report_date',
            'animal_id', 'animal_name',
            'status',
            'user_id',
            'image',
            'location_id',  # 쓰기
            'location',     # 읽기
        ]
        read_only_fields = ['report_id', 'animal_name', 'location', 'user_id']

    def get_animal_name(self, obj):
        return getattr(obj.animal, 'name_kor', str(obj.animal))

    def validate_status(self, value):
        allowed = {c[0] for c in Report.STATUS_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError('허용되지 않은 상태값입니다.')
        return value
        
class NotificationSerializer(serializers.ModelSerializer):
    notification_id = serializers.IntegerField(source='id', read_only=True)

    # ▶ read-only id 필드들 (source 지정하지 마세요: DRF가 알아서 obj.user_id/…를 읽습니다)
    user_id   = serializers.IntegerField(read_only=True)
    admin_id  = serializers.IntegerField(read_only=True)
    report_id = serializers.IntegerField(read_only=True)

    # ▶ write-only 입력용 (개인 알림 생성 시 받기 위함)
    user_id_in = serializers.PrimaryKeyRelatedField(
        source='user',
        queryset=User.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    # ▶ 표시용
    user_name    = serializers.SerializerMethodField()
    animal_name  = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'notification_id',
            'type', 'created_at',
            'reply', 'status_change', 'status_label',
            'user_id', 'admin_id', 'report_id', 'user_id_in',
            'user_name', 'animal_name',
        ]
        read_only_fields = ['notification_id', 'created_at', 'user_id', 'admin_id', 'report_id']

    def get_user_name(self, obj):
        # 우선순위: 알림의 user → 리포트의 user
        u = getattr(obj, 'user', None) or getattr(getattr(obj, 'report', None), 'user', None)
        if not u:
            return '사용자'
        return u.first_name or u.username or f'사용자 #{u.id}'

    def get_animal_name(self, obj):
        a = getattr(getattr(obj, 'report', None), 'animal', None)
        return getattr(a, 'name_kor', None) or '미상'

    def get_status_label(self, obj):
        return dict(Notification.STATUS_CHANGE_CHOICES).get(obj.status_change)

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

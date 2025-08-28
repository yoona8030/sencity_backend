# api/serializers.py
from rest_framework import serializers
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from .models import (
    Animal, SearchHistory, Location, Report,
    Notification, Feedback, Admin, Statistic, SavedPlace,
    Profile
)

User = get_user_model()


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
    class Meta:
        model = Animal
        fields = (
            'id',
            'name_kor',
            'name_eng',
            'image_url',
            'description',
            'features',
            'precautions',
        )


class SearchHistorySerializer(serializers.ModelSerializer):
    animal_info = serializers.SerializerMethodField()

    class Meta:
        model = SearchHistory
        fields = ('id', 'keyword', 'searched_at', 'animal_info')
        read_only_fields = ('id', 'searched_at')

    def get_animal_info(self, obj):
        try:
            animal = Animal.objects.get(name_kor=obj.keyword)
            return {
                'name_kor':    animal.name_kor,
                'name_eng':    animal.name_eng,
                'image_url':   animal.image_url,
                'features':    animal.features,
                'precautions': animal.precautions,
                'description': animal.description,
            }
        except Animal.DoesNotExist:
            return None


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

    # user_id는 쓰기 가능(개인 알림에서만)하게 유지
    from django.contrib.auth import get_user_model
    UserModel = get_user_model()
    user_id = serializers.PrimaryKeyRelatedField(
        source='user',
        queryset=UserModel.objects.all(),
        write_only=True,
        allow_null=True,
        required=False
    )

    # admin_id는 서버에서 세팅(읽기 전용)으로 통일
    admin_id = serializers.PrimaryKeyRelatedField(source='admin', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'notification_id',
            'user_id',
            'admin_id',
            'type',           # 'group' | 'single'
            'status_change',  # 선택
            'reply',          # 선택
            'created_at',
        ]
        read_only_fields = ['notification_id', 'created_at', 'admin_id']

    def validate(self, attrs):
        # 현재 요청의 type (없으면 기존 인스턴스에서 가져오기)
        t = attrs.get('type') or getattr(self.instance, 'type', None)
        usr = attrs.get('user', getattr(self.instance, 'user', None))

        # 유효값은 'group' 또는 'single' 로 통일
        if t not in ('group', 'single'):
            raise serializers.ValidationError({'type': "type은 'group' 또는 'single'이어야 합니다."})

        # 개인 알림(single)에는 user 필수
        if t == 'single' and not usr:
            raise serializers.ValidationError({'user': '개인 알림(type=single)에는 user가 필수입니다.'})

        # 그룹 알림(group)에는 user가 있으면 안 됨
        if t == 'group' and usr:
            raise serializers.ValidationError({'user': '그룹 알림(type=group)에서는 user를 비워야 합니다.'})

        sc = attrs.get('status_change') if 'status_change' in attrs else getattr(self.instance, 'status_change', None)
        rp = attrs.get('reply') if 'reply' in attrs else getattr(self.instance, 'reply', None)

        if not sc and not rp:
            raise serializers.ValidationError({'detail': "status_change 또는 reply 중 하나는 반드시 포함해야 합니다."})

        # status_change 값 유효성 (선택)
        if sc and sc not in dict(Notification.STATUS_CHANGE_CHOICES):
            raise serializers.ValidationError({'status_change': f"허용되지 않은 값입니다: {sc}"})

        return attrs

class FeedbackSerializer(serializers.ModelSerializer):
    feedback_id = serializers.IntegerField(read_only=True)
    report_id   = serializers.PrimaryKeyRelatedField(source='report', queryset=Feedback._meta.apps.get_model('api', 'Report').objects.all())
    user_id     = serializers.PrimaryKeyRelatedField(source='user', queryset=Feedback._meta.apps.get_model('api', 'User').objects.all())
    admin_id    = serializers.PrimaryKeyRelatedField(source='admin', queryset=Feedback._meta.apps.get_model('api', 'User').objects.all(), allow_null=True, required=False)

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

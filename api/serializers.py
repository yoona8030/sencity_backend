# api/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Animal, SearchHistory, Location, Report,
    Notification, Feedback, Statistic
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


class ReportSerializer(serializers.ModelSerializer):
    report_id   = serializers.IntegerField(source='id', read_only=True)
    animal_name = serializers.SerializerMethodField(read_only=True)

    # 🔹 Report → Location FK
    location_id = serializers.PrimaryKeyRelatedField(
        source='location',
        queryset=Location.objects.all(),
        write_only=True
    )

    location = LocationSerializer(read_only=True)  # 조회 시 상세 위치 정보 포함

    user_id = serializers.PrimaryKeyRelatedField(
        source='user',
        queryset=User.objects.all(),
        write_only=True,
        required=False
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
        read_only_fields = ['report_id', 'animal_name', 'location']

    def get_animal_name(self, obj):
        return getattr(obj.animal, 'name_kor', str(obj.animal))

    def validate_status(self, value):
        allowed = {c[0] for c in Report.STATUS_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError('허용되지 않은 상태값입니다.')
        return value
        
class NotificationSerializer(serializers.ModelSerializer):
    notification_id = serializers.IntegerField(source='id', read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        source='user',
        queryset=Notification._meta.apps.get_model('api', 'User').objects.all(),
        write_only=True
    )

    class Meta:
        model = Notification
        fields = [
            'notification_id',
            'user_id',
            'type',           # 'group' | 'single'
            'status_change',  # 선택
            'reply',          # 선택
            'created_at', 
        ]
        read_only_fields = ['notification_id', 'created_at', ]

    def validate(self, attrs):
        t = attrs.get('type') or getattr(self.instance, 'type', None)
        if t not in ('group', 'single'):
            raise serializers.ValidationError({'type': "type은 'group' 또는 'single'이어야 합니다."})

        sc = attrs.get('status_change') if 'status_change' in attrs else getattr(self.instance, 'status_change', None)
        rp = attrs.get('reply') if 'reply' in attrs else getattr(self.instance, 'reply', None)
        
        if not sc and not rp:
            raise serializers.ValidationError({'detail': "status_change 또는 reply 중 하나는 반드시 포함해야 합니다."})
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


class StatisticSerializer(serializers.ModelSerializer):
    class Meta:
        model = Statistic
        fields = (
            'id', 'state_unit', 'state_year',
            'state_month', 'all_reports',
            'completed', 'incomplete'
        )
        read_only_fields = ('id',)

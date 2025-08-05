from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import SearchHistory, Animal  

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'telphone', 'address', 'agree')

class UserSignUpSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    email = serializers.EmailField()
    telphone = serializers.CharField()
    address = serializers.CharField(required=False, allow_blank=True)
    agree = serializers.BooleanField()
    
    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'telphone', 'address', 'agree')

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("이미 등록된 이메일입니다.")
        return value

    def create(self, validated_data):
        user = User(
            username=validated_data['username'],
            email=validated_data['email'],
            telphone=validated_data['telphone'],
            address=validated_data.get('address', ''),
            agree=validated_data['agree'],
        )
        user.set_password(validated_data['password'])
        user.save()
        return user

class SearchHistorySerializer(serializers.ModelSerializer):
    animal_info = serializers.SerializerMethodField()

    class Meta:
        model = SearchHistory
        fields = ['id', 'keyword', 'searched_at', 'animal_info']
        read_only_fields = ['id']

    def get_animal_info(self, obj):
        try:
            animal = Animal.objects.get(name_kor=obj.keyword)
            return {
                'english': animal.name_eng,
                'image_url': animal.image_url,
                'features': animal.features,
                'precautions': animal.precautions,
                'description': animal.description
            }
        except Animal.DoesNotExist:
            return None  # ✅ 예외처리 깔끔

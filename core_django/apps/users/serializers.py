from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'first_name', 'last_name')

    def create(self, validated_data):
        from django.db import transaction
        from apps.subscriptions.services import grant_new_user_trial_pro
        
        with transaction.atomic():
            user = User.objects.create_user(
                username=validated_data['username'],
                email=validated_data.get('email', ''),
                password=validated_data['password'],
                first_name=validated_data.get('first_name', ''),
                last_name=validated_data.get('last_name', '')
            )
            grant_new_user_trial_pro(user)
        return user

from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile

class UserDetailSerializer(serializers.ModelSerializer):
    equipped_frame = serializers.SerializerMethodField()
    equipped_title = serializers.SerializerMethodField()
    levels = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'bio', 'avatar', 'date_joined', 'equipped_frame', 'equipped_title', 'levels')
        read_only_fields = ('id', 'username', 'date_joined')

    def get_equipped_frame(self, obj):
        from apps.gamification.models import UserInventory
        from apps.gamification.serializers import RewardItemSerializer
        inv = UserInventory.objects.filter(user=obj, reward_item__reward_type='avatar_frame', is_equipped=True).select_related('reward_item').first()
        if inv:
            return RewardItemSerializer(inv.reward_item).data
        return None

    def get_equipped_title(self, obj):
        from apps.gamification.models import UserInventory
        from apps.gamification.serializers import RewardItemSerializer
        inv = UserInventory.objects.filter(user=obj, reward_item__reward_type='title', is_equipped=True).select_related('reward_item').first()
        if inv:
            return RewardItemSerializer(inv.reward_item).data
        return None

    def get_levels(self, obj):
        from apps.gamification.models import UserLanguageLevel
        from apps.gamification.leveling_service import LevelingService
        levels = UserLanguageLevel.objects.filter(user=obj)
        data = {}
        for lv in levels:
            data[lv.lang] = {
                'level': lv.level,
                'current_exp': lv.current_exp,
                'exp_required': LevelingService.exp_required_for_level(lv.level),
                'total_exp': lv.total_exp,
            }
        # Ensure both zh and en exist in output (defaults if not in DB yet)
        for lang in ['zh', 'en']:
            if lang not in data:
                data[lang] = {
                    'level': 1,
                    'current_exp': 0,
                    'exp_required': 100,
                    'total_exp': 0
                }
        return data

    def validate_avatar(self, avatar):
        if not avatar:
            return avatar

        # Mở dữ liệu ảnh bằng Pillow
        img = Image.open(avatar)

        # Chuẩn hóa kích thước tối đa cho Avatar (Giới hạn ở mức 400x400 pixels)
        max_size = (400, 400)
        if img.width > 400 or img.height > 400:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # Nén và chuyển định dạng sang WebP
        output = BytesIO()
        
        # Chuyển đổi về hệ màu RGB để tránh lỗi đối với ảnh PNG có nền trong suốt (RGBA)
        if img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Nén với chất lượng 85%
        img.save(output, format='WEBP', quality=85)
        output.seek(0)

        # Đổi tên file extension thành .webp
        new_name = f"{avatar.name.split('.')[0]}.webp"
        return ContentFile(output.read(), name=new_name)

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True)

    def validate_new_password(self, value):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        
        user = self.context['request'].user
        try:
            validate_password(value, user=user)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        if not user.check_password(attrs.get('old_password')):
            raise serializers.ValidationError({"old_password": "Mật khẩu cũ không chính xác."})
        return attrs

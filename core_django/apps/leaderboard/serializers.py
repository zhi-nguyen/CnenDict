from rest_framework import serializers
from .models import LeaderboardSnapshot, LeaderboardEntry

class LeaderboardEntrySerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    equipped_frame = serializers.SerializerMethodField()
    equipped_title = serializers.SerializerMethodField()

    class Meta:
        model = LeaderboardEntry
        fields = ('rank', 'score', 'username', 'avatar_url', 'user', 'equipped_frame', 'equipped_title')

    def get_username(self, obj):
        full_name = obj.user.get_full_name().strip()
        return full_name if full_name else obj.username

    def get_equipped_frame(self, obj):
        from apps.gamification.models import UserInventory
        from apps.gamification.serializers import RewardItemSerializer
        inv = UserInventory.objects.filter(user=obj.user, reward_item__reward_type='avatar_frame', is_equipped=True).select_related('reward_item').first()
        if inv:
            return RewardItemSerializer(inv.reward_item).data
        return None

    def get_equipped_title(self, obj):
        from apps.gamification.models import UserInventory
        from apps.gamification.serializers import RewardItemSerializer
        inv = UserInventory.objects.filter(user=obj.user, reward_item__reward_type='title', is_equipped=True).select_related('reward_item').first()
        if inv:
            return RewardItemSerializer(inv.reward_item).data
        return None

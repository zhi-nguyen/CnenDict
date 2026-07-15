from rest_framework import serializers
from .models import LeaderboardSnapshot, LeaderboardEntry

class LeaderboardEntrySerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()

    class Meta:
        model = LeaderboardEntry
        fields = ('rank', 'score', 'username', 'avatar_url', 'user')

    def get_username(self, obj):
        full_name = obj.user.get_full_name().strip()
        return full_name if full_name else obj.username

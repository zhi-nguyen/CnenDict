from rest_framework import serializers
from .models import (
    UserStreak, DailyTarget, StudyHistory, DailyActivity, StudySession, StudySessionCard, CoinWallet, CoinTransaction,
    UserLanguageLevel, EXPTransaction, RewardItem, UserInventory, LevelRewardLog
)

class UserStreakSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserStreak
        fields = ['current_streak', 'max_streak']

class DailyTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyTarget
        fields = ['target_words', 'target_duration', 'target_type']

class StudyHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = StudyHistory
        fields = ['study_date', 'vocabulary_learned', 'pronunciation_accuracy', 'study_duration_seconds']
        read_only_fields = ['study_date']

class DailyActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyActivity
        fields = ['activity_date', 'is_target_met']


class StudySessionCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudySessionCard
        fields = ['id', 'card_id', 'word', 'status', 'updated_at']


class StudySessionSerializer(serializers.ModelSerializer):
    cards = StudySessionCardSerializer(many=True, read_only=True, source='session_cards')

    class Meta:
        model = StudySession
        fields = ['id', 'lang', 'status', 'total_cards', 'memorized_count', 'coins_earned', 'created_at', 'finished_at', 'cards']
        read_only_fields = ['id', 'status', 'total_cards', 'memorized_count', 'coins_earned', 'created_at', 'finished_at']


class CoinWalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoinWallet
        fields = ['lang', 'paid_balance', 'free_balance', 'shop_balance', 'total_balance', 'updated_at']


class CoinTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoinTransaction
        fields = ['id', 'group_id', 'transaction_type', 'balance_type', 'amount', 'paid_balance_after', 'free_balance_after', 'shop_balance_after', 'reference_id', 'note', 'created_at']


class UserLanguageLevelSerializer(serializers.ModelSerializer):
    exp_required = serializers.SerializerMethodField()

    class Meta:
        model = UserLanguageLevel
        fields = ['lang', 'level', 'current_exp', 'exp_required', 'total_exp', 'updated_at']

    def get_exp_required(self, obj):
        from .leveling_service import LevelingService
        return LevelingService.exp_required_for_level(obj.level)


class EXPTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EXPTransaction
        fields = ['id', 'lang', 'source_type', 'amount', 'level_before', 'level_after', 'exp_before', 'exp_after', 'reference_id', 'note', 'created_at']


class RewardItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RewardItem
        fields = ['id', 'name', 'reward_type', 'description', 'image_url', 'title_text', 'rarity', 'ui_metadata', 'is_sellable', 'price_free', 'price_paid', 'price_shop']


class UserInventorySerializer(serializers.ModelSerializer):
    reward_item = RewardItemSerializer(read_only=True)

    class Meta:
        model = UserInventory
        fields = ['id', 'reward_item', 'quantity', 'is_equipped', 'acquired_at']



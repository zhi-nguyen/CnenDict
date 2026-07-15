from django.contrib import admin
from .models import UserStreak, DailyTarget, StudyHistory, DailyActivity

@admin.register(UserStreak)
class UserStreakAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_streak', 'max_streak')
    search_fields = ('user__username', 'user__email')

@admin.register(DailyTarget)
class DailyTargetAdmin(admin.ModelAdmin):
    list_display = ('user', 'target_words', 'target_duration', 'target_type')
    search_fields = ('user__username', 'user__email')

@admin.register(StudyHistory)
class StudyHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'study_date', 'vocabulary_learned', 'pronunciation_accuracy', 'study_duration_seconds')
    list_filter = ('study_date',)
    search_fields = ('user__username', 'user__email')

@admin.register(DailyActivity)
class DailyActivityAdmin(admin.ModelAdmin):
    list_display = ('user', 'activity_date', 'is_target_met')
    list_filter = ('activity_date', 'is_target_met')
    search_fields = ('user__username', 'user__email')


from .models import CoinWallet, CoinTransaction, CoinConfig, StudySession, StudySessionCard, CoinPurchaseOrder

@admin.register(CoinConfig)
class CoinConfigAdmin(admin.ModelAdmin):
    list_display = ('tier', 'weekly_refill_cap', 'initial_coins_zh', 'initial_coins_en',
                    'words_per_coin', 'daily_free_earn_limit', 'chat_create_cost', 'chat_message_cost',
                    'writing_base_cost_zh', 'writing_increment_cost_zh',
                    'writing_base_cost_en', 'writing_increment_cost_en',
                    'pdf_normal_export_cost', 'pdf_stroke_export_cost')

@admin.register(CoinWallet)
class CoinWalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'lang', 'paid_balance', 'free_balance', 'total_balance', 'updated_at')
    list_filter = ('lang',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('id',)

@admin.register(CoinTransaction)
class CoinTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'wallet', 'transaction_type', 'balance_type', 'amount',
                    'paid_balance_after', 'free_balance_after', 'created_at')
    list_filter = ('transaction_type', 'balance_type')
    search_fields = ('user__username', 'reference_id')
    readonly_fields = ('id', 'wallet', 'user', 'transaction_type', 'balance_type',
                       'amount', 'paid_balance_after', 'free_balance_after', 'reference_id')

@admin.register(CoinPurchaseOrder)
class CoinPurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('order_code', 'user', 'lang', 'coin_amount', 'price', 'status', 'created_at')
    list_filter = ('status', 'lang')
    readonly_fields = ('id', 'order_code', 'sepay_transaction_id', 'bank_reference')

class StudySessionCardInline(admin.TabularInline):
    model = StudySessionCard
    extra = 0
    readonly_fields = ('card_id', 'word', 'status')

@admin.register(StudySession)
class StudySessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'lang', 'status', 'total_cards', 'memorized_count', 'coins_earned', 'created_at')
    list_filter = ('status', 'lang')
    inlines = [StudySessionCardInline]

@admin.register(StudySessionCard)
class StudySessionCardAdmin(admin.ModelAdmin):
    list_display = ('session', 'card_id', 'word', 'status', 'updated_at')
    list_filter = ('status',)


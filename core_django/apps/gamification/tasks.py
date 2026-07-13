from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import UserStreak, DailyTarget, StudyHistory, DailyActivity
from django.db import transaction

@shared_task
def calculate_daily_streaks():
    # Use timezone.now() which is set to Asia/Ho_Chi_Minh
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)

    # 1. Process users who studied yesterday
    histories_yesterday = StudyHistory.objects.filter(study_date=yesterday).select_related('user', 'user__streak', 'user__daily_target')
    
    streaks_to_update = []
    activities_to_create = []

    for history in histories_yesterday:
        user = history.user
        target = user.daily_target
        streak, _ = UserStreak.objects.get_or_create(user=user)
        
        is_met = False
        if target.target_type == 'words' and history.vocabulary_learned >= target.target_words:
            is_met = True
        elif target.target_type == 'duration' and history.study_duration_seconds >= (target.target_duration * 60):
            is_met = True
        
        if is_met:
            streak.current_streak += 1
            if streak.current_streak > streak.max_streak:
                streak.max_streak = streak.current_streak
        else:
            streak.current_streak = 0
            
        streaks_to_update.append(streak)
        activities_to_create.append(
            DailyActivity(user=user, activity_date=yesterday, is_target_met=is_met)
        )

    # 2. Process users who DID NOT study yesterday but have current_streak > 0 (they missed a day)
    users_studied_yesterday_ids = [h.user.id for h in histories_yesterday]
    streaks_to_reset = UserStreak.objects.filter(current_streak__gt=0).exclude(user_id__in=users_studied_yesterday_ids)

    for streak in streaks_to_reset:
        streak.current_streak = 0
        streaks_to_update.append(streak)
        activities_to_create.append(
            DailyActivity(user=streak.user, activity_date=yesterday, is_target_met=False)
        )

    # Bulk update and create to optimize DB hits
    with transaction.atomic():
        if streaks_to_update:
            UserStreak.objects.bulk_update(streaks_to_update, ['current_streak', 'max_streak'])
        if activities_to_create:
            DailyActivity.objects.bulk_create(activities_to_create, ignore_conflicts=True)

    return f"Processed {len(histories_yesterday)} active users, reset {streaks_to_reset.count()} inactive streaks."


@shared_task
def weekly_coin_refill():
    """
    ╔══════════════════════════════════════════════╗
    ║  MASTER TASK — Chạy mỗi Thứ 2 (Celery Beat) ║
    ╚══════════════════════════════════════════════╝
    
    Chỉ quét DB để thu thập danh sách (user_id, tier).
    KHÔNG lock row, KHÔNG ghi dữ liệu.
    Dispatch sub-tasks cho Workers xử lý song song.
    """
    from apps.subscriptions.models import UserSubscription
    from django.contrib.auth import get_user_model
    import logging
    
    logger = logging.getLogger(__name__)
    dispatched = 0
    
    # 1. Users có subscription
    for sub in UserSubscription.objects.values_list('user_id', 'tier', 'is_active').iterator(chunk_size=1000):
        user_id, tier, is_active = sub
        effective_tier = tier if is_active else 'Free'
        refill_individual_wallet_task.delay(str(user_id), effective_tier)
        dispatched += 1
    
    # 2. Users chưa có subscription (= Free)
    User = get_user_model()
    users_without_sub = User.objects.filter(
        subscription__isnull=True
    ).values_list('id', flat=True).iterator(chunk_size=1000)
    
    for user_id in users_without_sub:
        refill_individual_wallet_task.delay(str(user_id), 'Free')
        dispatched += 1
    
    logger.info(f"Weekly refill master dispatched {dispatched} sub-tasks")
    return f"Dispatched {dispatched} refill sub-tasks"


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def refill_individual_wallet_task(self, user_id: str, tier: str):
    """
    ╔═══════════════════════════════════════════╗
    ║  WORKER SUB-TASK — 1 user, cả 2 ví       ║
    ╚═══════════════════════════════════════════╝
    
    Lock scope: 1 row × vài ms. Xử lý song song bởi N workers.
    """
    from django.contrib.auth import get_user_model
    from .coin_service import CoinService
    import logging
    
    logger = logging.getLogger(__name__)
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning(f"User {user_id} not found for weekly refill")
        return
    
    try:
        for lang in ['zh', 'en']:
            CoinService.apply_weekly_refill_for_wallet(user, lang, tier)
    except Exception as e:
        logger.error(f"Failed refill for user {user_id} (tier={tier}): {e}", exc_info=True)
        raise self.retry(exc=e)


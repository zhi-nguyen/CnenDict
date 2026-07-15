import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.db.models import Sum, Q, Count
from django.contrib.auth import get_user_model

from .models import LeaderboardSnapshot, LeaderboardEntry
from apps.gamification.models import CoinWallet, CoinTransaction, StudySession, StudySessionCard, UserStreak

logger = logging.getLogger(__name__)
User = get_user_model()

@shared_task
def refresh_all_leaderboards():
    """
    Task định kỳ chạy mỗi 4 tiếng để cập nhật bảng xếp hạng
    Sinh snapshot mới và lấy TOP 50 cho từng loại bảng xếp hạng
    """
    logger.info("Starting scheduled leaderboard refresh...")
    for lang in ['zh', 'en']:
        try:
            refresh_coin_leaderboard(lang, 'paid')
            refresh_coin_leaderboard(lang, 'free')
            refresh_likes_leaderboard(lang)
            refresh_weekly_words_leaderboard(lang)
            refresh_streak_leaderboard(lang)
        except Exception as e:
            logger.error(f"Error refreshing leaderboard for lang={lang}: {e}", exc_info=True)
            
    # Tự động dọn dẹp các snapshot cũ
    cleanup_old_snapshots()
    logger.info("Leaderboard refresh completed.")


def refresh_coin_leaderboard(lang: str, balance_type: str):
    """
    Xếp hạng user theo tổng coin paid/free (Số dư hiện tại + Điểm đã dùng)
    """
    board_type = f'coin_{balance_type}'
    snapshot = LeaderboardSnapshot.objects.create(board_type=board_type, lang=lang)

    wallets = CoinWallet.objects.filter(lang=lang)
    entries_to_create = []
    
    for wallet in wallets:
        user = wallet.user
        current_balance = wallet.paid_balance if balance_type == 'paid' else wallet.free_balance
        
        # Tính điểm đã tiêu dùng (amount < 0) của wallet này
        spent_amount = CoinTransaction.objects.filter(
            wallet=wallet,
            balance_type=balance_type,
            amount__lt=0
        ).aggregate(total_spent=Sum('amount'))['total_spent'] or 0
        
        total_score = current_balance + abs(spent_amount)
        
        if total_score > 0:
            entries_to_create.append({
                'user': user,
                'score': total_score,
                'username': user.username,
                'avatar_url': user.avatar.url if user.avatar else ''
            })

    entries_to_create.sort(key=lambda x: x['score'], reverse=True)

    bulk_entries = []
    for rank, item in enumerate(entries_to_create[:50], start=1):
        bulk_entries.append(
            LeaderboardEntry(
                snapshot=snapshot,
                user=item['user'],
                rank=rank,
                score=item['score'],
                username=item['username'],
                avatar_url=item['avatar_url']
            )
        )
        
    if bulk_entries:
        LeaderboardEntry.objects.bulk_create(bulk_entries)
    logger.info(f"Refreshed board {board_type} for {lang} - {len(bulk_entries)} entries created.")


def refresh_likes_leaderboard(lang: str):
    """
    Xếp hạng user theo tổng lượt like (WordComment upvotes + ForumPost likes)
    """
    snapshot = LeaderboardSnapshot.objects.create(board_type='total_likes', lang=lang)
    
    users = User.objects.all()
    entries_to_create = []

    for user in users:
        from apps.community.models import WordComment, ForumPost
        word_comments_likes = WordComment.objects.filter(
            user=user, lang=lang, is_hidden=False
        ).aggregate(total=Sum('upvotes'))['total'] or 0

        posts_likes = ForumPost.objects.filter(
            author=user, lang=lang, is_hidden=False
        ).aggregate(total=Sum('like_count'))['total'] or 0

        total_likes = word_comments_likes + posts_likes

        if total_likes > 0:
            entries_to_create.append({
                'user': user,
                'score': total_likes,
                'username': user.username,
                'avatar_url': user.avatar.url if user.avatar else ''
            })

    entries_to_create.sort(key=lambda x: x['score'], reverse=True)
    
    bulk_entries = []
    for rank, item in enumerate(entries_to_create[:50], start=1):
        bulk_entries.append(
            LeaderboardEntry(
                snapshot=snapshot,
                user=item['user'],
                rank=rank,
                score=item['score'],
                username=item['username'],
                avatar_url=item['avatar_url']
            )
        )
        
    if bulk_entries:
        LeaderboardEntry.objects.bulk_create(bulk_entries)
    logger.info(f"Refreshed board total_likes for {lang} - {len(bulk_entries)} entries created.")


def refresh_weekly_words_leaderboard(lang: str):
    """
    Xếp hạng user theo tổng số từ đã thuộc trong tuần (tránh spam, đếm distinct từ đã học thuộc)
    """
    snapshot = LeaderboardSnapshot.objects.create(board_type='weekly_words', lang=lang)
    start_of_week = timezone.now() - timedelta(days=7)

    active_cards = StudySessionCard.objects.filter(
        session__lang=lang,
        session__status='FINISHED',
        status='memorized',
        updated_at__gte=start_of_week
    ).values('session__user').annotate(
        distinct_words=Count('word', distinct=True)
    ).order_by('-distinct_words')

    bulk_entries = []
    rank = 1
    for item in active_cards[:50]:
        try:
            user = User.objects.get(pk=item['session__user'])
            score = item['distinct_words']
            bulk_entries.append(
                LeaderboardEntry(
                    snapshot=snapshot,
                    user=user,
                    rank=rank,
                    score=score,
                    username=user.username,
                    avatar_url=user.avatar.url if user.avatar else ''
                )
            )
            rank += 1
        except User.DoesNotExist:
            continue

    if bulk_entries:
        LeaderboardEntry.objects.bulk_create(bulk_entries)
    logger.info(f"Refreshed board weekly_words for {lang} - {len(bulk_entries)} entries created.")


def refresh_streak_leaderboard(lang: str):
    """
    Xếp hạng user theo Streak (sử dụng UserStreak.max_streak của tài khoản),
    nhưng chỉ xếp hạng cho ngôn ngữ đó nếu user có phiên học tập hợp lệ (StudySession)
    trong vòng 7 ngày gần nhất trên ngôn ngữ đó.
    """
    snapshot = LeaderboardSnapshot.objects.create(board_type='max_streak', lang=lang)
    start_of_week = timezone.now() - timedelta(days=7)

    active_users_ids = StudySession.objects.filter(
        lang=lang,
        created_at__gte=start_of_week
    ).values_list('user_id', flat=True).distinct()

    streaks = UserStreak.objects.filter(
        user_id__in=active_users_ids,
        max_streak__gt=0
    ).select_related('user').order_by('-max_streak')

    bulk_entries = []
    rank = 1
    for streak in streaks[:50]:
        user = streak.user
        bulk_entries.append(
            LeaderboardEntry(
                snapshot=snapshot,
                user=user,
                rank=rank,
                score=streak.max_streak,
                username=user.username,
                avatar_url=user.avatar.url if user.avatar else ''
            )
        )
        rank += 1

    if bulk_entries:
        LeaderboardEntry.objects.bulk_create(bulk_entries)
    logger.info(f"Refreshed board max_streak for {lang} - {len(bulk_entries)} entries created.")


@shared_task
def cleanup_old_snapshots():
    """
    Dọn dẹp các snapshot cũ hơn 24 giờ để tránh phình to cơ sở dữ liệu
    """
    time_limit = timezone.now() - timedelta(days=1)
    old_snapshots = LeaderboardSnapshot.objects.filter(created_at__lt=time_limit)
    count = old_snapshots.count()
    old_snapshots.delete()
    logger.info(f"Cleaned up {count} old leaderboard snapshots.")

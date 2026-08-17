import logging
from datetime import timedelta
from typing import Optional, Tuple
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.dispatch import receiver
from .models import (
    QuestDefinition, UserQuestProgress, QuestClaimLog, UserInventory
)
from .leveling_service import LevelingService
from .coin_service import CoinService
from .quest_signals import quest_action_signal

logger = logging.getLogger(__name__)


class QuestNotFoundError(Exception):
    """Nhiệm vụ không tồn tại hoặc đã bị vô hiệu hóa."""
    pass


class QuestNotCompletedError(Exception):
    """Nhiệm vụ chưa hoàn thành điều kiện để nhận thưởng."""
    pass


class AlreadyClaimedError(Exception):
    """Phần thưởng nhiệm vụ đã được nhận trước đó."""
    pass


class QuestService:
    """
    Business logic layer cho hệ thống Nhiệm vụ (Quest System).
    
    Kiến trúc:
    - Lazy Initialization: Chỉ tạo UserQuestProgress khi user truy cập hoặc phát sinh action.
    - Concurrency Control: Dùng F() expressions chống race condition khi cập nhật tiến độ,
      và select_for_update() + transaction.atomic() khi nhận thưởng.
    - Event-Driven: Lắng nghe quest_action_signal để tự động cập nhật tiến độ.
    """

    @staticmethod
    def get_current_period(quest_type: str) -> Tuple[Optional[object], Optional[object]]:
        """
        Tính period_start và period_end theo timezone hệ thống (Asia/Ho_Chi_Minh).
        - daily: [today, today]
        - weekly: [thứ 2 tuần này, chủ nhật tuần này]
        - achievement / event: [None, None]
        """
        today = timezone.localdate()
        if quest_type == 'daily':
            return today, today
        elif quest_type == 'weekly':
            # weekday: Monday is 0, Sunday is 6
            start_of_week = today - timedelta(days=today.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            return start_of_week, end_of_week
        else:
            return None, None

    @staticmethod
    def ensure_user_progress(user, quest: QuestDefinition) -> UserQuestProgress:
        """
        Lazy Initialization: Lấy hoặc tạo mới bản ghi UserQuestProgress
        cho user theo chu kỳ hiện tại của quest.
        """
        period_start, period_end = QuestService.get_current_period(quest.quest_type)
        progress, _created = UserQuestProgress.objects.get_or_create(
            user=user,
            quest=quest,
            period_start=period_start,
            defaults={
                'period_end': period_end,
                'status': 'in_progress',
                'current_value': 0,
            }
        )
        return progress

    @staticmethod
    def get_user_quests(user, quest_type: Optional[str] = None, lang: str = 'all'):
        """
        Lấy danh sách nhiệm vụ và tiến độ hiện tại của user.
        Tự động lazy-init các quest chưa có record trong chu kỳ này.
        """
        now = timezone.now()
        quest_query = QuestDefinition.objects.filter(is_active=True)

        if quest_type:
            quest_query = quest_query.filter(quest_type=quest_type)

        if lang and lang != 'all':
            quest_query = quest_query.filter(Q(lang=lang) | Q(lang='all'))

        # Lọc các quest event theo thời hạn hợp lệ nếu có
        quest_query = quest_query.filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=now),
            Q(valid_to__isnull=True) | Q(valid_to__gte=now)
        )

        quests = list(quest_query.order_by('quest_type', 'sort_order', 'created_at'))

        # Lazy initialize progress cho từng quest
        progress_list = []
        for q in quests:
            p = QuestService.ensure_user_progress(user, q)
            progress_list.append(p)

        return progress_list

    @staticmethod
    def increment_progress(user, trigger_type: str, amount: int = 1, lang: str = 'all'):
        """
        Cập nhật tiến độ nhiệm vụ theo trigger_type.
        Đảm bảo an toàn race condition bằng F() expressions và atomic transactions.
        """
        if amount <= 0:
            return

        now = timezone.now()
        matching_quests = QuestDefinition.objects.filter(
            is_active=True,
            trigger_type=trigger_type
        ).filter(
            Q(lang='all') | Q(lang=lang) if lang != 'all' else Q()
        ).filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=now),
            Q(valid_to__isnull=True) | Q(valid_to__gte=now)
        )

        completed_quests_to_notify = []

        for quest in matching_quests:
            try:
                with transaction.atomic():
                    period_start, period_end = QuestService.get_current_period(quest.quest_type)
                    
                    # Đảm bảo record tồn tại trước khi khóa
                    UserQuestProgress.objects.get_or_create(
                        user=user,
                        quest=quest,
                        period_start=period_start,
                        defaults={
                            'period_end': period_end,
                            'status': 'in_progress',
                            'current_value': 0,
                        }
                    )

                    progress = UserQuestProgress.objects.select_for_update().get(
                        user=user,
                        quest=quest,
                        period_start=period_start
                    )

                    # Bỏ qua nếu quest đã hoàn thành hoặc đã nhận thưởng
                    if progress.status != 'in_progress':
                        continue

                    # Milestone triggers (streak, level) lấy giá trị tuyệt đối lớn nhất
                    if trigger_type in ['streak_days', 'reach_level']:
                        if amount > progress.current_value:
                            progress.current_value = amount
                    else:
                        # Cumulative triggers dùng F() expression
                        progress.current_value = F('current_value') + amount

                    progress.save(update_fields=['current_value', 'updated_at'])
                    progress.refresh_from_db()

                    # Kiểm tra hoàn thành nhiệm vụ
                    if progress.current_value >= quest.target_value:
                        progress.status = 'completed'
                        progress.completed_at = timezone.now()
                        progress.save(update_fields=['status', 'completed_at', 'updated_at'])
                        completed_quests_to_notify.append(quest)

            except Exception as e:
                logger.error(f"Error updating quest progress for user {user.id}, quest {quest.id}: {e}", exc_info=True)

        # Gửi thông báo WebSocket nếu có nhiệm vụ vừa hoàn thành
        for q in completed_quests_to_notify:
            try:
                from core_project.ws_utils import ws_notify
                ws_notify(
                    user_id=user.id,
                    event_type='quest_completed',
                    title=f"Đã hoàn thành nhiệm vụ: {q.name}!",
                    payload={
                        'quest_id': str(q.id),
                        'quest_name': q.name,
                        'reward_exp': q.reward_exp,
                        'reward_coins': q.reward_coins,
                    },
                    persist=False
                )
            except Exception as ws_err:
                logger.debug(f"Could not send quest WS notification: {ws_err}")

    @staticmethod
    @transaction.atomic
    def claim_reward(user, progress_id, target_lang: str = 'zh') -> dict:
        """
        Nhận phần thưởng cho nhiệm vụ đã hoàn thành.
        - Row-Level Locking (select_for_update)
        - Idempotency check qua QuestClaimLog
        - Cấp EXP, Coin, RewardItem (nếu có)
        """
        try:
            progress = UserQuestProgress.objects.select_for_update().select_related(
                'quest', 'quest__reward_item'
            ).get(id=progress_id, user=user)
        except UserQuestProgress.DoesNotExist:
            raise QuestNotFoundError("Không tìm thấy tiến độ nhiệm vụ.")

        quest = progress.quest

        # Kiểm tra trạng thái đã nhận thưởng
        if progress.status == 'claimed':
            raise AlreadyClaimedError("Phần thưởng cho nhiệm vụ này đã được nhận.")

        # Tự động cập nhật completed nếu current_value đã đạt target
        if progress.status != 'completed':
            if progress.current_value >= quest.target_value:
                progress.status = 'completed'
                progress.completed_at = timezone.now()
            else:
                raise QuestNotCompletedError("Nhiệm vụ chưa hoàn thành, không thể nhận thưởng.")

        # Kiểm tra chống nhận thưởng trùng lặp trong chu kỳ (Audit check)
        if QuestClaimLog.objects.filter(user=user, quest=quest, period_start=progress.period_start).exists():
            progress.status = 'claimed'
            progress.save(update_fields=['status'])
            raise AlreadyClaimedError("Phần thưởng cho nhiệm vụ này đã được nhận trước đó.")

        # Xác định ngôn ngữ để cộng EXP và Coin
        reward_lang = quest.lang if quest.lang in ['zh', 'en'] else (target_lang if target_lang in ['zh', 'en'] else 'zh')

        # 1. Cấp EXP
        exp_result = None
        if quest.reward_exp > 0:
            exp_result = LevelingService.add_exp(
                user=user,
                lang=reward_lang,
                amount=quest.reward_exp,
                source_type='QUEST_COMPLETE',
                idempotency_key=f"QUEST_EXP:{user.id}:{quest.id}:{progress.period_start or 'perm'}",
                reference_id=str(progress.id),
                note=f"Thưởng nhiệm vụ: {quest.name}"
            )

        # 2. Cấp Coin (free_balance)
        coins_earned = 0
        if quest.reward_coins > 0:
            _txn, coins_earned, _is_capped = CoinService.earn_coins(
                user=user,
                lang=reward_lang,
                amount=quest.reward_coins,
                reference_id=str(progress.id),
                note=f"Thưởng nhiệm vụ: {quest.name}"
            )

        # 3. Cấp RewardItem (nếu có)
        item_granted = None
        if quest.reward_item and quest.reward_item.is_active:
            inv, created = UserInventory.objects.get_or_create(
                user=user,
                reward_item=quest.reward_item,
                defaults={'quantity': quest.reward_item_quantity}
            )
            if not created:
                inv.quantity += quest.reward_item_quantity
                inv.save(update_fields=['quantity'])
            item_granted = quest.reward_item

        # 4. Ghi nhận QuestClaimLog
        claim_log = QuestClaimLog.objects.create(
            user=user,
            quest=quest,
            progress=progress,
            period_start=progress.period_start,
            exp_granted=quest.reward_exp,
            coins_granted=coins_earned,
            item_granted=item_granted,
            item_quantity_granted=quest.reward_item_quantity if item_granted else 0,
        )

        # 5. Cập nhật trạng thái progress
        progress.status = 'claimed'
        progress.claimed_at = timezone.now()
        progress.save(update_fields=['status', 'claimed_at', 'updated_at'])

        # Lấy số dư ví mới nhất
        wallet_balances = CoinService.get_all_balances(user)

        return {
            'status': 'success',
            'message': f"Đã nhận thưởng thành công nhiệm vụ '{quest.name}'",
            'progress_id': str(progress.id),
            'exp_granted': quest.reward_exp,
            'coins_granted': coins_earned,
            'item_granted': {
                'id': str(item_granted.id),
                'name': item_granted.name,
                'reward_type': item_granted.reward_type,
                'image_url': item_granted.image_url,
                'quantity': quest.reward_item_quantity,
            } if item_granted else None,
            'level_up': exp_result.get('leveled_up', False) if exp_result else False,
            'level_after': exp_result.get('level_after') if exp_result else None,
            'wallet_balances': wallet_balances,
        }


# ── Receiver cho Django Signals ──
@receiver(quest_action_signal)
def handle_quest_action(sender, user, trigger_type, lang='all', amount=1, **kwargs):
    """
    Lắng nghe domain event và cập nhật tiến độ nhiệm vụ tự động.
    """
    try:
        if user and user.is_authenticated:
            QuestService.increment_progress(
                user=user,
                trigger_type=trigger_type,
                amount=amount,
                lang=lang
            )
    except Exception as e:
        logger.error(f"Error handling quest_action_signal ({trigger_type}): {e}", exc_info=True)

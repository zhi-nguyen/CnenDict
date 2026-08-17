import logging
import math
from django.db import transaction, IntegrityError
from .models import UserLanguageLevel, EXPTransaction, RewardRule, UserInventory, LevelRewardLog
from .coin_service import CoinService

logger = logging.getLogger(__name__)


class LevelingService:
    """
    Core business logic cho hệ thống Level & EXP.
    
    Công thức EXP mỗi level (cấp số nhân theo bracket):
    - LV 1-10:  100 EXP / level
    - LV 11-20: 200 EXP / level
    - LV 21-30: 400 EXP / level
    - LV 31-40: 800 EXP / level
    - ...
    - Bracket n (LV (n-1)*10+1 → n*10): 100 * 2^(n-1) EXP / level
    """

    @staticmethod
    def exp_required_for_level(level: int) -> int:
        """Tính EXP cần thiết để hoàn thành level hiện tại."""
        if level < 1:
            return 100
        bracket = (level - 1) // 10  # 0-based bracket index
        return 100 * (2 ** bracket)

    @staticmethod
    def get_or_create_level(user, lang: str) -> UserLanguageLevel:
        """Lấy hoặc tạo record level cho user + lang."""
        obj, _ = UserLanguageLevel.objects.get_or_create(user=user, lang=lang)
        return obj

    @staticmethod
    @transaction.atomic
    def add_exp(user, lang: str, amount: int, source_type: str, 
                idempotency_key: str = None,
                reference_id='', note='') -> dict:
        """
        Cộng/trừ EXP, tự động level up/clamp.
        
        Idempotency: Nếu idempotency_key đã tồn tại trong EXPTransaction,
        hàm sẽ trả về kết quả "đã xử lý" mà KHÔNG cộng thêm EXP.
        
        Args:
            idempotency_key: Khóa duy nhất, format khuyến nghị:
                - Chat: 'CHAT_PEER:{user_id}:{lang}:{message_uuid}'
                - Study: 'STUDY_SESSION:{user_id}:{lang}:{session_uuid}'
        
        Returns: {
            'level_before', 'level_after', 'exp_before', 'exp_after',
            'leveled_up': bool, 'levels_gained': int,
            'rewards_granted': list[dict],
            'already_processed': bool
        }
        """
        # ── Lớp 2: DB Idempotency Check ──
        if idempotency_key:
            existing = EXPTransaction.objects.filter(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                logger.warning(
                    f"Idempotency hit: EXP transaction '{idempotency_key}' "
                    f"already processed (txn_id={existing.id})"
                )
                return {
                    'level_before': existing.level_before,
                    'level_after': existing.level_after,
                    'exp_before': existing.exp_before,
                    'exp_after': existing.exp_after,
                    'leveled_up': existing.level_after > existing.level_before,
                    'levels_gained': existing.level_after - existing.level_before,
                    'rewards_granted': [],
                    'already_processed': True,
                }
        
        # Lock row
        level_obj, _ = UserLanguageLevel.objects.get_or_create(user=user, lang=lang)
        level_obj = UserLanguageLevel.objects.select_for_update().get(id=level_obj.id)
        
        level_before = level_obj.level
        exp_before = level_obj.current_exp
        
        new_exp = level_obj.current_exp + amount
        
        # Clamp: không cho EXP xuống dưới 0 tại level hiện tại
        if new_exp < 0:
            new_exp = 0
        
        # Level up loop
        levels_gained = 0
        while new_exp >= LevelingService.exp_required_for_level(level_obj.level):
            new_exp -= LevelingService.exp_required_for_level(level_obj.level)
            level_obj.level += 1
            levels_gained += 1
        
        level_obj.current_exp = new_exp
        if amount > 0:
            level_obj.total_exp += amount
        level_obj.save()
        
        # Audit trail (unique key đảm bảo IntegrityError nếu duplicate lọt qua)
        try:
            EXPTransaction.objects.create(
                user=user, lang=lang, source_type=source_type,
                amount=amount,
                level_before=level_before, level_after=level_obj.level,
                exp_before=exp_before, exp_after=new_exp,
                idempotency_key=idempotency_key,
                reference_id=reference_id, note=note
            )
        except IntegrityError:
            # Race condition: task chạy song song vừa insert trước
            logger.error(
                f"IntegrityError on idempotency_key '{idempotency_key}'. "
                f"Concurrent duplicate detected — rolling back."
            )
            raise
        
        # Grant rewards cho các level vừa đạt (idempotent qua LevelRewardLog)
        rewards_granted = []
        if levels_gained > 0:
            for lv in range(level_before + 1, level_obj.level + 1):
                rewards = LevelingService._grant_level_rewards(user, lang, lv)
                rewards_granted.extend(rewards)

            # Phát quest action signal cho reach_level
            try:
                from .quest_signals import quest_action_signal
                quest_action_signal.send(
                    sender='reach_level',
                    user=user,
                    trigger_type='reach_level',
                    amount=level_obj.level,
                    lang=lang
                )
            except Exception as sig_err:
                logger.debug(f"Could not send reach_level quest signal: {sig_err}")
        
        return {
            'level_before': level_before,
            'level_after': level_obj.level,
            'exp_before': exp_before,
            'exp_after': new_exp,
            'leveled_up': levels_gained > 0,
            'levels_gained': levels_gained,
            'rewards_granted': rewards_granted,
            'already_processed': False,
        }

    @staticmethod
    def _grant_level_rewards(user, lang, level) -> list:
        """
        Phát phần thưởng cho mốc level cụ thể.
        
        Idempotent qua LevelRewardLog: mỗi (user, lang, level, rule)
        chỉ được grant đúng 1 lần. Nếu đã tồn tại → skip.
        """
        rules = RewardRule.objects.filter(
            required_level=level,
            lang__in=[lang, 'all'],
            is_active=True
        ).select_related('reward_item')
        
        granted = []
        for rule in rules:
            item = rule.reward_item
            if not item.is_active:
                continue
            
            # ── Lớp 3: LevelRewardLog Idempotency ──
            # Kiểm tra đã trao chưa — nếu rồi thì skip hoàn toàn
            _log, log_created = LevelRewardLog.objects.get_or_create(
                user=user, lang=lang, level=level, reward_rule=rule
            )
            if not log_created:
                logger.info(
                    f"Reward already granted: user={user.id}, "
                    f"lang={lang}, LV{level}, rule={rule.id}. Skipping."
                )
                continue
                
            # Upsert inventory
            inv, created = UserInventory.objects.get_or_create(
                user=user, reward_item=item,
                defaults={'quantity': rule.quantity, 'source_rule': rule}
            )
            if not created:
                inv.quantity += rule.quantity
                inv.save(update_fields=['quantity'])
            
            # Nếu là bonus_coins → cộng coin vào wallet (để ngỏ khả năng này cho tương lai, mặc dù seed data đã bỏ)
            if item.reward_type == 'bonus_coins' and item.coin_amount > 0:
                CoinService.earn_coins(
                    user, lang, item.coin_amount * rule.quantity,
                    reference_id=str(rule.id),
                    note=f'Level {level} reward: {item.name}'
                )
            
            granted.append({
                'reward_name': item.name,
                'reward_type': item.reward_type,
                'quantity': rule.quantity,
                'rarity': item.rarity,
                'image_url': item.image_url,
                'title_text': item.title_text,
            })
        
        return granted

    # ── Chat EXP Calculation ──
    @staticmethod
    def calculate_chat_exp(relation_type: str, is_reward: str, joy: float, sad: float) -> int:
        """
        Tính EXP từ 1 lần chat AI.
        
        Args:
            relation_type: 'peer'/'classmate'/'colleague'/'bestie'/'crush'/'master'/'professor'/'interviewer'
            is_reward: 'reward' (thưởng), 'punish' (phạt), 'neutral' (trung lập)
            joy: giá trị niềm vui hiện tại (0.0 - 1.0)
            sad: giá trị buồn bực hiện tại (0.0 - 1.0)
        
        Returns:
            Tổng EXP (có thể âm nếu bị phạt)
        """
        SUPERIOR_ROLES = {'master', 'professor', 'interviewer'}
        base_exp = 20 if relation_type in SUPERIOR_ROLES else 10
        
        bonus = 0
        if is_reward == 'reward':
            if joy == sad:
                bonus = 10  # Mặc định +10
            else:
                bonus = min(50, math.ceil(joy * 10 / max(sad, 0.1)))
        elif is_reward == 'punish':
            if joy == sad:
                bonus = -10  # Mặc định -10
            else:
                bonus = -min(30, math.ceil(sad * 10 / max(joy, 0.1)))
        # is_reward == 'neutral' → bonus = 0
        
        return base_exp + bonus

import uuid as uuid_mod
import logging
from django.db import transaction
from .models import CoinWallet, CoinTransaction, CoinConfig

logger = logging.getLogger(__name__)


class InsufficientCoinsError(Exception):
    """Raised khi user không đủ coin để thực hiện giao dịch."""
    pass


class CoinService:
    """
    Business logic layer cho mọi thao tác coin.
    
    Defensive Programming:
    - Mọi hàm dùng _get_wallet_for_update() nội bộ:
      1. get_or_create() → đảm bảo tồn tại (legacy user safe)
      2. select_for_update().get(id=) → lock row an toàn
    """

    @staticmethod
    def _get_wallet_for_update(user, lang: str) -> CoinWallet:
        """
        An toàn với legacy users: tạo ví nếu chưa tồn tại,
        rồi lock row để cập nhật.
        Phải gọi trong transaction.atomic() context.
        """
        wallet, _created = CoinWallet.objects.get_or_create(user=user, lang=lang)
        return CoinWallet.objects.select_for_update().get(id=wallet.id)

    @staticmethod
    def get_or_create_wallet(user, lang: str) -> CoinWallet:
        """Public helper — không lock, chỉ đảm bảo tồn tại."""
        wallet, _ = CoinWallet.objects.get_or_create(user=user, lang=lang)
        return wallet

    @staticmethod
    def get_balance(user, lang: str) -> dict:
        wallet = CoinService.get_or_create_wallet(user, lang)
        return {
            'paid': wallet.paid_balance,
            'free': wallet.free_balance,
            'total': wallet.total_balance,
        }

    @staticmethod
    def get_all_balances(user) -> dict:
        return {
            'zh': CoinService.get_balance(user, 'zh'),
            'en': CoinService.get_balance(user, 'en'),
        }

    # ────────────────── EARN ──────────────────

    @staticmethod
    @transaction.atomic
    def earn_coins(user, lang, amount, reference_id='', note='') -> tuple:
        """
        Kiếm coin từ học → cộng vào free_balance (tuân thủ giới hạn hàng ngày).
        Returns: (transaction_obj, coins_actually_earned, is_capped)
        """
        from django.core.cache import cache
        from django.db.models import Sum
        from django.utils import timezone

        # 1. Resolve daily limit based on user subscription tier
        user_tier = getattr(user.subscription, 'tier', 'Free') if hasattr(user, 'subscription') else 'Free'
        config = CoinConfig.objects.filter(tier=user_tier).first()
        limit = config.daily_free_earn_limit if config else 50  # default fallback if no config exists

        today_str = timezone.now().date().isoformat()
        redis_key = f"user:daily_earned:{user.id}:{lang}:{today_str}"
        is_capped = False
        coins_to_add = amount

        if limit > 0:
            # 2. Try fetching from Redis
            try:
                today_earned = cache.get(redis_key)
            except Exception as e:
                logger.warning(f"Failed to fetch daily coin counter from Redis: {e}")
                today_earned = None

            if today_earned is None:
                # Fallback to PostgreSQL
                logger.info(f"Redis cache miss for daily coin limit for user {user.id}. Querying DB...")
                db_sum = CoinTransaction.objects.filter(
                    user=user,
                    wallet__lang=lang,
                    transaction_type='EARN_STUDY',
                    created_at__date=timezone.now().date()
                ).aggregate(total=Sum('amount'))['total'] or 0
                today_earned = db_sum
                
                # Write back to Redis with 24 hours TTL
                try:
                    cache.set(redis_key, today_earned, timeout=86400)
                except Exception as e:
                    logger.warning(f"Failed to set daily coin counter to Redis: {e}")
            else:
                today_earned = int(today_earned)

            # Check if daily limit is reached/exceeded
            if today_earned >= limit:
                return None, 0, True

            allowed = limit - today_earned
            if amount >= allowed:
                coins_to_add = allowed
                is_capped = True
            else:
                coins_to_add = amount
                is_capped = False

        if coins_to_add <= 0:
            return None, 0, True

        wallet = CoinService._get_wallet_for_update(user, lang)
        wallet.free_balance += coins_to_add
        wallet.save(update_fields=['free_balance', 'updated_at'])

        txn = CoinTransaction.objects.create(
            wallet=wallet, user=user,
            transaction_type='EARN_STUDY', balance_type='free',
            amount=coins_to_add,
            paid_balance_after=wallet.paid_balance,
            free_balance_after=wallet.free_balance,
            reference_id=reference_id, note=note,
        )

        # 3. Increment Redis counter
        if limit > 0:
            try:
                cache.incrby(redis_key, coins_to_add)
            except Exception as e:
                # If incrby fails because of key expired or deleted between calls, set it
                try:
                    cache.set(redis_key, today_earned + coins_to_add, timeout=86400)
                except Exception as ex:
                    logger.warning(f"Failed to increment daily coin counter in Redis: {ex}")

        return txn, coins_to_add, is_capped

    # ────────────────── SPEND (Split-Aware Audit) ──────────────────

    @staticmethod
    @transaction.atomic
    def spend_coins(user, lang, amount, transaction_type,
                    reference_id='', note='') -> list:
        """
        Trừ coin: paid_balance trước → free_balance sau.
        
        Audit Trail: Tạo BẢN GHI TÁCH BIỆT cho từng nguồn cấp bị khấu trừ.
        - Nếu chỉ trừ paid → 1 record (balance_type='paid')
        - Nếu chỉ trừ free → 1 record (balance_type='free')
        - Nếu trừ cả 2   → 2 records, liên kết bằng group_id
        
        Raise InsufficientCoinsError nếu total_balance < amount.
        Returns: list[CoinTransaction] (1 hoặc 2 records)
        """
        wallet = CoinService._get_wallet_for_update(user, lang)

        if wallet.total_balance < amount:
            raise InsufficientCoinsError(
                f"Cần {amount} coin nhưng chỉ có {wallet.total_balance} "
                f"(paid={wallet.paid_balance}, free={wallet.free_balance})"
            )

        remaining = amount

        # 1. Tính toán khấu trừ từ paid_balance
        deduct_paid = min(wallet.paid_balance, remaining)
        remaining -= deduct_paid

        # 2. Tính toán khấu trừ từ free_balance
        deduct_free = remaining  # Phần còn lại sau khi trừ paid

        # 3. Cập nhật wallet
        wallet.paid_balance -= deduct_paid
        wallet.free_balance -= deduct_free
        wallet.save(update_fields=['paid_balance', 'free_balance', 'updated_at'])

        # 4. Ghi nhật ký tách biệt — group_id chung cho cùng 1 giao dịch logic
        group_id = uuid_mod.uuid4()
        transactions = []

        if deduct_paid > 0:
            transactions.append(CoinTransaction.objects.create(
                group_id=group_id,
                wallet=wallet, user=user,
                transaction_type=transaction_type, balance_type='paid',
                amount=-deduct_paid,
                paid_balance_after=wallet.paid_balance,
                free_balance_after=wallet.free_balance,
                reference_id=reference_id, note=note,
            ))

        if deduct_free > 0:
            transactions.append(CoinTransaction.objects.create(
                group_id=group_id,
                wallet=wallet, user=user,
                transaction_type=transaction_type, balance_type='free',
                amount=-deduct_free,
                paid_balance_after=wallet.paid_balance,
                free_balance_after=wallet.free_balance,
                reference_id=reference_id, note=note,
            ))

        return transactions

    # ────────────────── REFUND ──────────────────

    @staticmethod
    @transaction.atomic
    def refund_coins(user, lang, amount, reference_id='', note='') -> CoinTransaction:
        """Hoàn trả coin → paid_balance."""
        wallet = CoinService._get_wallet_for_update(user, lang)
        wallet.paid_balance += amount
        wallet.save(update_fields=['paid_balance', 'updated_at'])

        return CoinTransaction.objects.create(
            wallet=wallet, user=user,
            transaction_type='REFUND', balance_type='paid',
            amount=amount,
            paid_balance_after=wallet.paid_balance,
            free_balance_after=wallet.free_balance,
            reference_id=reference_id, note=note,
        )

    # ────────────────── WEEKLY REFILL (Worker) ──────────────────

    @staticmethod
    @transaction.atomic
    def apply_weekly_refill_for_wallet(user, lang, tier: str) -> CoinTransaction | None:
        """
        Hồi paid_balance lên cap cho 1 ví cụ thể (1 user + 1 lang).
        Được gọi bởi Worker sub-task, KHÔNG phải Master task.
        """
        config = CoinConfig.objects.filter(tier=tier).first()
        if not config or config.weekly_refill_cap <= 0:
            return None

        wallet = CoinService._get_wallet_for_update(user, lang)

        if wallet.paid_balance >= config.weekly_refill_cap:
            return None  # Đã đạt hoặc vượt cap → skip

        refill_amount = config.weekly_refill_cap - wallet.paid_balance
        wallet.paid_balance = config.weekly_refill_cap
        wallet.save(update_fields=['paid_balance', 'updated_at'])

        return CoinTransaction.objects.create(
            wallet=wallet, user=user,
            transaction_type='WEEKLY_REFILL', balance_type='paid',
            amount=refill_amount,
            paid_balance_after=wallet.paid_balance,
            free_balance_after=wallet.free_balance,
            note=f'Weekly refill for {tier} (cap={config.weekly_refill_cap})',
        )

    # ────────────────── TIER RESET ──────────────────

    @staticmethod
    @transaction.atomic
    def apply_tier_reset_for_wallet(user, lang, new_tier='Free'):
        """
        Reset paid_balance về cap của tier mới cho 1 ví cụ thể.
        free_balance giữ nguyên.
        """
        config = CoinConfig.objects.filter(tier=new_tier).first()
        cap = config.weekly_refill_cap if config else 5

        wallet = CoinService._get_wallet_for_update(user, lang)

        old_paid = wallet.paid_balance
        wallet.paid_balance = cap
        wallet.save(update_fields=['paid_balance', 'updated_at'])

        if old_paid != cap:
            CoinTransaction.objects.create(
                wallet=wallet, user=user,
                transaction_type='TIER_RESET', balance_type='paid',
                amount=cap - old_paid,
                paid_balance_after=wallet.paid_balance,
                free_balance_after=wallet.free_balance,
                note=f'Tier reset to {new_tier} (paid: {old_paid} → {cap})',
            )

    @staticmethod
    def apply_tier_reset(user, new_tier='Free'):
        """Reset cả 2 ví."""
        for lang in ['zh', 'en']:
            CoinService.apply_tier_reset_for_wallet(user, lang, new_tier)

    # ────────────────── PURCHASE ──────────────────

    @staticmethod
    @transaction.atomic
    def add_purchased_coins(user, lang, amount, reference_id='') -> CoinTransaction:
        """Cộng coin mua bằng tiền → paid_balance."""
        wallet = CoinService._get_wallet_for_update(user, lang)
        wallet.paid_balance += amount
        wallet.save(update_fields=['paid_balance', 'updated_at'])

        return CoinTransaction.objects.create(
            wallet=wallet, user=user,
            transaction_type='PURCHASE', balance_type='paid',
            amount=amount,
            paid_balance_after=wallet.paid_balance,
            free_balance_after=wallet.free_balance,
            reference_id=reference_id,
            note=f'Purchased {amount} coins',
        )

    @staticmethod
    @transaction.atomic
    def apply_initial_coins(user, tier: str) -> list:
        """
        Cấp coin khởi tạo tương ứng với tier cho user mới.
        Nếu ví của user đã có số dư paid lớn hơn hoặc bằng mức khởi tạo, ta skip hoặc chỉ bù phần thiếu.
        """
        config = CoinConfig.objects.filter(tier=tier).first()
        if not config:
            return []

        transactions = []
        for lang in ['zh', 'en']:
            initial_amount = config.initial_coins_zh if lang == 'zh' else config.initial_coins_en
            if initial_amount <= 0:
                continue

            wallet = CoinService._get_wallet_for_update(user, lang)
            old_paid = wallet.paid_balance
            
            # Chỉ nạp thêm phần chênh lệch nếu số coin khởi tạo lớn hơn số paid hiện tại
            diff = initial_amount - old_paid
            if diff <= 0:
                continue

            wallet.paid_balance = initial_amount
            wallet.save(update_fields=['paid_balance', 'updated_at'])

            txn = CoinTransaction.objects.create(
                wallet=wallet,
                user=user,
                transaction_type='ADMIN_ADJUST',
                balance_type='paid',
                amount=diff,
                paid_balance_after=wallet.paid_balance,
                free_balance_after=wallet.free_balance,
                note=f"Cấp Linh Thạch/Coin khởi tạo cho tài khoản mới (Gói {tier})"
            )
            transactions.append(txn)

        return transactions

    # ────────────────── HELPERS ──────────────────

    @staticmethod
    def calculate_session_coins(memorized_count, words_per_coin=5) -> int:
        return memorized_count // words_per_coin

    @staticmethod
    def get_coin_config(tier='Free') -> CoinConfig | None:
        return CoinConfig.objects.filter(tier=tier).first()

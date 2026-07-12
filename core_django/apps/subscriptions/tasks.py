import logging
from celery import shared_task
from django.utils import timezone
from django.db import transaction
from .models import UserSubscription, SubscriptionPlan, PaymentOrder

logger = logging.getLogger(__name__)

@shared_task
def process_expired_subscriptions():
    """
    Quét và xử lý các gói đăng ký đã hết hạn (loại trừ Premium):
    - Nếu có pending_downgrade_tier: chuyển sang gói đó.
      + Nếu là Free -> set is_active=False.
      + Nếu là Plus/Pro -> set is_active=True và gia hạn 30 ngày (mock payment thành công).
    - Nếu không có pending_downgrade_tier: chuyển về Free, set is_active=False.
    """
    now = timezone.now()
    expired_subs = UserSubscription.objects.exclude(tier='Premium').filter(end_date__lt=now)
    count = 0

    for sub in expired_subs.iterator(chunk_size=500):
        with transaction.atomic():
            # Khóa PostgreSQL row
            try:
                locked_sub = UserSubscription.objects.select_for_update().get(pk=sub.pk)
            except UserSubscription.DoesNotExist:
                continue

            if locked_sub.tier != 'Premium' and locked_sub.end_date and locked_sub.end_date < now:
                old_tier = locked_sub.tier
                locked_sub.tier = 'Free'
                locked_sub.is_active = False
                locked_sub.end_date = None
                locked_sub.price = 0
                locked_sub.vat = 0
                locked_sub.pending_downgrade_tier = None
                logger.info(f"Subscription expired and downgraded to Free for user {locked_sub.user.username}: {old_tier} -> Free")

                locked_sub.save()
                count += 1

    return f"Processed {count} expired subscriptions."


@shared_task
def expire_pending_payment_orders():
    """
    Quét và đánh dấu EXPIRED cho các PaymentOrder PENDING đã quá hạn.
    Chạy mỗi 5 phút qua Celery Beat.
    """
    now = timezone.now()
    expired_count = PaymentOrder.objects.filter(
        status='PENDING',
        expires_at__lt=now,
    ).update(status='EXPIRED')

    if expired_count > 0:
        logger.info(f"Expired {expired_count} pending payment orders.")

    return f"Expired {expired_count} pending payment orders."


@shared_task
def notify_payment_success_task(user_id, order_id, target_tier):
    """
    Gửi thông báo nâng cấp gói thành công tới client qua WebSocket (chạy ngầm).
    """
    from core_project.ws_utils import ws_notify
    ws_notify(
        user_id=user_id,
        event_type="subscription_change",
        title=f"Chúc mừng! Bạn đã nâng cấp thành công gói {target_tier.upper()}.",
        payload={
            "order_id": str(order_id),
            "status": "PAID",
            "tier": target_tier
        },
        persist=True
    )


@shared_task(bind=True, max_retries=5, default_retry_delay=3)
def send_welcome_pro_gift_notification(self, user_id):
    """
    Gửi thông báo chào mừng dùng thử gói Pro 3 ngày cho user mới (chạy ngầm).
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        # Check if user exists to handle replication lag / DB delay
        if not User.objects.filter(id=user_id).exists():
            raise User.DoesNotExist(f"User with ID {user_id} not found in database yet.")
        
        from core_project.ws_utils import ws_notify
        ws_notify(
            user_id=user_id,
            event_type="subscription_change",
            title="Cảm ơn bạn đã đăng ký sử dụng, chúng tôi xin gửi tặng bạn 3 ngày trải nghiệm miễn phí các tính năng trả phí của hệ thống",
            payload={
                "tier": "Pro",
                "days": 3
            },
            persist=True
        )
        logger.info(f"Successfully sent welcome pro gift notification to user {user_id}")
    except Exception as exc:
        logger.warning(f"Failed to send welcome pro gift notification for user {user_id}: {exc}. Retrying...")
        raise self.retry(exc=exc)

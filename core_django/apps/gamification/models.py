import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone

class UserStreak(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='streak')
    current_streak = models.IntegerField(default=0)
    max_streak = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} - Streak: {self.current_streak}"

class DailyTarget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='daily_target')
    target_words = models.IntegerField(default=10)
    target_duration = models.IntegerField(default=15) # in minutes
    target_type = models.CharField(max_length=50, default='words') # 'words' or 'duration'

    def __str__(self):
        return f"{self.user.username} Target: {self.target_words} words"

class StudyHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='study_histories')
    study_date = models.DateField(default=timezone.now)
    vocabulary_learned = models.IntegerField(default=0)
    pronunciation_accuracy = models.FloatField(default=0.0)
    study_duration_seconds = models.IntegerField(default=0)

    class Meta:
        unique_together = ('user', 'study_date')

    def __str__(self):
        return f"{self.user.username} - {self.study_date}"

class DailyActivity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='daily_activities')
    activity_date = models.DateField(default=timezone.now)
    is_target_met = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'activity_date')

    def __str__(self):
        return f"{self.user.username} - {self.activity_date} - Met: {self.is_target_met}"


class CoinWallet(models.Model):
    """
    Ví điểm thưởng theo ngôn ngữ, phân tách paid/free.
    - paid_balance: refill hàng tuần + mua bằng tiền → trừ TRƯỚC
    - free_balance: kiếm từ học flashcard → trừ SAU
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='coin_wallets')
    lang = models.CharField(max_length=10, choices=[('zh', 'Linh Thạch'), ('en', 'Coin')])
    paid_balance = models.IntegerField(default=0, help_text="Coin refill/mua — trừ trước")
    free_balance = models.IntegerField(default=0, help_text="Coin kiếm từ học — trừ sau")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'lang')

    @property
    def total_balance(self):
        return self.paid_balance + self.free_balance

    def __str__(self):
        label = "Linh Thạch" if self.lang == "zh" else "Coin"
        return f"{self.user.username} - {label}: paid={self.paid_balance}, free={self.free_balance}"


class CoinTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('EARN_STUDY', 'Kiếm từ học flashcard'),
        ('SPEND_CHAT_CREATE', 'Tạo AI Persona'),
        ('SPEND_CHAT_MSG', 'Gửi tin nhắn AI Chat'),
        ('REFUND', 'Hoàn trả do lỗi'),
        ('WEEKLY_REFILL', 'Hồi điểm hàng tuần'),
        ('ADMIN_ADJUST', 'Admin điều chỉnh'),
        ('PURCHASE', 'Mua bằng tiền'),
        ('TIER_RESET', 'Reset khi hết hạn subscription'),
    ]
    BALANCE_TYPES = [('paid', 'Paid'), ('free', 'Free')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_id = models.UUIDField(default=uuid.uuid4, db_index=True,
                                help_text="Liên kết các bản ghi thuộc cùng 1 giao dịch logic (split spend)")
    wallet = models.ForeignKey(CoinWallet, on_delete=models.CASCADE, related_name='transactions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    balance_type = models.CharField(max_length=10, choices=BALANCE_TYPES,
                                     help_text="Nguồn cấp thực tế bị tác động")
    amount = models.IntegerField(help_text="Dương = cộng, Âm = trừ. Giá trị chính xác theo balance_type")
    paid_balance_after = models.IntegerField(help_text="Snapshot paid_balance sau giao dịch")
    free_balance_after = models.IntegerField(help_text="Snapshot free_balance sau giao dịch")
    reference_id = models.CharField(max_length=255, blank=True, default='')
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['wallet', 'created_at']),
            models.Index(fields=['group_id']),
        ]


from apps.subscriptions.models import SubscriptionPlan

class CoinConfig(models.Model):
    """Admin-configurable coin settings per subscription tier."""
    tier = models.CharField(
        max_length=20,
        unique=True,
        choices=SubscriptionPlan.TIER_CHOICES,
        help_text="Gói đăng ký tương ứng"
    )
    weekly_refill_cap = models.IntegerField(default=0, help_text="Mức hồi paid_balance tối đa mỗi tuần")
    initial_coins_zh = models.IntegerField(default=0, help_text="Linh Thạch khởi tạo (paid) cho user mới")
    initial_coins_en = models.IntegerField(default=0, help_text="Coin EN khởi tạo (paid) cho user mới")
    words_per_coin = models.IntegerField(default=5, help_text="Số từ thuộc = 1 coin (free)")
    daily_free_earn_limit = models.IntegerField(default=50, help_text="Giới hạn số coin free tối đa có thể kiếm mỗi ngày (0 = không giới hạn)")
    chat_create_cost = models.IntegerField(default=5, help_text="Chi phí tạo AI Persona")
    chat_message_cost = models.IntegerField(default=1, help_text="Chi phí gửi tin nhắn AI")

    def __str__(self):
        return f"CoinConfig({self.tier}): refill={self.weekly_refill_cap}"


class StudySession(models.Model):
    STATUS_CHOICES = [
        ('IN_PROGRESS', 'Đang học'),
        ('FINISHED', 'Hoàn thành'),
        ('ABANDONED', 'Bỏ dở'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='study_sessions')
    lang = models.CharField(max_length=10)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='IN_PROGRESS')
    total_cards = models.IntegerField(default=0)
    memorized_count = models.IntegerField(default=0)
    coins_earned = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class StudySessionCard(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Chưa lật'),
        ('memorized', 'Đã thuộc'),
        ('skipped', 'Bỏ qua'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(StudySession, on_delete=models.CASCADE, related_name='session_cards')
    card_id = models.UUIDField(help_text="FK tới FlashcardExercise.id")
    word = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'card_id')


class CoinPurchaseOrder(models.Model):
    """Đơn mua coin qua SePay, tương tự PaymentOrder của subscription."""
    STATUS_CHOICES = [
        ('PENDING', 'Chờ thanh toán'),
        ('PAID', 'Đã thanh toán'),
        ('EXPIRED', 'Hết hạn'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='coin_purchase_orders')
    lang = models.CharField(max_length=10, choices=[('zh', 'Linh Thạch'), ('en', 'Coin')])
    coin_amount = models.IntegerField(help_text="Số coin sẽ nhận")
    price = models.DecimalField(max_digits=12, decimal_places=0, help_text="Số tiền VNĐ")
    order_code = models.CharField(max_length=50, unique=True, db_index=True)
    transfer_content = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    sepay_transaction_id = models.CharField(max_length=100, blank=True, default='')
    bank_reference = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    paid_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_expired(self):
        return self.status == 'PENDING' and timezone.now() > self.expires_at


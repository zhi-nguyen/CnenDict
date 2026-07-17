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
        ('SPEND_WRITING_PRACTICE', 'Luyện viết AI'),
        ('SPEND_PDF_EXPORT', 'Xuất PDF quá hạn mức'),
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
    writing_base_cost_zh = models.IntegerField(default=1, help_text="Chi phí Linh Thạch nền cho Luyện Viết tiếng Trung")
    writing_increment_cost_zh = models.IntegerField(default=1, help_text="Chi phí Linh Thạch tăng thêm cho mỗi 50 chữ tiếp theo")
    writing_base_cost_en = models.IntegerField(default=1, help_text="Chi phí Coin nền cho Luyện Viết tiếng Anh")
    writing_increment_cost_en = models.IntegerField(default=1, help_text="Chi phí Coin tăng thêm cho mỗi 50 từ tiếp theo")
    pdf_normal_export_cost = models.IntegerField(default=2, help_text="Chi phí Linh Thạch cho xuất PDF thường khi quá hạn")
    pdf_stroke_export_cost = models.IntegerField(default=3, help_text="Chi phí Linh Thạch cho xuất PDF phân rã nét khi quá hạn")

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


class UserLanguageLevel(models.Model):
    """
    EXP & Level theo ngôn ngữ cho mỗi user.
    Mỗi user có 1 record cho mỗi ngôn ngữ (zh, en).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='language_levels')
    lang = models.CharField(max_length=10, choices=[('zh', 'Tiếng Trung'), ('en', 'Tiếng Anh')])
    level = models.IntegerField(default=1)
    current_exp = models.IntegerField(default=0, help_text="EXP tích lũy trong level hiện tại")
    total_exp = models.IntegerField(default=0, help_text="Tổng EXP tích lũy từ đầu (không bao giờ giảm)")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'lang')
        indexes = [
            models.Index(fields=['user', 'lang']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.lang} LV{self.level} (EXP: {self.current_exp})"


class EXPTransaction(models.Model):
    """Audit trail cho mọi thay đổi EXP."""
    SOURCE_TYPES = [
        ('STUDY_SESSION', 'Hoàn thành lật thẻ flashcard'),
        ('CHAT_PEER', 'Chat AI đồng cấp'),
        ('CHAT_SUPERIOR', 'Chat AI cấp trên'),
        ('CHAT_REWARD', 'Thưởng từ chat'),
        ('CHAT_PUNISH', 'Phạt từ chat'),
        ('ADMIN_ADJUST', 'Admin điều chỉnh'),
        ('QUEST_COMPLETE', 'Hoàn thành nhiệm vụ'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    lang = models.CharField(max_length=10)
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPES)
    amount = models.IntegerField(help_text="Dương = cộng EXP, Âm = trừ EXP")
    level_before = models.IntegerField()
    level_after = models.IntegerField()
    exp_before = models.IntegerField(help_text="current_exp trước giao dịch")
    exp_after = models.IntegerField(help_text="current_exp sau giao dịch")
    idempotency_key = models.CharField(
        max_length=255, unique=True, null=True, blank=True,
        help_text="Khóa duy nhất đảm bảo mỗi giao dịch EXP chỉ được xử lý 1 lần. "
                  "Format: '{source_type}:{user_id}:{lang}:{message_id_or_date}'"
    )
    reference_id = models.CharField(max_length=255, blank=True, default='')
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'lang', 'created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['idempotency_key'],
                name='uq_exp_transaction_idempotency',
                condition=models.Q(idempotency_key__isnull=False),
            )
        ]


class RewardItem(models.Model):
    """Danh mục vật phẩm phần thưởng — Admin quản lý."""
    REWARD_TYPES = [
        ('avatar_frame', 'Khung Avatar'),
        ('title', 'Danh hiệu'),
        ('bonus_coins', 'Điểm thưởng (Coin)'),
        ('item', 'Vật phẩm Cosmetic'),
        ('badge', 'Huy hiệu'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, help_text="Tên hiển thị (VD: 'Khung Hỏa Diệm')")
    reward_type = models.CharField(max_length=20, choices=REWARD_TYPES)
    description = models.TextField(blank=True, default='')
    
    # Data payload tùy loại
    image_url = models.CharField(max_length=500, blank=True, default='', help_text="URL hoặc đường dẫn ảnh cho khung/badge/item")
    title_text = models.CharField(max_length=100, blank=True, default='', help_text="Text danh hiệu nếu type=title")
    coin_amount = models.IntegerField(default=0, help_text="Số coin thưởng nếu type=bonus_coins")
    
    # Metadata
    rarity = models.CharField(max_length=20, default='common', choices=[
        ('common', 'Phổ thông'),
        ('rare', 'Hiếm'),
        ('epic', 'Sử thi'),
        ('legendary', 'Huyền thoại'),
    ])
    ui_metadata = models.JSONField(default=dict, blank=True, help_text="Cấu hình hiển thị động ở Frontend")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.get_reward_type_display()}] {self.name} ({self.rarity})"


class RewardRule(models.Model):
    """
    Quy tắc thưởng khi user đạt mốc level.
    Admin tạo rule: "Khi đạt LV 5 ngôn ngữ zh → nhận RewardItem X".
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lang = models.CharField(max_length=10, choices=[('zh', 'Tiếng Trung'), ('en', 'Tiếng Anh'), ('all', 'Tất cả')])
    required_level = models.IntegerField(help_text="Level cần đạt để nhận phần thưởng")
    reward_item = models.ForeignKey(RewardItem, on_delete=models.CASCADE, related_name='rules')
    quantity = models.IntegerField(default=1, help_text="Số lượng vật phẩm thưởng")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('lang', 'required_level', 'reward_item')
        ordering = ['lang', 'required_level']

    def __str__(self):
        return f"LV{self.required_level} ({self.lang}) → {self.reward_item.name} x{self.quantity}"


class UserInventory(models.Model):
    """Kho vật phẩm đã nhận của user."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='inventory')
    reward_item = models.ForeignKey(RewardItem, on_delete=models.CASCADE, related_name='user_inventories')
    quantity = models.IntegerField(default=1)
    is_equipped = models.BooleanField(default=False, help_text="Đang trang bị/sử dụng")
    acquired_at = models.DateTimeField(auto_now_add=True)
    source_rule = models.ForeignKey(RewardRule, on_delete=models.SET_NULL, null=True, blank=True,
                                     help_text="Rule đã grant vật phẩm này")

    class Meta:
        indexes = [
            models.Index(fields=['user', 'reward_item']),
        ]

    def __str__(self):
        equipped = " [EQUIPPED]" if self.is_equipped else ""
        return f"{self.user.username} - {self.reward_item.name} x{self.quantity}{equipped}"


class LevelRewardLog(models.Model):
    """
    Ghi nhận phần thưởng ĐÃ PHÁT cho mỗi (user, lang, level, rule).
    Dùng unique_together để đảm bảo không bao giờ trao trùng,
    kể cả khi Celery Worker retry task nhiều lần.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='level_reward_logs')
    lang = models.CharField(max_length=10)
    level = models.IntegerField(help_text="Level tại thời điểm nhận thưởng")
    reward_rule = models.ForeignKey(RewardRule, on_delete=models.CASCADE)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'lang', 'level', 'reward_rule')
        indexes = [
            models.Index(fields=['user', 'lang', 'level']),
        ]

    def __str__(self):
        return f"{self.user.username} - LV{self.level} ({self.lang}) - {self.reward_rule}"



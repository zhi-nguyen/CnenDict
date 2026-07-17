import uuid
from django.db import models
from django.conf import settings

class LeaderboardSnapshot(models.Model):
    """Snapshot bảng xếp hạng, tạo mới mỗi 4 tiếng bởi Celery"""
    BOARD_TYPES = [
        ('coin_paid', 'Xếp hạng Coin/Linh Thạch (Paid)'),
        ('coin_free', 'Xếp hạng Coin/Linh Thạch (Free)'),
        ('total_likes', 'Xếp hạng Like'),
        ('weekly_words', 'Xếp hạng Từ thuộc tuần'),
        ('max_streak', 'Xếp hạng Streak'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board_type = models.CharField(max_length=20, choices=BOARD_TYPES)
    lang = models.CharField(max_length=10, choices=[('zh', 'Chinese'), ('en', 'English')])
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)  # Thời điểm snapshot

    class Meta:
        db_table = 'leaderboard_snapshot'
        indexes = [
            models.Index(fields=['board_type', 'lang', '-created_at']),
        ]

    def __str__(self):
        return f"{self.board_type} - {self.lang} snapshot at {self.created_at}"


class LeaderboardEntry(models.Model):
    """Từng dòng xếp hạng trong một snapshot"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snapshot = models.ForeignKey(LeaderboardSnapshot, on_delete=models.CASCADE, related_name='entries')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leaderboard_entries')
    rank = models.IntegerField()
    score = models.BigIntegerField()  # Giá trị dùng để xếp hạng
    username = models.CharField(max_length=150)  # Denormalized để tránh query JOIN khi hiển thị
    avatar_url = models.CharField(max_length=500, blank=True, default='') # Denormalized

    class Meta:
        db_table = 'leaderboard_entry'
        ordering = ['rank']
        unique_together = ('snapshot', 'user')
        indexes = [
            models.Index(fields=['snapshot', 'rank']),
        ]

    def __str__(self):
        return f"#{self.rank} - {self.username} (Score: {self.score}) in {self.snapshot.id}"

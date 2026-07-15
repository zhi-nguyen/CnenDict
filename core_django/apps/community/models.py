import uuid
from django.db import models
from django.conf import settings

# ═══════════════════════════════════════════
#  MODULE 1: WORD COMMENT SYSTEM
# ═══════════════════════════════════════════

class WordComment(models.Model):
    """Bình luận trên 1 từ trong hệ thống dictionary (ZhWord hoặc EnWord)"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='word_comments')
    word_id = models.UUIDField(db_index=True)         # ID của ZhWord hoặc EnWord
    lang = models.CharField(max_length=10, choices=[('zh', 'Chinese'), ('en', 'English')])
    content = models.TextField(max_length=500)
    upvotes = models.IntegerField(default=0)     # Denormalized count
    downvotes = models.IntegerField(default=0)   # Denormalized count
    score = models.IntegerField(default=0, db_index=True)  # score = upvotes - downvotes
    is_hidden = models.BooleanField(default=False)  # Bị ẩn khi bị >= 5 reports
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'community_wordcomment'
        unique_together = ('user', 'word_id', 'lang') # Mỗi user chỉ có 1 comment trên mỗi từ
        indexes = [
            models.Index(fields=['user', 'lang', '-created_at']),
            models.Index(fields=['word_id', 'lang', '-score']),
        ]

    def __str__(self):
        return f"{self.user.username} on word {self.word_id} ({self.lang}): {self.score}"


class WordCommentVote(models.Model):
    """Upvote hoặc Downvote trên WordComment"""
    VOTE_CHOICES = [
        (1, 'Upvote'),
        (-1, 'Downvote'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='word_comment_votes')
    comment = models.ForeignKey(WordComment, on_delete=models.CASCADE, related_name='votes')
    vote = models.SmallIntegerField(choices=VOTE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'community_wordcommentvote'
        unique_together = ('user', 'comment') # 1 vote/user/comment

    def __str__(self):
        vote_label = "Up" if self.vote == 1 else "Down"
        return f"{self.user.username} {vote_label} voted on comment {self.comment.id}"


# ═══════════════════════════════════════════
#  MODULE 2: FORUM / POST SYSTEM
# ═══════════════════════════════════════════

class ForumPost(models.Model):
    """Bài đăng/topic trong diễn đàn cộng đồng"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='forum_posts')
    lang = models.CharField(max_length=10, choices=[('zh', 'Chinese'), ('en', 'English')], db_index=True)
    content = models.TextField(max_length=2000)
    image_url = models.URLField(max_length=500, blank=True, default='') # Tối đa 1 ảnh (đường dẫn GCS permanent)
    like_count = models.IntegerField(default=0)  # Denormalized
    comment_count = models.IntegerField(default=0)  # Denormalized
    is_hidden = models.BooleanField(default=False, db_index=True) # Bị ẩn khi >= 5 reports
    is_pinned = models.BooleanField(default=False, db_index=True) # Ghim bài
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'community_forumpost'
        ordering = ['-is_pinned', '-created_at']

    def __str__(self):
        return f"Post by {self.author.username} ({self.lang}): {self.content[:30]}..."


class PostLike(models.Model):
    """Like bài viết"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='post_likes')
    post = models.ForeignKey(ForumPost, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'community_postlike'
        unique_together = ('user', 'post')

    def __str__(self):
        return f"{self.user.username} liked post {self.post.id}"


class PostComment(models.Model):
    """Bình luận trên bài đăng diễn đàn"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='post_comments')
    post = models.ForeignKey(ForumPost, on_delete=models.CASCADE, related_name='comments')
    content = models.TextField(max_length=1000)
    like_count = models.IntegerField(default=0)  # Denormalized
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'community_postcomment'
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.user.username} on post {self.post.id}"


class PostCommentLike(models.Model):
    """Like bình luận trên bài đăng diễn đàn"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comment_likes')
    comment = models.ForeignKey(PostComment, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'community_postcommentlike'
        unique_together = ('user', 'comment')

    def __str__(self):
        return f"{self.user.username} liked comment {self.comment.id}"


class PostBookmark(models.Model):
    """Lưu bài viết diễn đàn"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='post_bookmarks')
    post = models.ForeignKey(ForumPost, on_delete=models.CASCADE, related_name='bookmarks')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'community_postbookmark'
        unique_together = ('user', 'post')

    def __str__(self):
        return f"{self.user.username} bookmarked post {self.post.id}"


# ═══════════════════════════════════════════
#  MODULE 3: COMMUNITY REPORT SYSTEM
# ═══════════════════════════════════════════

class CommunityReport(models.Model):
    """Báo cáo bài viết hoặc bình luận độc hại"""
    CONTENT_TYPE_CHOICES = [
        ('post', 'Forum Post'),
        ('post_comment', 'Post Comment'),
        ('word_comment', 'Word Comment'),
    ]
    REASON_CHOICES = [
        ('spam', 'Spam / Quảng cáo'),
        ('harassment', 'Quấy rối / Bắt nạt'),
        ('inappropriate', 'Nội dung không phù hợp'),
        ('misinformation', 'Thông tin sai lệch'),
        ('other', 'Lý do khác'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_reports')
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES)
    object_id = models.UUIDField(db_index=True)  # ID của post/comment bị báo cáo
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    detail = models.TextField(blank=True, max_length=500, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'community_report'
        unique_together = ('reporter', 'content_type', 'object_id') # 1 report/user/target
        indexes = [
            models.Index(fields=['content_type', 'object_id', 'created_at']),
        ]

    def __str__(self):
        return f"Report by {self.reporter.username} on {self.content_type} {self.object_id}"


class CommunityAppeal(models.Model):
    """Khiếu nại khi bài viết hoặc bình luận bị ẩn tự động"""
    STATUS_CHOICES = [
        ('pending', 'Chờ xử lý'),
        ('approved', 'Chấp nhận (Phục hồi)'),
        ('rejected', 'Từ chối (Giữ ẩn)'),
    ]
    CONTENT_TYPE_CHOICES = [
        ('post', 'Forum Post'),
        ('post_comment', 'Post Comment'),
        ('word_comment', 'Word Comment'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_appeals') # Chủ nội dung
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES)
    object_id = models.UUIDField(db_index=True)
    reason = models.TextField(max_length=1000) # Lý do khiếu nại
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    admin_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'community_appeal'
        unique_together = ('user', 'content_type', 'object_id')

    def __str__(self):
        return f"Appeal by {self.user.username} on {self.content_type} {self.object_id} ({self.status})"

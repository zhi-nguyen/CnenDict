import logging
from django.db import models
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from google.cloud import storage

from .models import CommunityReport, ForumPost, PostComment, PostLike, WordCommentVote, WordComment
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)

@receiver(post_save, sender=CommunityReport)
def check_report_threshold(sender, instance, created, **kwargs):
    """
    Khi có report mới, kiểm tra xem nội dung bị báo cáo đã nhận đủ 5 reports
    từ 5 người dùng khác nhau trong vòng 24 giờ chưa.
    Nếu đủ, ẩn nội dung đó (is_hidden = True) và gửi notification cho chủ sở hữu.
    """
    if not created:
        return

    content_type = instance.content_type
    object_id = instance.object_id
    time_threshold = timezone.now() - timedelta(days=1)

    # Đếm số report duy nhất từ các users khác nhau trong 24h qua
    reports_count = CommunityReport.objects.filter(
        content_type=content_type,
        object_id=object_id,
        created_at__gte=time_threshold
    ).values('reporter').distinct().count()

    if reports_count >= 5:
        target_owner = None
        title = ""
        content_preview = ""

        if content_type == 'post':
            try:
                post = ForumPost.objects.get(pk=object_id)
                if not post.is_hidden:
                    post.is_hidden = True
                    post.save(update_fields=['is_hidden'])
                    target_owner = post.author
                    title = "Bài viết của bạn đã bị ẩn"
                    content_preview = post.content[:50]
            except ForumPost.DoesNotExist:
                pass

        elif content_type == 'post_comment':
            try:
                comment = PostComment.objects.get(pk=object_id)
                if not comment.is_hidden:
                    comment.is_hidden = True
                    comment.save(update_fields=['is_hidden'])
                    target_owner = comment.user
                    title = "Bình luận của bạn đã bị ẩn"
                    content_preview = comment.content[:50]
            except PostComment.DoesNotExist:
                pass

        elif content_type == 'word_comment':
            try:
                comment = WordComment.objects.get(pk=object_id)
                if not comment.is_hidden:
                    comment.is_hidden = True
                    comment.save(update_fields=['is_hidden'])
                    target_owner = comment.user
                    title = "Bình luận từ vựng của bạn đã bị ẩn"
                    content_preview = comment.content[:50]
            except WordComment.DoesNotExist:
                pass

        # Gửi thông báo cho chủ sở hữu nội dung bị ẩn
        if target_owner:
            Notification.objects.create(
                user=target_owner,
                notification_type='content_hidden',
                title=title,
                payload={
                    "content_type": content_type,
                    "object_id": str(object_id),
                    "content_preview": content_preview,
                    "message": "Nội dung của bạn bị báo cáo vi phạm tiêu chuẩn cộng đồng nhiều lần và tạm thời bị ẩn. Bạn có thể gửi khiếu nại trong phần quản lý hồ sơ."
                }
            )


# ═══════════════════════════════════════════
#  DENORMALIZED COUNTERS UPDATES
# ═══════════════════════════════════════════

@receiver(post_save, sender=PostLike)
def increment_post_likes(sender, instance, created, **kwargs):
    if created:
        ForumPost.objects.filter(pk=instance.post_id).update(
            like_count=models.F('like_count') + 1
        )

@receiver(post_delete, sender=PostLike)
def decrement_post_likes(sender, instance, **kwargs):
    ForumPost.objects.filter(pk=instance.post_id).update(
        like_count=models.Case(
            models.When(like_count__gt=0, then=models.F('like_count') - 1),
            default=0
        )
    )

@receiver(post_save, sender=PostComment)
def increment_post_comments(sender, instance, created, **kwargs):
    if created:
        ForumPost.objects.filter(pk=instance.post_id).update(
            comment_count=models.F('comment_count') + 1
        )

@receiver(post_delete, sender=PostComment)
def decrement_post_comments(sender, instance, **kwargs):
    ForumPost.objects.filter(pk=instance.post_id).update(
        comment_count=models.Case(
            models.When(comment_count__gt=0, then=models.F('comment_count') - 1),
            default=0
        )
    )


@receiver(post_save, sender=WordCommentVote)
def update_word_comment_votes_on_save(sender, instance, created, **kwargs):
    """Cập nhật upvotes, downvotes và score trên WordComment khi có vote mới hoặc sửa vote"""
    comment = instance.comment
    upvotes = WordCommentVote.objects.filter(comment=comment, vote=1).count()
    downvotes = WordCommentVote.objects.filter(comment=comment, vote=-1).count()
    
    comment.upvotes = upvotes
    comment.downvotes = downvotes
    comment.score = upvotes - downvotes
    comment.save(update_fields=['upvotes', 'downvotes', 'score'])

@receiver(post_delete, sender=WordCommentVote)
def update_word_comment_votes_on_delete(sender, instance, **kwargs):
    """Cập nhật upvotes, downvotes và score trên WordComment khi vote bị xóa"""
    comment = instance.comment
    upvotes = WordCommentVote.objects.filter(comment=comment, vote=1).count()
    downvotes = WordCommentVote.objects.filter(comment=comment, vote=-1).count()
    
    comment.upvotes = upvotes
    comment.downvotes = downvotes
    comment.score = upvotes - downvotes
    comment.save(update_fields=['upvotes', 'downvotes', 'score'])


# ═══════════════════════════════════════════
#  GCS FILE CLEANUP SIGNALS
# ═══════════════════════════════════════════

@receiver(post_delete, sender=ForumPost)
def cleanup_post_image_on_delete(sender, instance, **kwargs):
    """Xóa ảnh khỏi GCS khi bài viết bị xóa."""
    if instance.image_url:
        bucket_name = getattr(settings, 'GS_BUCKET_NAME', 'cnen-bucket')
        if bucket_name and f"/{bucket_name}/" in instance.image_url:
            try:
                blob_name = instance.image_url.split(f"/{bucket_name}/", 1)[-1]
                client = storage.Client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(blob_name)
                if blob.exists():
                    blob.delete()
                    logger.info(f"🗑️ Deleted GCS image for deleted post {instance.id}: {blob_name}")
            except Exception as e:
                logger.warning(f"Failed to delete GCS image for post {instance.id}: {e}")

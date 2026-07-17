from django.contrib import admin
from django.utils import timezone
from .models import (
    WordComment, WordCommentVote, ForumPost, PostLike,
    PostComment, PostCommentLike, PostBookmark, CommunityReport, CommunityAppeal
)
from apps.notifications.models import Notification

@admin.register(ForumPost)
class ForumPostAdmin(admin.ModelAdmin):
    list_display = ('id', 'author', 'lang', 'content_summary', 'like_count', 'comment_count', 'is_hidden', 'is_pinned', 'created_at')
    list_filter = ('lang', 'is_hidden', 'is_pinned', 'created_at')
    search_fields = ('content', 'author__username')
    list_editable = ('is_hidden', 'is_pinned')
    actions = ['hide_posts', 'unhide_posts']

    def content_summary(self, obj):
        return obj.content[:50]
    content_summary.short_description = "Content"

    def hide_posts(self, request, queryset):
        queryset.update(is_hidden=True)
    hide_posts.short_description = "Hide selected posts"

    def unhide_posts(self, request, queryset):
        queryset.update(is_hidden=False)
    unhide_posts.short_description = "Unhide selected posts"


@admin.register(WordComment)
class WordCommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'word_id', 'lang', 'content_summary', 'upvotes', 'downvotes', 'score', 'is_hidden', 'created_at')
    list_filter = ('lang', 'is_hidden', 'created_at')
    search_fields = ('content', 'user__username', 'word_id')
    list_editable = ('is_hidden',)

    def content_summary(self, obj):
        return obj.content[:50]


@admin.register(PostComment)
class PostCommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'post_id', 'content_summary', 'like_count', 'is_hidden', 'created_at')
    list_filter = ('is_hidden', 'created_at')
    search_fields = ('content', 'user__username')
    list_editable = ('is_hidden',)

    def content_summary(self, obj):
        return obj.content[:50]


@admin.register(CommunityReport)
class CommunityReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'reporter', 'content_type', 'object_id', 'reason', 'created_at')
    list_filter = ('content_type', 'reason', 'created_at')
    search_fields = ('reporter__username', 'object_id', 'detail')


@admin.register(CommunityAppeal)
class CommunityAppealAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'content_type', 'object_id', 'status', 'created_at', 'resolved_at')
    list_filter = ('status', 'content_type', 'created_at')
    search_fields = ('user__username', 'object_id', 'reason', 'admin_notes')
    readonly_fields = ('created_at', 'resolved_at')
    actions = ['approve_appeals', 'reject_appeals']

    def save_model(self, request, obj, form, change):
        """Xử lý mở ẩn nội dung khi admin phê duyệt trực tiếp trong giao diện sửa appeal"""
        if change and 'status' in form.changed_data:
            self._handle_appeal_resolution(obj)
        super().save_model(request, obj, form, change)

    def approve_appeals(self, request, queryset):
        """Action phê duyệt khiếu nại hàng loạt"""
        updated_count = 0
        for appeal in queryset.filter(status='pending'):
            appeal.status = 'approved'
            appeal.resolved_at = timezone.now()
            appeal.admin_notes = "Phê duyệt hàng loạt bởi Admin"
            appeal.save()
            self._handle_appeal_resolution(appeal)
            updated_count += 1
        self.message_user(request, f"Đã phê duyệt {updated_count} khiếu nại và phục hồi nội dung.")
    approve_appeals.short_description = "Approve and restore content for selected appeals"

    def reject_appeals(self, request, queryset):
        """Action từ chối khiếu nại hàng loạt"""
        updated_count = 0
        for appeal in queryset.filter(status='pending'):
            appeal.status = 'rejected'
            appeal.resolved_at = timezone.now()
            appeal.admin_notes = "Từ chối hàng loạt bởi Admin"
            appeal.save()
            self._handle_appeal_resolution(appeal)
            updated_count += 1
        self.message_user(request, f"Đã từ chối {updated_count} khiếu nại.")
    reject_appeals.short_description = "Reject selected appeals"

    def _handle_appeal_resolution(self, appeal):
        """Xử lý logic khi một appeal được giải quyết (phục hồi hoặc từ chối vĩnh viễn)"""
        content_type = appeal.content_type
        object_id = appeal.object_id
        
        # Cập nhật thời gian giải quyết
        appeal.resolved_at = timezone.now()

        if appeal.status == 'approved':
            # Mở ẩn nội dung
            if content_type == 'post':
                ForumPost.objects.filter(pk=object_id).update(is_hidden=False)
            elif content_type == 'post_comment':
                PostComment.objects.filter(pk=object_id).update(is_hidden=False)
            elif content_type == 'word_comment':
                WordComment.objects.filter(pk=object_id).update(is_hidden=False)
            
            # Gửi thông báo phục hồi nội dung thành công
            Notification.objects.create(
                user=appeal.user,
                notification_type='appeal_resolved',
                title="Khiếu nại của bạn đã được chấp nhận",
                payload={
                    "content_type": content_type,
                    "object_id": str(object_id),
                    "status": "approved",
                    "message": "Nội dung của bạn đã được phục hồi sau khi kiểm duyệt lại."
                }
            )
        elif appeal.status == 'rejected':
            # Gửi thông báo khiếu nại bị từ chối
            Notification.objects.create(
                user=appeal.user,
                notification_type='appeal_resolved',
                title="Khiếu nại của bạn đã bị từ chối",
                payload={
                    "content_type": content_type,
                    "object_id": str(object_id),
                    "status": "rejected",
                    "message": f"Khiếu nại của bạn đã bị từ chối. Ghi chú admin: {appeal.admin_notes}"
                }
            )


# Register other standard models without customized views
admin.site.register(WordCommentVote)
admin.site.register(PostLike)
admin.site.register(PostCommentLike)
admin.site.register(PostBookmark)

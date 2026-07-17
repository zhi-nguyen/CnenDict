from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    WordComment, WordCommentVote, ForumPost, PostLike,
    PostComment, PostCommentLike, PostBookmark, CommunityReport, CommunityAppeal
)

User = get_user_model()

class UserMinSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    equipped_frame = serializers.SerializerMethodField()
    equipped_title = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'avatar', 'full_name', 'equipped_frame', 'equipped_title')

    def get_full_name(self, obj):
        full_name = obj.get_full_name().strip()
        return full_name if full_name else obj.username

    def get_equipped_frame(self, obj):
        from apps.gamification.models import UserInventory
        from apps.gamification.serializers import RewardItemSerializer
        inv = UserInventory.objects.filter(user=obj, reward_item__reward_type='avatar_frame', is_equipped=True).select_related('reward_item').first()
        if inv:
            return RewardItemSerializer(inv.reward_item).data
        return None

    def get_equipped_title(self, obj):
        from apps.gamification.models import UserInventory
        from apps.gamification.serializers import RewardItemSerializer
        inv = UserInventory.objects.filter(user=obj, reward_item__reward_type='title', is_equipped=True).select_related('reward_item').first()
        if inv:
            return RewardItemSerializer(inv.reward_item).data
        return None


class WordCommentSerializer(serializers.ModelSerializer):
    user = UserMinSerializer(read_only=True)
    my_vote = serializers.SerializerMethodField()

    class Meta:
        model = WordComment
        fields = ('id', 'user', 'word_id', 'lang', 'content', 'upvotes', 'downvotes', 'score', 'is_hidden', 'created_at', 'updated_at', 'my_vote')
        read_only_fields = ('id', 'user', 'upvotes', 'downvotes', 'score', 'is_hidden', 'created_at', 'updated_at')

    def get_my_vote(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            vote_obj = WordCommentVote.objects.filter(user=request.user, comment=obj).first()
            if vote_obj:
                return vote_obj.vote
        return 0


class ForumPostSerializer(serializers.ModelSerializer):
    author = UserMinSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    is_bookmarked = serializers.SerializerMethodField()

    class Meta:
        model = ForumPost
        fields = ('id', 'author', 'lang', 'content', 'image_url', 'like_count', 'comment_count', 'is_hidden', 'is_pinned', 'created_at', 'updated_at', 'is_liked', 'is_bookmarked')
        read_only_fields = ('id', 'author', 'like_count', 'comment_count', 'is_hidden', 'is_pinned', 'created_at', 'updated_at')

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return PostLike.objects.filter(user=request.user, post=obj).exists()
        return False

    def get_is_bookmarked(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return PostBookmark.objects.filter(user=request.user, post=obj).exists()
        return False


class PostCommentSerializer(serializers.ModelSerializer):
    user = UserMinSerializer(read_only=True)
    like_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.SerializerMethodField()

    class Meta:
        model = PostComment
        fields = ('id', 'user', 'post', 'content', 'like_count', 'is_hidden', 'created_at', 'is_liked')
        read_only_fields = ('id', 'user', 'post', 'like_count', 'is_hidden', 'created_at')

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return PostCommentLike.objects.filter(user=request.user, comment=obj).exists()
        return False


class CommunityReportSerializer(serializers.ModelSerializer):
    reporter = UserMinSerializer(read_only=True)

    class Meta:
        model = CommunityReport
        fields = ('id', 'reporter', 'content_type', 'object_id', 'reason', 'detail', 'created_at')
        read_only_fields = ('id', 'reporter', 'created_at')

    def validate(self, attrs):
        request = self.context.get('request')
        if not request or not request.user:
            raise serializers.ValidationError("Authentication required")

        content_type = attrs.get('content_type')
        object_id = attrs.get('object_id')

        if content_type == 'post':
            post = ForumPost.objects.filter(pk=object_id).first()
            if post and post.author == request.user:
                raise serializers.ValidationError("Bạn không thể báo cáo bài viết của chính mình.")
        elif content_type == 'post_comment':
            comment = PostComment.objects.filter(pk=object_id).first()
            if comment and comment.user == request.user:
                raise serializers.ValidationError("Bạn không thể báo cáo bình luận của chính mình.")
        elif content_type == 'word_comment':
            comment = WordComment.objects.filter(pk=object_id).first()
            if comment and comment.user == request.user:
                raise serializers.ValidationError("Bạn không thể báo cáo bình luận của chính mình.")

        return attrs


class CommunityAppealSerializer(serializers.ModelSerializer):
    user = UserMinSerializer(read_only=True)

    class Meta:
        model = CommunityAppeal
        fields = ('id', 'user', 'content_type', 'object_id', 'reason', 'status', 'admin_notes', 'created_at', 'resolved_at')
        read_only_fields = ('id', 'user', 'status', 'admin_notes', 'created_at', 'resolved_at')

    def validate(self, attrs):
        request = self.context.get('request')
        if not request or not request.user:
            raise serializers.ValidationError("Authentication required")

        content_type = attrs.get('content_type')
        object_id = attrs.get('object_id')

        is_owner = False
        is_currently_hidden = False

        if content_type == 'post':
            post = ForumPost.objects.filter(pk=object_id).first()
            if post:
                is_owner = (post.author == request.user)
                is_currently_hidden = post.is_hidden
        elif content_type == 'post_comment':
            comment = PostComment.objects.filter(pk=object_id).first()
            if comment:
                is_owner = (comment.user == request.user)
                is_currently_hidden = comment.is_hidden
        elif content_type == 'word_comment':
            comment = WordComment.objects.filter(pk=object_id).first()
            if comment:
                is_owner = (comment.user == request.user)
                is_currently_hidden = comment.is_hidden

        if not is_owner:
            raise serializers.ValidationError("Bạn chỉ có thể khiếu nại nội dung của chính mình.")
        if not is_currently_hidden:
            raise serializers.ValidationError("Nội dung này không bị ẩn, bạn không cần gửi khiếu nại.")

        existing = CommunityAppeal.objects.filter(user=request.user, content_type=content_type, object_id=object_id).exists()
        if existing:
            raise serializers.ValidationError("Bạn đã gửi khiếu nại cho nội dung này rồi.")

        return attrs

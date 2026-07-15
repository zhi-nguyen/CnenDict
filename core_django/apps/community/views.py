import logging
from rest_framework import generics, status, views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.db import models
from django.conf import settings
from google.cloud import storage

from .models import (
    WordComment, WordCommentVote, ForumPost, PostLike,
    PostComment, PostCommentLike, PostBookmark, CommunityReport, CommunityAppeal
)
from .serializers import (
    WordCommentSerializer, ForumPostSerializer, PostCommentSerializer,
    CommunityReportSerializer, CommunityAppealSerializer
)
from .throttles import PostCreateThrottle, CommentCreateThrottle, ReportThrottle

logger = logging.getLogger(__name__)

def _move_temp_to_permanent(temp_url: str, lang: str) -> str:
    """Di chuyển ảnh từ temp → permanent trên GCS.
    Trả về URL vĩnh viễn. Nếu thất bại hoặc local debug, giữ nguyên temp_url."""
    # Hỗ trợ local mock mode khi không cấu hình GCS
    if settings.DEBUG and "localhost" in temp_url:
        return temp_url

    bucket_name = getattr(settings, 'GS_BUCKET_NAME', 'cnen-bucket')
    if not bucket_name or bucket_name not in temp_url:
        return temp_url

    temp_blob_name = temp_url.split(f"{bucket_name}/", 1)[-1]
    if not temp_blob_name.startswith("community/temp/"):
        return temp_url

    file_name = temp_blob_name.rsplit("/", 1)[-1]
    permanent_blob_name = f"community/images/{lang}/{file_name}"

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        source_blob = bucket.blob(temp_blob_name)
        if source_blob.exists():
            new_blob = bucket.copy_blob(source_blob, bucket, permanent_blob_name)
            source_blob.delete()
            return new_blob.public_url
    except Exception as e:
        logger.warning(f"Failed to move temp image to permanent folder on GCS: {e}")

    return temp_url


# ═══════════════════════════════════════════
#  WORD COMMENT VIEWS
# ═══════════════════════════════════════════

class WordCommentView(views.APIView):
    """Lấy danh sách bình luận hoặc đăng bình luận trên từ vựng"""
    permission_classes = [IsAuthenticated]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [CommentCreateThrottle()]
        return []

    def get(self, request):
        word_id = request.query_params.get('word_id')
        lang = request.query_params.get('lang')
        if not word_id or not lang:
            return Response({"detail": "Missing word_id or lang"}, status=status.HTTP_400_BAD_REQUEST)

        # Trả về các bình luận không bị ẩn, ưu tiên score cao nhất
        comments = WordComment.objects.filter(word_id=word_id, lang=lang, is_hidden=False).order_by('-score', '-created_at')
        serializer = WordCommentSerializer(comments, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        serializer = WordCommentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            # Kiểm tra xem user đã comment từ này chưa
            word_id = serializer.validated_data['word_id']
            lang = serializer.validated_data['lang']
            if WordComment.objects.filter(user=request.user, word_id=word_id, lang=lang).exists():
                return Response({"detail": "Bạn đã bình luận từ vựng này rồi."}, status=status.HTTP_400_BAD_REQUEST)

            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class WordCommentDeleteView(views.APIView):
    """Xóa bình luận từ vựng của bản thân"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        comment = get_object_or_404(WordComment, pk=pk, user=request.user)
        comment.delete()
        return Response({"detail": "Đã xóa bình luận thành công."}, status=status.HTTP_200_OK)


class WordCommentVoteView(views.APIView):
    """Upvote/Downvote cho bình luận từ vựng (Toggle)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        comment = get_object_or_404(WordComment, pk=pk)
        vote_value = request.data.get('vote') # 1 (upvote) hoặc -1 (downvote)

        if vote_value not in (1, -1):
            return Response({"detail": "Vote value must be 1 or -1"}, status=status.HTTP_400_BAD_REQUEST)

        vote_obj, created = WordCommentVote.objects.get_or_create(
            user=request.user,
            comment=comment,
            defaults={'vote': vote_value}
        )

        if not created:
            # Nếu vote trùng với giá trị cũ -> Toggle (Hủy vote)
            if vote_obj.vote == vote_value:
                vote_obj.delete()
                return Response({"detail": "Đã hủy bỏ vote thành công.", "my_vote": 0}, status=status.HTTP_200_OK)
            else:
                # Đổi vote từ Up sang Down hoặc ngược lại
                vote_obj.vote = vote_value
                vote_obj.save(update_fields=['vote'])

        return Response({
            "detail": "Đã lưu vote thành công.",
            "my_vote": vote_value
        }, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════
#  FORUM POST VIEWS
# ═══════════════════════════════════════════

class ForumPostListView(generics.ListCreateAPIView):
    """Feed bài viết cộng đồng (GET list) hoặc đăng bài mới (POST)"""
    serializer_class = ForumPostSerializer
    permission_classes = [IsAuthenticated]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [PostCreateThrottle()]
        return []

    def get_queryset(self):
        lang = self.request.query_params.get('lang')
        if not lang:
            return ForumPost.objects.none()
        
        # Chỉ trả về bài viết không bị ẩn theo ngôn ngữ
        return ForumPost.objects.filter(lang=lang, is_hidden=False)

    def perform_create(self, serializer):
        image_url = serializer.validated_data.get('image_url', '')
        lang = serializer.validated_data['lang']

        # Di chuyển ảnh từ temp sang permanent folder
        if image_url:
            image_url = _move_temp_to_permanent(image_url, lang)

        serializer.save(author=self.request.user, image_url=image_url)


class ForumPostDetailView(generics.RetrieveDestroyAPIView):
    """Chi tiết bài viết hoặc xóa bài viết của mình"""
    queryset = ForumPost.objects.all()
    serializer_class = ForumPostSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        obj = super().get_object()
        # Chặn xem nếu bài viết bị ẩn bởi hệ thống (chỉ cho phép chủ bài xem bài viết bị ẩn)
        if obj.is_hidden and obj.author != self.request.user:
            raise status.exceptions.PermissionDenied("Bài viết này đã bị ẩn do vi phạm tiêu chuẩn cộng đồng.")
        return obj

    def perform_destroy(self, instance):
        if instance.author != self.request.user:
            raise status.exceptions.PermissionDenied("Bạn không có quyền xóa bài viết này.")
        instance.delete()


class PostLikeView(views.APIView):
    """Toggle Like bài viết"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        post = get_object_or_404(ForumPost, pk=pk)
        like_obj = PostLike.objects.filter(user=request.user, post=post).first()
        
        if like_obj:
            like_obj.delete()
            return Response({"liked": False, "like_count": post.likes.count()}, status=status.HTTP_200_OK)
        else:
            PostLike.objects.create(user=request.user, post=post)
            # Gửi notification cho chủ bài viết (nếu không tự like bài mình)
            if post.author != request.user:
                from apps.notifications.models import Notification
                Notification.objects.create(
                    user=post.author,
                    notification_type='post_liked',
                    title=f"{request.user.username} đã thích bài viết của bạn",
                    payload={"post_id": str(post.id), "content_preview": post.content[:30]}
                )
            return Response({"liked": True, "like_count": post.likes.count()}, status=status.HTTP_200_OK)


class PostBookmarkView(views.APIView):
    """Toggle Bookmark bài viết"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        post = get_object_or_404(ForumPost, pk=pk)
        bookmark_obj = PostBookmark.objects.filter(user=request.user, post=post).first()

        if bookmark_obj:
            bookmark_obj.delete()
            return Response({"bookmarked": False}, status=status.HTTP_200_OK)
        else:
            PostBookmark.objects.create(user=request.user, post=post)
            return Response({"bookmarked": True}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════
#  POST COMMENT VIEWS
# ═══════════════════════════════════════════

class PostCommentView(views.APIView):
    """Xem danh sách comment hoặc tạo comment trên bài viết"""
    permission_classes = [IsAuthenticated]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [CommentCreateThrottle()]
        return []

    def get(self, request, post_pk):
        post = get_object_or_404(ForumPost, pk=post_pk)
        comments = PostComment.objects.filter(post=post, is_hidden=False)
        serializer = PostCommentSerializer(comments, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request, post_pk):
        post = get_object_or_404(ForumPost, pk=post_pk)
        serializer = PostCommentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            comment = serializer.save(user=request.user, post=post)
            # Gửi notification cho chủ bài viết
            if post.author != request.user:
                from apps.notifications.models import Notification
                Notification.objects.create(
                    user=post.author,
                    notification_type='post_commented',
                    title=f"{request.user.username} đã bình luận bài viết của bạn",
                    payload={"post_id": str(post.id), "comment_id": str(comment.id), "content_preview": comment.content[:30]}
                )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PostCommentDeleteView(views.APIView):
    """Xóa bình luận diễn đàn của bản thân"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        comment = get_object_or_404(PostComment, pk=pk, user=request.user)
        comment.delete()
        return Response({"detail": "Đã xóa bình luận thành công."}, status=status.HTTP_200_OK)


class PostCommentLikeView(views.APIView):
    """Toggle Like bình luận trên bài viết"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        comment = get_object_or_404(PostComment, pk=pk)
        like_obj = PostCommentLike.objects.filter(user=request.user, comment=comment).first()

        if like_obj:
            like_obj.delete()
            # Cập nhật denormalized counter
            comment.like_count = comment.likes.count()
            comment.save(update_fields=['like_count'])
            return Response({"liked": False, "like_count": comment.like_count}, status=status.HTTP_200_OK)
        else:
            PostCommentLike.objects.create(user=request.user, comment=comment)
            comment.like_count = comment.likes.count()
            comment.save(update_fields=['like_count'])
            return Response({"liked": True, "like_count": comment.like_count}, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════
#  MODERATION & REPORT/APPEAL VIEWS
# ═══════════════════════════════════════════

class CommunityReportView(generics.CreateAPIView):
    """Gửi báo cáo vi phạm nội dung"""
    serializer_class = CommunityReportSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReportThrottle]

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)


# ═══════════════════════════════════════════
#  MY COMMUNITY CONTENTS (PROFILE TABS)
# ═══════════════════════════════════════════

class MyPostsView(generics.ListAPIView):
    """Danh sách bài viết của tôi"""
    serializer_class = ForumPostSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Trả về tất cả bài viết của user (kể cả bài bị ẩn để user quản lý khiếu nại)
        return ForumPost.objects.filter(author=self.request.user)


class MyCommentsView(views.APIView):
    """Danh sách comment của tôi (post comments + word comments)"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        post_comments = PostComment.objects.filter(user=user)
        word_comments = WordComment.objects.filter(user=user)

        post_comments_serializer = PostCommentSerializer(post_comments, many=True, context={'request': request})
        word_comments_serializer = WordCommentSerializer(word_comments, many=True, context={'request': request})

        return Response({
            "post_comments": post_comments_serializer.data,
            "word_comments": word_comments_serializer.data
        }, status=status.HTTP_200_OK)


class MyLikesView(views.APIView):
    """Danh sách bài viết tôi đã thích"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        liked_posts = ForumPost.objects.filter(likes__user=request.user, is_hidden=False)
        serializer = ForumPostSerializer(liked_posts, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class MyBookmarksView(generics.ListAPIView):
    """Danh sách bài viết tôi đã lưu"""
    serializer_class = ForumPostSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ForumPost.objects.filter(bookmarks__user=self.request.user, is_hidden=False)


class MyHiddenContentView(views.APIView):
    """Danh sách bài viết và bình luận bị ẩn của tôi"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        hidden_posts = ForumPost.objects.filter(author=user, is_hidden=True)
        hidden_post_comments = PostComment.objects.filter(user=user, is_hidden=True)
        hidden_word_comments = WordComment.objects.filter(user=user, is_hidden=True)

        return Response({
            "posts": ForumPostSerializer(hidden_posts, many=True, context={'request': request}).data,
            "post_comments": PostCommentSerializer(hidden_post_comments, many=True, context={'request': request}).data,
            "word_comments": WordCommentSerializer(hidden_word_comments, many=True, context={'request': request}).data,
        }, status=status.HTTP_200_OK)


class CommunityAppealView(views.APIView):
    """Gửi khiếu nại hoặc xem danh sách khiếu nại của tôi"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        appeals = CommunityAppeal.objects.filter(user=request.user)
        serializer = CommunityAppealSerializer(appeals, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = CommunityAppealSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

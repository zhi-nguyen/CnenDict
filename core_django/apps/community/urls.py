from django.urls import path
from .views import (
    WordCommentView, WordCommentDeleteView, WordCommentVoteView,
    ForumPostListView, ForumPostDetailView, PostLikeView, PostBookmarkView,
    PostCommentView, PostCommentDeleteView, PostCommentLikeView,
    CommunityReportView, CommunityAppealView,
    MyPostsView, MyCommentsView, MyLikesView, MyBookmarksView, MyHiddenContentView
)

app_name = 'community'

urlpatterns = [
    # Word Comments
    path('word-comments/', WordCommentView.as_view(), name='word-comments'),
    path('word-comments/<uuid:pk>/', WordCommentDeleteView.as_view(), name='word-comments-delete'),
    path('word-comments/<uuid:pk>/vote/', WordCommentVoteView.as_view(), name='word-comments-vote'),

    # Forum Posts
    path('posts/', ForumPostListView.as_view(), name='posts-list'),
    path('posts/<uuid:pk>/', ForumPostDetailView.as_view(), name='posts-detail'),
    path('posts/<uuid:pk>/like/', PostLikeView.as_view(), name='posts-like'),
    path('posts/<uuid:pk>/bookmark/', PostBookmarkView.as_view(), name='posts-bookmark'),

    # Post Comments
    path('posts/<uuid:post_pk>/comments/', PostCommentView.as_view(), name='post-comments'),
    path('comments/<uuid:pk>/', PostCommentDeleteView.as_view(), name='post-comments-delete'),
    path('comments/<uuid:pk>/like/', PostCommentLikeView.as_view(), name='post-comments-like'),

    # Reports & Appeals
    path('report/', CommunityReportView.as_view(), name='report-create'),
    path('appeals/', CommunityAppealView.as_view(), name='appeals-list'),

    # Profile management
    path('me/posts/', MyPostsView.as_view(), name='my-posts'),
    path('me/comments/', MyCommentsView.as_view(), name='my-comments'),
    path('me/likes/', MyLikesView.as_view(), name='my-likes'),
    path('me/bookmarks/', MyBookmarksView.as_view(), name='my-bookmarks'),
    path('me/hidden/', MyHiddenContentView.as_view(), name='my-hidden-content'),
]

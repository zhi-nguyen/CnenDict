import logging
from rest_framework import views, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Count

from .models import LeaderboardSnapshot, LeaderboardEntry
from .serializers import LeaderboardEntrySerializer
from apps.gamification.models import CoinWallet, CoinTransaction, StudySession, StudySessionCard, UserStreak

logger = logging.getLogger(__name__)

class LeaderboardView(views.APIView):
    """
    Lấy danh sách bảng xếp hạng mới nhất và thông tin xếp hạng của user hiện tại.
    Cho phép Guest xem bảng xếp hạng (AllowAny). Guest không có my_entry.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        board_type = request.query_params.get('board_type')
        lang = request.query_params.get('lang')

        if not board_type or not lang:
            return Response({"detail": "Missing board_type or lang"}, status=status.HTTP_400_BAD_REQUEST)

        valid_board_types = [t[0] for t in LeaderboardSnapshot.BOARD_TYPES]
        if board_type not in valid_board_types:
            return Response({"detail": f"Invalid board_type. Valid values: {valid_board_types}"}, status=status.HTTP_400_BAD_REQUEST)

        if lang not in ('zh', 'en'):
            return Response({"detail": "Invalid lang. Valid values: 'zh', 'en'"}, status=status.HTTP_400_BAD_REQUEST)

        is_authenticated = request.user and request.user.is_authenticated

        # 1. Tìm snapshot mới nhất
        snapshot = LeaderboardSnapshot.objects.filter(
            board_type=board_type,
            lang=lang
        ).order_by('-created_at').first()

        if not snapshot:
            # Không có snapshot nào → trả empty
            my_entry = None
            if is_authenticated:
                full_name = request.user.get_full_name().strip()
                my_entry = {
                    "rank": None,
                    "score": 0,
                    "username": full_name if full_name else request.user.username,
                    "avatar_url": request.user.avatar.url if request.user.avatar else ""
                }
            return Response({
                "snapshot_id": None,
                "created_at": None,
                "entries": [],
                "my_entry": my_entry
            })

        # 2. Lấy top 50 entries
        entries = LeaderboardEntry.objects.filter(snapshot=snapshot).select_related('user').order_by('rank')
        entries_serializer = LeaderboardEntrySerializer(entries, many=True)

        # 3. Tìm hoặc tính toán hạng của user hiện tại
        my_entry_data = None
        if is_authenticated:
            my_entry_db = LeaderboardEntry.objects.filter(snapshot=snapshot, user=request.user).select_related('user').first()

            if my_entry_db:
                my_entry_data = LeaderboardEntrySerializer(my_entry_db).data
            else:
                # User nằm ngoài Top 50, tính score thủ công
                score = 0
                user = request.user

                if board_type == 'coin_paid':
                    wallet = CoinWallet.objects.filter(user=user, lang=lang).first()
                    if wallet:
                        spent = CoinTransaction.objects.filter(wallet=wallet, balance_type='paid', amount__lt=0).aggregate(total=Sum('amount'))['total'] or 0
                        score = wallet.paid_balance + abs(spent)
                elif board_type == 'coin_free':
                    wallet = CoinWallet.objects.filter(user=user, lang=lang).first()
                    if wallet:
                        spent = CoinTransaction.objects.filter(wallet=wallet, balance_type='free', amount__lt=0).aggregate(total=Sum('amount'))['total'] or 0
                        score = wallet.free_balance + abs(spent)
                elif board_type == 'total_likes':
                    from apps.community.models import WordComment, ForumPost
                    word_likes = WordComment.objects.filter(user=user, lang=lang, is_hidden=False).aggregate(total=Sum('upvotes'))['total'] or 0
                    post_likes = ForumPost.objects.filter(author=user, lang=lang, is_hidden=False).aggregate(total=Sum('like_count'))['total'] or 0
                    score = word_likes + post_likes
                elif board_type == 'weekly_words':
                    start_of_week = timezone.now() - timedelta(days=7)
                    score = StudySessionCard.objects.filter(
                        session__user=user,
                        session__lang=lang,
                        session__status='FINISHED',
                        status='memorized',
                        updated_at__gte=start_of_week
                    ).values('word').distinct().count()
                elif board_type == 'max_streak':
                    start_of_week = timezone.now() - timedelta(days=7)
                    has_active = StudySession.objects.filter(user=user, lang=lang, created_at__gte=start_of_week).exists()
                    if has_active:
                        streak = UserStreak.objects.filter(user=user).first()
                        score = streak.max_streak if streak else 0

                full_name = user.get_full_name().strip()
                my_entry_data = {
                    "rank": None, # Ngoài top 50, hiển thị là "-" hoặc "50+" trên frontend
                    "score": score,
                    "username": full_name if full_name else user.username,
                    "avatar_url": user.avatar.url if user.avatar else "",
                    "user": str(user.id)
                }

        return Response({
            "snapshot_id": str(snapshot.id),
            "created_at": snapshot.created_at.isoformat(),
            "entries": entries_serializer.data,
            "my_entry": my_entry_data
        }, status=status.HTTP_200_OK)


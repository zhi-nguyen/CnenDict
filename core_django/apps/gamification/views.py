from rest_framework import generics, views, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from .models import UserStreak, DailyTarget, StudyHistory, DailyActivity
from .serializers import UserStreakSerializer, DailyTargetSerializer, StudyHistorySerializer, DailyActivitySerializer

class StreakView(generics.RetrieveAPIView):
    serializer_class = UserStreakSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        streak, _ = UserStreak.objects.get_or_create(user=self.request.user)
        return streak

class TargetView(generics.RetrieveUpdateAPIView):
    serializer_class = DailyTargetSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        target, _ = DailyTarget.objects.get_or_create(user=self.request.user)
        return target

class StudyHistoryLogView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Retrieve study history for the current user.
        """
        history = StudyHistory.objects.filter(user=request.user).order_by('-study_date')
        serializer = StudyHistorySerializer(history, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        """
        Increment the study history for today.
        Expects payload: {
            "vocabulary_learned": 5,
            "pronunciation_accuracy": 0.85,
            "study_duration_seconds": 300
        }
        """
        user = request.user
        today = timezone.localdate()

        vocab = request.data.get('vocabulary_learned', 0)
        acc = request.data.get('pronunciation_accuracy', 0.0)
        dur = request.data.get('study_duration_seconds', 0)

        history, created = StudyHistory.objects.get_or_create(user=user, study_date=today)
        
        # Calculate new average accuracy if needed, or simply keep the latest/highest.
        # For simplicity, if acc is provided, update it with an average.
        if acc > 0:
            if history.pronunciation_accuracy > 0:
                history.pronunciation_accuracy = (history.pronunciation_accuracy + acc) / 2.0
            else:
                history.pronunciation_accuracy = acc

        history.vocabulary_learned += int(vocab)
        history.study_duration_seconds += int(dur)
        history.save()

        # Immediately check if target met so user can see it without waiting for cron?
        # Typically gamification might show "Target Met!" immediately.
        # For performance, this is fine to do here for the current user.
        target, _ = DailyTarget.objects.get_or_create(user=user)
        is_met = False
        if target.target_type == 'words' and history.vocabulary_learned >= target.target_words:
            is_met = True
        elif target.target_type == 'duration' and history.study_duration_seconds >= (target.target_duration * 60):
            is_met = True
        
        if is_met:
            # We can mark it met for today, but the cron job will finalize streaks.
            # Or we can update the streak immediately if it wasn't met already.
            activity, created_act = DailyActivity.objects.get_or_create(user=user, activity_date=today)
            if not activity.is_target_met:
                activity.is_target_met = True
                activity.save()
                
                # We can dynamically increase the current streak immediately if we want real-time feedback
                # But to prevent double counting, the cron job should be the single source of truth for streak increments.

        return Response(StudyHistorySerializer(history).data, status=status.HTTP_200_OK)

from apps.dictionary_zh.views import StandardResultsSetPagination
from apps.flashcard_exercises.models import FlashcardExercise
from .models import StudySession, StudySessionCard, CoinWallet, CoinTransaction, CoinPurchaseOrder
from .serializers import StudySessionSerializer, StudySessionCardSerializer, CoinWalletSerializer, CoinTransactionSerializer
from .coin_service import CoinService
import uuid

class ActivityHistoryView(generics.ListAPIView):
    serializer_class = DailyActivitySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return DailyActivity.objects.filter(user=self.request.user).order_by('-activity_date')


class CreateStudySessionView(views.APIView):
    """
    POST /api/v1/gamification/study-session/
    Body: { "card_ids": ["uuid1", "uuid2"], "lang": "zh" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        card_ids = request.data.get('card_ids', [])
        lang = request.data.get('lang', 'zh')

        if not card_ids:
            return Response({"error": "card_ids is required and cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure session is created atomically
        from django.db import transaction
        with transaction.atomic():
            session = StudySession.objects.create(
                user=request.user,
                lang=lang,
                total_cards=len(card_ids),
                status='IN_PROGRESS'
            )

            # Query the exercises in DB to get the words
            exercises_map = {str(ex.id): ex.word for ex in FlashcardExercise.objects.filter(id__in=card_ids)}

            cards_to_create = []
            for cid in card_ids:
                word = exercises_map.get(str(cid), '')
                cards_to_create.append(StudySessionCard(
                    session=session,
                    card_id=cid,
                    word=word,
                    status='pending'
                ))
            
            StudySessionCard.objects.bulk_create(cards_to_create)

        return Response({
            "status": "success",
            "session_id": str(session.id),
            "total_cards": session.total_cards
        }, status=status.HTTP_201_CREATED)


class FinishStudySessionView(views.APIView):
    """
    POST /api/v1/gamification/study-session/<session_id>/finish/
    Body: { "card_results": [{"card_id": "uuid", "status": "memorized"}, ...] }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        try:
            session = StudySession.objects.get(id=session_id, user=request.user)
        except StudySession.DoesNotExist:
            return Response({"error": "Study session not found."}, status=status.HTTP_404_NOT_FOUND)

        if session.status != 'IN_PROGRESS':
            return Response({"error": "Study session is already finished or abandoned."}, status=status.HTTP_400_BAD_REQUEST)

        card_results = request.data.get('card_results', [])

        # Get settings/configs
        user_tier = getattr(request.user.subscription, 'tier', 'Free') if hasattr(request.user, 'subscription') else 'Free'
        config = CoinService.get_coin_config(user_tier)
        words_per_coin = config.words_per_coin if config else 5

        from django.db import transaction
        with transaction.atomic():
            # Update card statuses locally buffered
            if card_results:
                status_map = {str(item.get('card_id')): item.get('status') for item in card_results if item.get('card_id')}
                cards_to_update = []
                session_cards = session.session_cards.filter(card_id__in=list(status_map.keys()))
                for card in session_cards:
                    status_val = status_map.get(str(card.card_id))
                    if status_val in ['pending', 'memorized', 'skipped']:
                        card.status = status_val
                        cards_to_update.append(card)
                
                if cards_to_update:
                    StudySessionCard.objects.bulk_update(cards_to_update, ['status', 'updated_at'])

                # Mark words as mastered in the notebook and update StudyHistory
                memorized_card_ids = [
                    str(item.get('card_id')) 
                    for item in card_results 
                    if item.get('status') == 'memorized' and item.get('card_id')
                ]
                if memorized_card_ids:
                    from apps.notes.models import Word
                    # Fetch words that are not yet mastered to avoid double-counting
                    newly_mastered_words = Word.objects.filter(
                        id__in=memorized_card_ids,
                        notebook__user=request.user,
                        is_mastered=False
                    )
                    newly_mastered_count = newly_mastered_words.count()
                    if newly_mastered_count > 0:
                        newly_mastered_words.update(is_mastered=True)
                        
                        # Increment vocabulary_learned in today's StudyHistory
                        today = timezone.localdate()
                        history, created = StudyHistory.objects.get_or_create(user=request.user, study_date=today)
                        history.vocabulary_learned += newly_mastered_count
                        history.save()
                        
                        # Check daily target
                        target, _ = DailyTarget.objects.get_or_create(user=request.user)
                        is_met = False
                        if target.target_type == 'words' and history.vocabulary_learned >= target.target_words:
                            is_met = True
                        elif target.target_type == 'duration' and history.study_duration_seconds >= (target.target_duration * 60):
                            is_met = True
                        
                        if is_met:
                            activity, created_act = DailyActivity.objects.get_or_create(user=request.user, activity_date=today)
                            if not activity.is_target_met:
                                activity.is_target_met = True
                                activity.save()

            # Count memorized cards
            memorized_count = session.session_cards.filter(status='memorized').count()

            # Calculate coins
            coins_earned = CoinService.calculate_session_coins(memorized_count, words_per_coin)

            session.status = 'FINISHED'
            session.memorized_count = memorized_count
            session.finished_at = timezone.now()

            is_capped = False
            actual_earned = 0
            if coins_earned > 0:
                _txn, actual_earned, is_capped = CoinService.earn_coins(
                    user=request.user,
                    lang=session.lang,
                    amount=coins_earned,
                    reference_id=str(session.id),
                    note=f"Học flashcard session {session.id}"
                )
            
            session.coins_earned = actual_earned
            session.save(update_fields=['status', 'memorized_count', 'coins_earned', 'finished_at'])

        balances = CoinService.get_all_balances(request.user)

        return Response({
            "status": "success",
            "session_id": str(session.id),
            "memorized_count": memorized_count,
            "coins_earned": actual_earned,
            "is_capped": is_capped,
            "wallet_balances": balances
        }, status=status.HTTP_200_OK)


class CoinConfigView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_tier = getattr(request.user.subscription, 'tier', 'Free') if hasattr(request.user, 'subscription') else 'Free'
        config = CoinService.get_coin_config(user_tier)
        
        # Safe default values
        weekly_refill_cap = config.weekly_refill_cap if config else 5
        words_per_coin = config.words_per_coin if config else 5
        chat_create_cost = config.chat_create_cost if config else 5
        chat_message_cost = config.chat_message_cost if config else 1
        
        return Response({
            "tier": user_tier,
            "weekly_refill_cap": weekly_refill_cap,
            "words_per_coin": words_per_coin,
            "chat_create_cost": chat_create_cost,
            "chat_message_cost": chat_message_cost,
            "coin_price_vnd": 500,
            "purchase_presets": [10, 20, 50, 100]
        }, status=status.HTTP_200_OK)


class CoinPurchaseStatusView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        try:
            order = CoinPurchaseOrder.objects.get(id=order_id, user=request.user)
        except CoinPurchaseOrder.DoesNotExist:
            return Response(
                {"error": "Đơn mua coin không tồn tại."},
                status=status.HTTP_404_NOT_FOUND
            )

        if order.is_expired:
            order.status = 'EXPIRED'
            order.save(update_fields=['status'])

        balances = CoinService.get_all_balances(request.user)

        return Response({
            "order_id": str(order.id),
            "order_code": order.order_code,
            "status": order.status,
            "coin_amount": order.coin_amount,
            "price": int(order.price),
            "wallet_balances": balances
        }, status=status.HTTP_200_OK)



class WalletBalanceView(views.APIView):
    """
    GET /api/v1/gamification/wallet/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        balances = CoinService.get_all_balances(request.user)
        return Response(balances, status=status.HTTP_200_OK)


class InitiateCoinPurchaseView(views.APIView):
    """
    POST /api/v1/gamification/wallet/purchase/
    Body: { "lang": "zh", "coin_amount": 50 }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        lang = request.data.get('lang', 'zh')
        coin_amount = request.data.get('coin_amount')

        if not coin_amount or not isinstance(coin_amount, int) or coin_amount <= 0:
            return Response({"error": "Invalid coin_amount. Must be a positive integer."}, status=status.HTTP_400_BAD_REQUEST)

        if lang not in ['zh', 'en']:
            return Response({"error": "Invalid language. Must be 'zh' or 'en'."}, status=status.HTTP_400_BAD_REQUEST)

        # 500 VND per coin
        COIN_PRICE_VND = 500
        price = coin_amount * COIN_PRICE_VND

        from apps.subscriptions.services import (
            get_sepay_bank_code,
            get_sepay_account_number,
            get_sepay_account_name,
            get_sepay_order_prefix
        )

        order_code = f"ORDC{uuid.uuid4().hex[:7].upper()}"
        transfer_content = f"{get_sepay_order_prefix()} {order_code}"
        expires_at = timezone.now() + timezone.timedelta(minutes=15)

        order = CoinPurchaseOrder.objects.create(
            user=request.user,
            lang=lang,
            coin_amount=coin_amount,
            price=price,
            order_code=order_code,
            transfer_content=transfer_content,
            expires_at=expires_at
        )

        bank_code = get_sepay_bank_code()
        account_number = get_sepay_account_number()
        account_name = get_sepay_account_name()

        qr_url = (
            f"https://img.vietqr.io/image/"
            f"{bank_code}-{account_number}-compact2.png"
            f"?amount={int(order.price)}"
            f"&addInfo={order.transfer_content}"
            f"&accountName={account_name}"
        )

        return Response({
            "status": "payment_pending",
            "order_id": str(order.id),
            "order_code": order.order_code,
            "coin_amount": order.coin_amount,
            "price": int(order.price),
            "qr_url": qr_url,
            "bank_code": bank_code,
            "account_number": account_number,
            "account_name": account_name,
            "transfer_content": order.transfer_content,
            "expires_at": order.expires_at.isoformat()
        }, status=status.HTTP_201_CREATED)


class GamificationDashboardView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        streak, _ = UserStreak.objects.get_or_create(user=user)
        target, _ = DailyTarget.objects.get_or_create(user=user)
        history = StudyHistory.objects.filter(user=user).order_by('-study_date')
        wallets = CoinService.get_all_balances(user)

        return Response({
            'streak': UserStreakSerializer(streak).data,
            'target': DailyTargetSerializer(target).data,
            'history': StudyHistorySerializer(history, many=True).data,
            'wallets': {
                'zh': {'name': 'Linh Thạch', **wallets['zh']},
                'en': {'name': 'Coin', **wallets['en']},
            }
        }, status=status.HTTP_200_OK)


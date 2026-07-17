from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import UserStreak, DailyTarget

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_gamification_profiles(sender, instance, created, **kwargs):
    if created:
        UserStreak.objects.create(user=instance)
        DailyTarget.objects.create(user=instance)
        
        # Tạo ví coin cho user mới
        from .models import CoinWallet, UserLanguageLevel
        from .coin_service import CoinService
        CoinWallet.objects.create(user=instance, lang='zh', paid_balance=0)
        CoinWallet.objects.create(user=instance, lang='en', paid_balance=0)
        
        # Tạo level cho user mới
        UserLanguageLevel.objects.create(user=instance, lang='zh')
        UserLanguageLevel.objects.create(user=instance, lang='en')
        
        # Cấp initial coins của gói mặc định (Free)
        CoinService.apply_initial_coins(instance, 'Free')


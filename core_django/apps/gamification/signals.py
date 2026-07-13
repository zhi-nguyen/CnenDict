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
        from .models import CoinWallet, CoinConfig
        config = CoinConfig.objects.filter(tier='Free').first()
        initial_zh = config.initial_coins_zh if config else 0
        initial_en = config.initial_coins_en if config else 0
        CoinWallet.objects.create(user=instance, lang='zh', paid_balance=initial_zh)
        CoinWallet.objects.create(user=instance, lang='en', paid_balance=initial_en)


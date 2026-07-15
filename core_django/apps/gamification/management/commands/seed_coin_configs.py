"""
Management command: Seed/Update CoinConfig cho tất cả subscription tiers.

Usage:
    python manage.py seed_coin_configs
    python manage.py seed_coin_configs --dry-run
"""
from django.core.management.base import BaseCommand
from apps.gamification.models import CoinConfig


# ─── Dữ liệu seed chuẩn cho từng tier ───
# Cơ sở quy đổi: 5.000 VND = 10 Coin → 1 Coin ≈ 500 VND
COIN_CONFIG_SEED = [
    {
        'tier': 'Free',
        'weekly_refill_cap': 5,
        'initial_coins_zh': 0,
        'initial_coins_en': 0,
        'words_per_coin': 5,
        'daily_free_earn_limit': 20,
        'chat_create_cost': 5,
        'chat_message_cost': 1,
        'writing_base_cost_zh': 1,
        'writing_increment_cost_zh': 1,
        'writing_base_cost_en': 1,
        'writing_increment_cost_en': 1,
        'pdf_normal_export_cost': 2,
        'pdf_stroke_export_cost': 3,
    },
    {
        'tier': 'Plus',
        'weekly_refill_cap': 20,
        'initial_coins_zh': 10,
        'initial_coins_en': 10,
        'words_per_coin': 4,
        'daily_free_earn_limit': 50,
        'chat_create_cost': 3,
        'chat_message_cost': 1,
        'writing_base_cost_zh': 0,
        'writing_increment_cost_zh': 0,
        'writing_base_cost_en': 0,
        'writing_increment_cost_en': 0,
        'pdf_normal_export_cost': 2,
        'pdf_stroke_export_cost': 3,
    },
    {
        'tier': 'Pro',
        'weekly_refill_cap': 50,
        'initial_coins_zh': 30,
        'initial_coins_en': 30,
        'words_per_coin': 3,
        'daily_free_earn_limit': 100,
        'chat_create_cost': 2,
        'chat_message_cost': 1,
        'writing_base_cost_zh': 0,
        'writing_increment_cost_zh': 0,
        'writing_base_cost_en': 0,
        'writing_increment_cost_en': 0,
        'pdf_normal_export_cost': 2,
        'pdf_stroke_export_cost': 3,
    },
    {
        'tier': 'Premium',
        'weekly_refill_cap': 100,
        'initial_coins_zh': 50,
        'initial_coins_en': 50,
        'words_per_coin': 2,
        'daily_free_earn_limit': 0,  # 0 = Không giới hạn
        'chat_create_cost': 1,
        'chat_message_cost': 0,  # Premium chat miễn phí
        'writing_base_cost_zh': 0,
        'writing_increment_cost_zh': 0,
        'writing_base_cost_en': 0,
        'writing_increment_cost_en': 0,
        'pdf_normal_export_cost': 2,
        'pdf_stroke_export_cost': 3,
    },
]


class Command(BaseCommand):
    help = 'Seed hoặc cập nhật CoinConfig cho tất cả subscription tiers.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Chỉ hiển thị những thay đổi sẽ được thực hiện, không ghi vào DB.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('── DRY RUN MODE ── Không ghi vào database.\n'))

        for seed in COIN_CONFIG_SEED:
            tier = seed['tier']
            config_fields = {k: v for k, v in seed.items() if k != 'tier'}

            try:
                existing = CoinConfig.objects.get(tier=tier)
                # So sánh từng trường để phát hiện thay đổi
                changes = {}
                for field, new_val in config_fields.items():
                    old_val = getattr(existing, field)
                    if old_val != new_val:
                        changes[field] = (old_val, new_val)

                if changes:
                    self.stdout.write(f'\n📝 [{tier}] Cập nhật {len(changes)} trường:')
                    for field, (old, new) in changes.items():
                        self.stdout.write(f'   • {field}: {old} → {new}')

                    if not dry_run:
                        for field, (_, new_val) in changes.items():
                            setattr(existing, field, new_val)
                        existing.save()
                        self.stdout.write(self.style.SUCCESS(f'   ✅ Đã lưu.'))
                else:
                    self.stdout.write(f'\n✓ [{tier}] Không thay đổi.')

            except CoinConfig.DoesNotExist:
                self.stdout.write(f'\n🆕 [{tier}] Tạo mới:')
                for field, val in config_fields.items():
                    self.stdout.write(f'   • {field}: {val}')

                if not dry_run:
                    CoinConfig.objects.create(**seed)
                    self.stdout.write(self.style.SUCCESS(f'   ✅ Đã tạo.'))

        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING('── Kết thúc DRY RUN. Chạy lại không có --dry-run để áp dụng. ──'))
        else:
            self.stdout.write(self.style.SUCCESS('── Hoàn tất seed CoinConfig! ──'))

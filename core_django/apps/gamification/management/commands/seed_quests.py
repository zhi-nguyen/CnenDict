from django.core.management.base import BaseCommand
from apps.gamification.models import QuestDefinition, RewardItem


class Command(BaseCommand):
    help = 'Khởi tạo danh sách Nhiệm vụ mẫu (Daily, Weekly, Achievement) cho hệ thống Gamification'

    def handle(self, *args, **options):
        self.stdout.write("Bắt đầu seed dữ liệu Nhiệm Vụ (Quests)...")

        # Tìm một số RewardItem mẫu nếu có để gắn vào Achievement quests
        title_item = RewardItem.objects.filter(reward_type='title').first()
        frame_item = RewardItem.objects.filter(reward_type='avatar_frame').first()

        quest_data = [
            # ── 1. DAILY QUESTS (Hàng ngày) ──
            {
                'name': 'Khởi động từ vựng',
                'description': 'Học thuộc ít nhất 5 từ vựng mới trong flashcard hôm nay.',
                'icon': 'menu_book',
                'quest_type': 'daily',
                'lang': 'all',
                'trigger_type': 'study_words',
                'target_value': 5,
                'reward_exp': 50,
                'reward_coins': 2,
                'sort_order': 1,
            },
            {
                'name': 'Hoàn thành phiên học',
                'description': 'Luyện tập và hoàn tất trọn vẹn 1 phiên flashcard.',
                'icon': 'school',
                'quest_type': 'daily',
                'lang': 'all',
                'trigger_type': 'study_sessions',
                'target_value': 1,
                'reward_exp': 30,
                'reward_coins': 1,
                'sort_order': 2,
            },
            {
                'name': 'Đối thoại cùng AI',
                'description': 'Gửi 3 tin nhắn đàm thoại với AI Persona bất kỳ.',
                'icon': 'smart_toy',
                'quest_type': 'daily',
                'lang': 'all',
                'trigger_type': 'chat_messages',
                'target_value': 3,
                'reward_exp': 40,
                'reward_coins': 1,
                'sort_order': 3,
            },
            {
                'name': 'Chinh phục mục tiêu ngày',
                'description': 'Đạt chỉ tiêu học tập đề ra trong ngày.',
                'icon': 'flag',
                'quest_type': 'daily',
                'lang': 'all',
                'trigger_type': 'daily_target_met',
                'target_value': 1,
                'reward_exp': 60,
                'reward_coins': 3,
                'sort_order': 4,
            },
            {
                'name': 'Tích tiểu thành đại',
                'description': 'Thu thập được 5 Linh Thạch hoặc Coin từ việc học chăm chỉ.',
                'icon': 'savings',
                'quest_type': 'daily',
                'lang': 'all',
                'trigger_type': 'earn_coins',
                'target_value': 5,
                'reward_exp': 50,
                'reward_coins': 2,
                'sort_order': 5,
            },

            # ── 2. WEEKLY QUESTS (Hàng tuần) ──
            {
                'name': 'Chăm chỉ cả tuần',
                'description': 'Ghi nhớ thành công 50 từ vựng trong tuần.',
                'icon': 'auto_stories',
                'quest_type': 'weekly',
                'lang': 'all',
                'trigger_type': 'study_words',
                'target_value': 50,
                'reward_exp': 300,
                'reward_coins': 15,
                'sort_order': 1,
            },
            {
                'name': 'Chiến binh kiên trì',
                'description': 'Duy trì chuỗi học liên tiếp đạt ít nhất 5 ngày.',
                'icon': 'local_fire_department',
                'quest_type': 'weekly',
                'lang': 'all',
                'trigger_type': 'streak_days',
                'target_value': 5,
                'reward_exp': 400,
                'reward_coins': 20,
                'sort_order': 2,
            },
            {
                'name': 'Bậc thầy luyện tập',
                'description': 'Hoàn thành 10 phiên học flashcard trong tuần.',
                'icon': 'psychology',
                'quest_type': 'weekly',
                'lang': 'all',
                'trigger_type': 'study_sessions',
                'target_value': 10,
                'reward_exp': 350,
                'reward_coins': 15,
                'sort_order': 3,
            },

            # ── 3. ACHIEVEMENT QUESTS (Thành tựu tích lũy) ──
            {
                'name': 'Khởi đầu vững chắc',
                'description': 'Nâng cấp độ của bạn lên Level 5.',
                'icon': 'military_tech',
                'quest_type': 'achievement',
                'lang': 'all',
                'trigger_type': 'reach_level',
                'target_value': 5,
                'reward_exp': 500,
                'reward_coins': 25,
                'sort_order': 1,
            },
            {
                'name': 'Bác học nhí',
                'description': 'Tích lũy tổng cộng 200 từ vựng đã học thuộc.',
                'icon': 'workspace_premium',
                'quest_type': 'achievement',
                'lang': 'all',
                'trigger_type': 'study_words',
                'target_value': 200,
                'reward_exp': 1000,
                'reward_coins': 50,
                'reward_item': title_item,
                'reward_item_quantity': 1 if title_item else 0,
                'sort_order': 2,
            },
            {
                'name': 'Ngọn lửa bất diệt',
                'description': 'Duy trì chuỗi streak học tập đạt mốc 15 ngày liên tiếp.',
                'icon': 'whatshot',
                'quest_type': 'achievement',
                'lang': 'all',
                'trigger_type': 'streak_days',
                'target_value': 15,
                'reward_exp': 1500,
                'reward_coins': 75,
                'reward_item': frame_item,
                'reward_item_quantity': 1 if frame_item else 0,
                'sort_order': 3,
            },
            {
                'name': 'Đỉnh cao thông thạo',
                'description': 'Vượt qua mọi thử thách để đạt tới Level 10.',
                'icon': 'trophy',
                'quest_type': 'achievement',
                'lang': 'all',
                'trigger_type': 'reach_level',
                'target_value': 10,
                'reward_exp': 2000,
                'reward_coins': 100,
                'sort_order': 4,
            },
        ]

        created_count = 0
        updated_count = 0

        for item in quest_data:
            quest, created = QuestDefinition.objects.update_or_create(
                name=item['name'],
                quest_type=item['quest_type'],
                defaults=item
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seed Quests hoàn tất thành công! Tạo mới: {created_count}, Cập nhật: {updated_count}."
        ))

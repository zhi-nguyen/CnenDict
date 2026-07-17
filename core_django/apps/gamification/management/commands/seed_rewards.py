import re
import os
from django.core.management.base import BaseCommand
from apps.gamification.models import RewardItem, RewardRule

def slugify_filename(filename):
    name, ext = os.path.splitext(filename.lower())
    
    replacements = {
        'à':'a', 'á':'a', 'ả':'a', 'ã':'a', 'ạ':'a',
        'ă':'a', 'ằ':'a', 'ắ':'a', 'ẳ':'a', 'ẵ':'a', 'ặ':'a',
        'â':'a', 'ầ':'a', 'ấ':'a', 'ẩ':'a', 'ẫ':'a', 'ậ':'a',
        'đ':'d',
        'è':'e', 'é':'e', 'ẻ':'e', 'ẽ':'e', 'ẹ':'e',
        'ê':'e', 'ề':'e', 'ế':'e', 'ể':'e', 'ễ':'e', 'ệ':'e',
        'ì':'i', 'í':'i', 'ỉ':'i', 'ĩ':'i', 'ị':'i',
        'ò':'o', 'ó':'o', 'ỏ':'o', 'õ':'o', 'ọ':'o',
        'ô':'o', 'ồ':'o', 'ố':'o', 'ổ':'o', 'ỗ':'o', 'ộ':'o',
        'ơ':'o', 'ờ':'o', 'ớ':'o', 'ở':'o', 'ỡ':'o', 'ợ':'o',
        'ù':'u', 'ú':'u', 'ủ':'u', 'ũ':'u', 'ụ':'u',
        'ư':'u', 'ừ':'u', 'ứ':'u', 'ử':'u', 'ữ':'u', 'ự':'u',
        'ỳ':'y', 'ý':'y', 'ỷ':'y', 'ỹ':'y', 'ỵ':'y',
    }
    for k, v in replacements.items():
        name = name.replace(k, v)
        
    name = re.sub(r'[^a-z0-9]+', '-', name)
    name = name.strip('-')
    return f"{name}{ext}"

class Command(BaseCommand):
    help = 'Seed Level Up Reward Items and Rules for both ZH and EN'

    def handle(self, *args, **options):
        # Delete existing RewardRule and RewardItem objects to clear out old seed data
        self.stdout.write("Deleting existing RewardRule and RewardItem objects...")
        RewardRule.objects.all().delete()
        RewardItem.objects.all().delete()

        # 1. Define Reward Items
        items_data = [
            # --- CHINESE (ZH) TITLES ---
            {
                'name': 'Danh hiệu: Sơ Cấp (ZH)',
                'reward_type': 'title',
                'description': 'Danh hiệu sơ cấp dành cho người học tiếng Trung.',
                'title_text': 'Sơ Cấp (ZH)',
                'rarity': 'common',
                'ui_metadata': {
                    'text': 'Sơ Cấp (ZH)',
                    'style': {
                        'background': 'linear-gradient(135deg, #64748B 0%, #475569 100%)',
                        'color': '#FFFFFF',
                        'borderRadius': '4px',
                        'padding': '4px 10px',
                        'fontWeight': '800',
                        'textShadow': '0px 1px 2px rgba(0, 0, 0, 0.5)',
                        'boxShadow': '0px 2px 4px rgba(0, 0, 0, 0.1)',
                        'display': 'inline-block'
                    }
                }
            },
            {
                'name': 'Danh hiệu: Trung Cấp (ZH)',
                'reward_type': 'title',
                'description': 'Danh hiệu trung cấp dành cho người học tiếng Trung.',
                'title_text': 'Trung Cấp (ZH)',
                'rarity': 'rare',
                'ui_metadata': {
                    'text': 'Trung Cấp (ZH)',
                    'style': {
                        'background': 'linear-gradient(135deg, #10B981 0%, #059669 100%)',
                        'color': '#FFFFFF',
                        'borderRadius': '6px',
                        'padding': '4px 12px',
                        'fontWeight': '900',
                        'textShadow': '0px 2px 4px rgba(0, 0, 0, 0.4)',
                        'boxShadow': '0px 0px 8px rgba(16, 185, 129, 0.6), inset 0px 1px 1px rgba(255, 255, 255, 0.3)',
                        'display': 'inline-block'
                    }
                }
            },
            {
                'name': 'Danh hiệu: Cao Cấp (ZH)',
                'reward_type': 'title',
                'description': 'Danh hiệu cao cấp tối thượng dành cho bậc thầy tiếng Trung.',
                'title_text': 'Cao Cấp (ZH)',
                'rarity': 'legendary',
                'ui_metadata': {
                    'text': 'Cao Cấp (ZH)',
                    'style': {
                        'background': 'linear-gradient(90deg, #F59E0B 0%, #FFFBEB 50%, #F59E0B 100%)',
                        'backgroundSize': '200% auto',
                        'animation': 'shimmer 2s linear infinite',
                        'color': '#FFFFFF',
                        'borderRadius': '6px',
                        'padding': '5px 14px',
                        'fontWeight': '950',
                        'textShadow': '0px 0px 4px rgba(245, 158, 11, 0.8), 1px 1px 2px rgba(0, 0, 0, 0.6)',
                        'boxShadow': '0px 0px 15px rgba(245, 158, 11, 0.6), inset 0px 1px 2px rgba(255, 255, 255, 0.4)',
                        'border': '1px solid rgba(255, 255, 255, 0.4)',
                        'display': 'inline-block'
                    }
                }
            },

            # --- ENGLISH (EN) TITLES ---
            {
                'name': 'Danh hiệu: Sơ Cấp (EN)',
                'reward_type': 'title',
                'description': 'Danh hiệu sơ cấp dành cho người học tiếng Anh.',
                'title_text': 'Sơ Cấp (EN)',
                'rarity': 'common',
                'ui_metadata': {
                    'text': 'Sơ Cấp (EN)',
                    'style': {
                        'background': 'linear-gradient(135deg, #64748B 0%, #475569 100%)',
                        'color': '#FFFFFF',
                        'borderRadius': '4px',
                        'padding': '4px 10px',
                        'fontWeight': '800',
                        'textShadow': '0px 1px 2px rgba(0, 0, 0, 0.5)',
                        'boxShadow': '0px 2px 4px rgba(0, 0, 0, 0.1)',
                        'display': 'inline-block'
                    }
                }
            },
            {
                'name': 'Danh hiệu: Trung Cấp (EN)',
                'reward_type': 'title',
                'description': 'Danh hiệu trung cấp dành cho người học tiếng Anh.',
                'title_text': 'Trung Cấp (EN)',
                'rarity': 'rare',
                'ui_metadata': {
                    'text': 'Trung Cấp (EN)',
                    'style': {
                        'background': 'linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%)',
                        'color': '#FFFFFF',
                        'borderRadius': '6px',
                        'padding': '4px 12px',
                        'fontWeight': '900',
                        'textShadow': '0px 2px 4px rgba(0, 0, 0, 0.4)',
                        'boxShadow': '0px 0px 8px rgba(59, 130, 246, 0.6), inset 0px 1px 1px rgba(255, 255, 255, 0.3)',
                        'display': 'inline-block'
                    }
                }
            },
            {
                'name': 'Danh hiệu: Cao Cấp (EN)',
                'reward_type': 'title',
                'description': 'Danh hiệu cao cấp tối thượng dành cho bậc thầy tiếng Anh.',
                'title_text': 'Cao Cấp (EN)',
                'rarity': 'legendary',
                'ui_metadata': {
                    'text': 'Cao Cấp (EN)',
                    'style': {
                        'background': 'linear-gradient(90deg, #6366F1 0%, #EC4899 50%, #6366F1 100%)',
                        'backgroundSize': '200% auto',
                        'animation': 'shimmer 2s linear infinite',
                        'color': '#FFFFFF',
                        'borderRadius': '6px',
                        'padding': '5px 14px',
                        'fontWeight': '950',
                        'textShadow': '0px 0px 4px rgba(236, 72, 153, 0.8), 1px 1px 2px rgba(0, 0, 0, 0.6)',
                        'boxShadow': '0px 0px 15px rgba(139, 92, 246, 0.6), inset 0px 1px 2px rgba(255, 255, 255, 0.4)',
                        'border': '1px solid rgba(255, 255, 255, 0.4)',
                        'display': 'inline-block'
                    }
                }
            },
        ]

        # Define Level Reward Avatar Frames mapping to their original filenames
        level_frames = [
            {'name': 'Khung Avatar: Sơ Cấp (ZH)', 'file': 'socap_ZH_transparent.svg', 'rarity': 'common', 'desc': 'Khung avatar sơ cấp tiếng Trung nhận khi đạt cấp 10.'},
            {'name': 'Khung Avatar: Trung Cấp (ZH)', 'file': 'trungcap_Zh_transparent.svg', 'rarity': 'rare', 'desc': 'Khung avatar trung cấp tiếng Trung nhận khi đạt cấp 50.'},
            {'name': 'Khung Avatar: Cao Cấp (ZH)', 'file': 'caocap_Zh_transparent.svg', 'rarity': 'epic', 'desc': 'Khung avatar cao cấp tiếng Trung nhận khi đạt cấp 100.'},
            {'name': 'Khung Avatar: Sơ Cấp (EN)', 'file': 'socap_transparent.svg', 'rarity': 'common', 'desc': 'Khung avatar sơ cấp tiếng Anh nhận khi đạt cấp 10.'},
            {'name': 'Khung Avatar: Trung Cấp (EN)', 'file': 'trungcap_EN_transparent.svg', 'rarity': 'rare', 'desc': 'Khung avatar trung cấp tiếng Anh nhận khi đạt cấp 50.'},
            {'name': 'Khung Avatar: Cao Cấp (EN)', 'file': 'caocap_en_transparent.svg', 'rarity': 'epic', 'desc': 'Khung avatar cao cấp tiếng Anh nhận khi đạt cấp 100.'},
            {'name': 'Khung Avatar: Sơ Cấp (HSK)', 'file': 'socap_HSK_transparent.svg', 'rarity': 'common', 'desc': 'Khung sơ cấp chuyên dụng cho luyện thi HSK.'},
        ]

        # Remaining cosmetic frames in public/frames/
        cosmetic_frames_data = [
            {'file': 'Anh Đào và Cáo ST.svg', 'name': 'Anh Đào Hồ Ly', 'rarity': 'epic', 'desc': 'Khung cảnh hoa anh đào rơi cùng linh hồ quý phái.'},
            {'file': 'Chim Công H.svg', 'name': 'Lam Tước Khổng Tước', 'rarity': 'rare', 'desc': 'Bộ lông khổng tước kiêu sa đầy màu sắc.'},
            {'file': 'Chim Hạc HT.svg', 'name': 'Bạch Hạc Tiên Nhân', 'rarity': 'legendary', 'desc': 'Hạc tiên thanh cao cõi bồng lai cực phẩm.'},
            {'file': 'Cổng Toji H.svg', 'name': 'Thần Đạo Toji', 'rarity': 'rare', 'desc': 'Cổng đền truyền thống tĩnh mịch.'},
            {'file': 'Cổng Toji ST.svg', 'name': 'Thần Đạo Toji Linh Cảnh', 'rarity': 'epic', 'desc': 'Lối vào thần giới ngập tràn linh khí.'},
            {'file': 'Fox HT.svg', 'name': 'Cửu Vĩ Thiên Hồ', 'rarity': 'legendary', 'desc': 'Vua của muôn loài cáo - thần thú tối thượng.'},
            {'file': 'Fox ST.svg', 'name': 'Mộc Linh Hồ', 'rarity': 'epic', 'desc': 'Linh hồ bảo hộ khu rừng huyền bí.'},
            {'file': 'Hoa và Đèn ST.svg', 'name': 'Cổ Phong Hoa Đăng', 'rarity': 'epic', 'desc': 'Đèn lồng lung linh đón hội đêm trăng.'},
            {'file': 'Hoả Long HT.svg', 'name': 'Xích Long Phệ Thiên', 'rarity': 'legendary', 'desc': 'Hỏa long tôn nghiêm ngự trị vòm trời cao rộng.'},
            {'file': 'Hoả Long ST.svg', 'name': 'Xích Long Trảo', 'rarity': 'epic', 'desc': 'Ấn ký vuốt rồng lửa dũng mãnh.'},
            {'file': 'Huyết Long HT.svg', 'name': 'Huyết Long Thần', 'rarity': 'legendary', 'desc': 'Rồng máu thức tỉnh mang sức mạnh hủy thiên diệt địa.'},
            {'file': 'Hạc Vàng ST.svg', 'name': 'Hoàng Hạc Cánh Sen', 'rarity': 'epic', 'desc': 'Hạc vàng cất cánh trên đầm sen rực rỡ.'},
            {'file': 'Hạc Đỏ ST.svg', 'name': 'Đan Sa Bạch Hạc', 'rarity': 'epic', 'desc': 'Hạc tiên mang sắc đỏ đan sa cát tường.'},
            {'file': 'Hắc Long HT.svg', 'name': 'Ma Long Hắc Ám', 'rarity': 'legendary', 'desc': 'Sự thống trị tối tăm của rồng đen phương Bắc.'},
            {'file': 'Hắc Ám H.svg', 'name': 'Hắc Ám Tinh Vân', 'rarity': 'rare', 'desc': 'Vòng xoáy hắc ám dịu nhẹ.'},
            {'file': 'Hắc Ám HT.svg', 'name': 'Hắc Ám Vực Thẳm', 'rarity': 'legendary', 'desc': 'Nơi tối tăm sâu thẳm nhất của ma giới.'},
            {'file': 'Hắc Ám ST.svg', 'name': 'Hắc Ám Tinh Hồn', 'rarity': 'epic', 'desc': 'Linh hồn bóng tối cổ xưa.'},
            {'file': 'Phượng Hoàng HT.svg', 'name': 'Phượng Hoàng Bất Diệt', 'rarity': 'legendary', 'desc': 'Vương giả chi điểu hồi sinh từ đống tro tàn.'},
            {'file': 'Phượng Hoàng ST.svg', 'name': 'Phượng Hoàng Minh Ca', 'rarity': 'epic', 'desc': 'Tiếng hót lảnh lót của phượng hoàng lửa.'},
            {'file': 'Phố Cổ H.svg', 'name': 'Hoài Niệm Phố Cổ', 'rarity': 'rare', 'desc': 'Mái ngói rêu phong mang nét trầm mặc cổ kính.'},
            {'file': 'Phố Phở ST.svg', 'name': 'Phố Phở Kinh Kỳ', 'rarity': 'epic', 'desc': 'Mùi phở ấm lòng giữa khu phố cổ đông vui.'},
            {'file': 'Quạ Đen H.svg', 'name': 'Dạ Hành Quạ Đen', 'rarity': 'rare', 'desc': 'Quạ đêm mang điềm báo huyền bí.'},
            {'file': 'Quạ Đen HT.svg', 'name': 'Thần Quạ Hắc Tinh', 'rarity': 'legendary', 'desc': 'Vua quạ thống trị bóng đêm vĩnh hằng.'},
            {'file': 'Sakura H.svg', 'name': 'Sakura Lạc Hoa', 'rarity': 'rare', 'desc': 'Những cánh hoa đào nhẹ rơi theo gió xuân.'},
            {'file': 'Sakura ST.svg', 'name': 'Sakura Vũ Điệu', 'rarity': 'epic', 'desc': 'Vũ khúc anh đào nở rộ rực rỡ.'},
            {'file': 'Song Hạc ST.svg', 'name': 'Song Hạc Quy Sào', 'rarity': 'epic', 'desc': 'Cặp hạc tiên bay về tổ ấm cát tường.'},
            {'file': 'Song Phượng HT.svg', 'name': 'Song Phượng Triều Dương', 'rarity': 'legendary', 'desc': 'Hai phượng hoàng hướng về phía mặt trời thịnh vượng.'},
            {'file': 'Song phượng ST.svg', 'name': 'Song Phượng Hiến Thụy', 'rarity': 'epic', 'desc': 'Điềm lành cát tường từ cặp chim thần thoại.'},
            {'file': 'Sông Nước H.svg', 'name': 'Giang Thủy Phong Vân', 'rarity': 'rare', 'desc': 'Hơi thở dòng sông phẳng lặng trôi.'},
            {'file': 'Tam Thanh HT.svg', 'name': 'Tam Thanh Huyền Diệu', 'rarity': 'legendary', 'desc': 'Bảo ngọc chấn thế tụ hội linh khí Tam Thanh.'},
            {'file': 'Thanh Long HT.svg', 'name': 'Thanh Long Trấn Hải', 'rarity': 'legendary', 'desc': 'Thần long bảo vệ biển cả uy nghiêm vô song.'},
            {'file': 'Thiên Đường H.svg', 'name': 'Bồng Lai Tiên Cảnh', 'rarity': 'rare', 'desc': 'Mây khói hư ảo nơi chốn thần tiên.'},
            {'file': 'Thiên Đường HT.svg', 'name': 'Thiên Đường Đế Vương', 'rarity': 'legendary', 'desc': 'Ngai vàng bọc trong mây lành tối cao.'},
            {'file': 'Thiên Đường ST.svg', 'name': 'Thiên Đường Ảo Mộng', 'rarity': 'epic', 'desc': 'Cõi tiên mộng ảo lung linh sắc màu.'},
            {'file': 'Thiên Đạo HT.svg', 'name': 'Thiên Đạo Vô Song', 'rarity': 'legendary', 'desc': 'Chấp chưởng thiên mệnh tối thượng.'},
            {'file': 'Thánh Quang HT.svg', 'name': 'Thánh Quang Phổ Chiếu', 'rarity': 'legendary', 'desc': 'Ánh sáng thánh đức chiếu rọi vạn vật.'},
            {'file': 'Tím Mộng Mơ H.svg', 'name': 'Tử Linh Mộng Mơ', 'rarity': 'rare', 'desc': 'Huyền ảo sắc tím mộng mơ thanh nhã.'},
            {'file': 'Đèn và Quạt H.svg', 'name': 'Đông Phương Đăng Quạt', 'rarity': 'rare', 'desc': 'Sự kết hợp hoàn mỹ giữa quạt giấy và đèn lồng cổ.'},
        ]

        # Generate Level Reward items
        for lf in level_frames:
            slug_file = slugify_filename(lf['file'])
            items_data.append({
                'name': lf['name'],
                'reward_type': 'avatar_frame',
                'description': lf['desc'],
                'image_url': f"/frames/{slug_file}",
                'rarity': lf['rarity'],
                'ui_metadata': {
                    'frame_type': 'standard',
                    'assets': {
                        'overlay_svg_url': f"/frames/{slug_file}"
                    },
                    'style': {}
                }
            })

        # Generate Cosmetic Reward items
        for frame in cosmetic_frames_data:
            slug_file = slugify_filename(frame['file'])
            items_data.append({
                'name': f"Khung Avatar: {frame['name']}",
                'reward_type': 'avatar_frame',
                'description': frame['desc'],
                'image_url': f"/frames/{slug_file}",
                'rarity': frame['rarity'],
                'ui_metadata': {
                    'frame_type': 'standard',
                    'assets': {
                        'overlay_svg_url': f"/frames/{slug_file}"
                    },
                    'style': {}
                }
            })

        created_items = {}
        for item in items_data:
            obj, created = RewardItem.objects.update_or_create(
                name=item['name'],
                defaults={
                    'reward_type': item['reward_type'],
                    'description': item['description'],
                    'image_url': item.get('image_url', ''),
                    'title_text': item.get('title_text', ''),
                    'rarity': item['rarity'],
                    'ui_metadata': item.get('ui_metadata', {}),
                    'is_active': True
                }
            )
            created_items[item['name']] = obj
            action = 'Created' if created else 'Updated'
            self.stdout.write(f"{action} RewardItem: {obj.name}")

        # 2. Define Reward Rules (Level up rewards mapped specifically to level goals)
        rules_data = [
            # --- Chinese (ZH) Rules ---
            {'lang': 'zh', 'level': 10, 'item_name': 'Khung Avatar: Sơ Cấp (ZH)'},
            {'lang': 'zh', 'level': 10, 'item_name': 'Danh hiệu: Sơ Cấp (ZH)'},
            {'lang': 'zh', 'level': 50, 'item_name': 'Khung Avatar: Trung Cấp (ZH)'},
            {'lang': 'zh', 'level': 50, 'item_name': 'Danh hiệu: Trung Cấp (ZH)'},
            {'lang': 'zh', 'level': 100, 'item_name': 'Khung Avatar: Cao Cấp (ZH)'},
            {'lang': 'zh', 'level': 100, 'item_name': 'Danh hiệu: Cao Cấp (ZH)'},

            # --- English (EN) Rules ---
            {'lang': 'en', 'level': 10, 'item_name': 'Khung Avatar: Sơ Cấp (EN)'},
            {'lang': 'en', 'level': 10, 'item_name': 'Danh hiệu: Sơ Cấp (EN)'},
            {'lang': 'en', 'level': 50, 'item_name': 'Khung Avatar: Trung Cấp (EN)'},
            {'lang': 'en', 'level': 50, 'item_name': 'Danh hiệu: Trung Cấp (EN)'},
            {'lang': 'en', 'level': 100, 'item_name': 'Khung Avatar: Cao Cấp (EN)'},
            {'lang': 'en', 'level': 100, 'item_name': 'Danh hiệu: Cao Cấp (EN)'},
        ]

        for rule in rules_data:
            item_obj = created_items.get(rule['item_name'])
            if not item_obj:
                self.stderr.write(f"Item not found for rule: {rule['item_name']}")
                continue

            obj, created = RewardRule.objects.update_or_create(
                lang=rule['lang'],
                required_level=rule['level'],
                reward_item=item_obj,
                defaults={
                    'quantity': 1,
                    'is_active': True
                }
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(f"{action} RewardRule: LV{rule['level']} ({rule['lang']}) -> {item_obj.name}")

        self.stdout.write(self.style.SUCCESS('Successfully seeded all level rewards, rules, and remaining frames!'))

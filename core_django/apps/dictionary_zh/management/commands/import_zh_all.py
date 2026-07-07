import os
import json
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.dictionary_zh.models import ZhWord, ZhExample

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import all ZhWord and ZhExample data (HSK + outside HSK)'

    def add_arguments(self, parser):
        parser.add_argument('--hsk-path', type=str, required=True, help='Path to HSK folder')
        parser.add_argument('--parts-path', type=str, required=True, help='Path to cedict_parts folder')

    def handle(self, *args, **options):
        hsk_path = options['hsk_path']
        parts_path = options['parts_path']

        def get_toneless_pinyin(pinyin_str):
            if not pinyin_str:
                return ""
            replacements = {
                'ā': 'a', 'á': 'a', 'ǎ': 'a', 'à': 'a',
                'ē': 'e', 'é': 'e', 'ě': 'e', 'è': 'e',
                'ī': 'i', 'í': 'i', 'ǐ': 'i', 'ì': 'i',
                'ō': 'o', 'ó': 'o', 'ǒ': 'o', 'ò': 'o',
                'ū': 'u', 'ú': 'u', 'ǔ': 'u', 'ù': 'u',
                'ǖ': 'v', 'ǘ': 'v', 'ǚ': 'v', 'ǜ': 'v', 'ü': 'v'
            }
            res = pinyin_str.lower()
            for k, v in replacements.items():
                res = res.replace(k, v)
            return res

        # 1. Drop old data
        self.stdout.write(self.style.WARNING("Dropping all existing ZhWord and ZhExample data..."))
        with transaction.atomic():
            ZhWord.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Old data dropped successfully!"))

        total_words_imported = 0
        total_examples_imported = 0

        # Track composite key (word, pinyin, hsk_level)
        prepared_words = {}

        # 2. Process HSK files
        hsk_files = ["Hsk1.json", "Hsk2.json", "Hsk3.json", "Hsk4.json", "Hsk5.json", "Hsk6.json", "Hsk7-8-9.json"]
        self.stdout.write(self.style.NOTICE("Importing HSK files..."))
        
        for hsk_file in hsk_files:
            file_path = os.path.join(hsk_path, hsk_file)
            if not os.path.exists(file_path):
                self.stdout.write(self.style.WARNING(f"HSK file not found: {file_path}"))
                continue

            self.stdout.write(self.style.NOTICE(f"Processing {hsk_file}..."))
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            words_to_create = []
            examples_to_create = []

            for item in data:
                word_str = item.get("word", "")
                word_id = item.get("id")
                if not word_str or not word_id:
                    continue

                pinyin_str = item.get("pinyin", "")
                pos_list = item.get("part_of_speech", [])
                trans_vi = item.get("translation_vi", "")
                hsk_level_str = item.get("hsk_level", "")

                composite_key = (word_str.strip(), pinyin_str.strip().lower(), hsk_level_str.strip())
                if composite_key in prepared_words:
                    word_obj = prepared_words[composite_key]
                    existing_pos = set(word_obj.part_of_speech)
                    for pos in pos_list:
                        if pos not in existing_pos:
                            word_obj.part_of_speech.append(pos)
                    existing_trans = [t.strip().lower() for t in word_obj.translation_vi.split(',')]
                    new_trans = [t.strip() for t in trans_vi.split(',') if t.strip().lower() not in existing_trans]
                    if new_trans:
                        word_obj.translation_vi += ", " + ", ".join(new_trans)
                else:
                    toneless = get_toneless_pinyin(pinyin_str)
                    word_obj = ZhWord(
                        id=word_id,
                        word=word_str,
                        traditional=item.get("traditional", ""),
                        pinyin=pinyin_str,
                        toneless_pinyin=toneless,
                        han_viet=item.get("han_viet", ""),
                        translation_vi=trans_vi,
                        translation_en=item.get("translation_en", ""),
                        part_of_speech=pos_list,
                        hsk_level=hsk_level_str,
                        radical=item.get("radical", []),
                        stroke_number=item.get("stroke_number", []),
                        components=item.get("components", []),
                        synonyms=item.get("synonyms", []),
                        antonyms=item.get("antonyms", []),
                        tags=item.get("tags", []),
                        word_frequency=item.get("word_frequency", 0.0) or 0.0,
                        popularity_rank=item.get("popularity_rank", 0) or 0,
                        audio_url=item.get("audio_url", "")
                    )
                    words_to_create.append(word_obj)
                    prepared_words[composite_key] = word_obj

                for ex in item.get("examples", []):
                    examples_to_create.append(ZhExample(
                        word=word_obj,
                        chinese=ex.get("chinese", ""),
                        pinyin=ex.get("pinyin", ""),
                        vietnamese=ex.get("vietnamese", ""),
                        audio_url=ex.get("audio_url", "")
                    ))

            with transaction.atomic():
                if words_to_create:
                    ZhWord.objects.bulk_create(words_to_create, batch_size=1000, ignore_conflicts=True)
                    total_words_imported += len(words_to_create)
                if examples_to_create:
                    ZhExample.objects.bulk_create(examples_to_create, batch_size=2000, ignore_conflicts=True)
                    total_examples_imported += len(examples_to_create)

            self.stdout.write(self.style.SUCCESS(f"  -> Finished {hsk_file}"))

        # 3. Process Non-HSK parts
        self.stdout.write(self.style.NOTICE("Importing non-HSK parts..."))
        if os.path.exists(parts_path):
            part_files = sorted(
                [f for f in os.listdir(parts_path) if f.startswith("part_") and f.endswith(".json")],
                key=lambda x: int(x.split("_")[1].split(".")[0])
            )
            
            for part_file in part_files:
                file_path = os.path.join(parts_path, part_file)
                self.stdout.write(self.style.NOTICE(f"Processing {part_file}..."))
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                words_to_create = []
                examples_to_create = []

                for item in data:
                    word_str = item.get("word", "")
                    word_id = item.get("id")
                    if not word_str or not word_id:
                        continue

                    pinyin_str = item.get("pinyin", "")
                    pos_list = item.get("part_of_speech", [])
                    trans_vi = item.get("translation_vi", "")
                    hsk_level_str = item.get("hsk_level", "")

                    composite_key = (word_str.strip(), pinyin_str.strip().lower(), hsk_level_str.strip())
                    if composite_key in prepared_words:
                        word_obj = prepared_words[composite_key]
                        existing_pos = set(word_obj.part_of_speech)
                        for pos in pos_list:
                            if pos not in existing_pos:
                                word_obj.part_of_speech.append(pos)
                        existing_trans = [t.strip().lower() for t in word_obj.translation_vi.split(',')]
                        new_trans = [t.strip() for t in trans_vi.split(',') if t.strip().lower() not in existing_trans]
                        if new_trans:
                            word_obj.translation_vi += ", " + ", ".join(new_trans)
                    else:
                        toneless = get_toneless_pinyin(pinyin_str)
                        word_obj = ZhWord(
                            id=word_id,
                            word=word_str,
                            traditional=item.get("traditional", ""),
                            pinyin=pinyin_str,
                            toneless_pinyin=toneless,
                            han_viet=item.get("han_viet", ""),
                            translation_vi=trans_vi,
                            translation_en=item.get("translation_en", ""),
                            part_of_speech=pos_list,
                            hsk_level=hsk_level_str,
                            radical=item.get("radical", []),
                            stroke_number=item.get("stroke_number", []),
                            components=item.get("components", []),
                            synonyms=item.get("synonyms", []),
                            antonyms=item.get("antonyms", []),
                            tags=item.get("tags", []),
                            word_frequency=item.get("word_frequency", 0.0) or 0.0,
                            popularity_rank=item.get("popularity_rank", 0) or 0,
                            audio_url=item.get("audio_url", "")
                        )
                        words_to_create.append(word_obj)
                        prepared_words[composite_key] = word_obj

                    for ex in item.get("examples", []):
                        examples_to_create.append(ZhExample(
                            word=word_obj,
                            chinese=ex.get("chinese", ""),
                            pinyin=ex.get("pinyin", ""),
                            vietnamese=ex.get("vietnamese", ""),
                            audio_url=ex.get("audio_url", "")
                        ))

                with transaction.atomic():
                    if words_to_create:
                        ZhWord.objects.bulk_create(words_to_create, batch_size=1000, ignore_conflicts=True)
                        total_words_imported += len(words_to_create)
                    if examples_to_create:
                        ZhExample.objects.bulk_create(examples_to_create, batch_size=2000, ignore_conflicts=True)
                        total_examples_imported += len(examples_to_create)

                self.stdout.write(self.style.SUCCESS(f"  -> Finished {part_file}"))
        else:
            self.stdout.write(self.style.WARNING(f"Parts directory not found: {parts_path}"))

        self.stdout.write(self.style.SUCCESS(f"\nImport completed! Total words: {total_words_imported}. Total examples: {total_examples_imported}."))

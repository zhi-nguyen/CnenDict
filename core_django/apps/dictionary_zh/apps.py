from django.apps import AppConfig

class DictionaryZhConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.dictionary_zh'

    def ready(self):
        """Pre-load jieba dictionary to eliminate cold-start latency (~700ms)."""
        import jieba
        jieba.initialize()

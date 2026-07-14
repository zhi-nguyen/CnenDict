from rest_framework import generics
from rest_framework.response import Response
from django.core.cache import cache
import random

from .models import ZhWord
from .serializers import ZhCharacterBriefSerializer

class RadicalSearchView(generics.ListAPIView):
    """
    API endpoint để tìm tất cả các chữ Hán chứa một bộ thủ nhất định.
    Query params:
      - radical: Ký tự bộ thủ cần tìm (VD: 心, 氵, 扌)
    """
    serializer_class = ZhCharacterBriefSerializer
    pagination_class = None

    def list(self, request, *args, **kwargs):
        radical_char = request.query_params.get('radical', '').strip()
        if not radical_char:
            return Response({'results': []})

        # Check Redis Cache
        cache_key = f"zh:radical:{radical_char}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response({'results': cached_data})

        # Query Database
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        results = serializer.data

        # Cache results with jitter (12h to 12.5h)
        ttl = 12 * 3600 + random.randint(0, 1800)
        cache.set(cache_key, results, timeout=ttl)

        return Response({'results': results})

    def get_queryset(self):
        radical_char = self.request.query_params.get('radical', '').strip()
        if not radical_char:
            return ZhWord.objects.none()

        # Query sử dụng toán tử @> trong Postgres JSONB field thông qua __contains
        # annotation/filtering và sắp xếp theo độ phổ biến tăng dần (popularity_rank thấp hơn nghĩa là phổ biến hơn)
        return ZhWord.objects.filter(
            radical__contains=[radical_char]
        ).only(
            'id', 'word', 'traditional', 'pinyin', 'han_viet', 'translation_vi', 'radical', 'stroke_number', 'components', 'popularity_rank'
        ).order_by('popularity_rank')

import os
import requests
from django.core.cache import cache
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

class AzureSpeechTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # 1. Lấy thông tin cấu hình từ settings hoặc env (hỗ trợ cả hai bộ biến môi trường)
        azure_key = getattr(settings, 'AZURE_SPEECH_KEY', None) or os.getenv('AZURE_SPEECH_KEY')
        if not azure_key:
            azure_key = getattr(settings, 'AZURE_SPEECH_STUDIO_KEY', None) or os.getenv('AZURE_SPEECH_STUDIO_KEY')

        azure_raw_region = getattr(settings, 'AZURE_SPEECH_REGION', None) or os.getenv('AZURE_SPEECH_REGION')
        if not azure_raw_region:
            azure_raw_region = getattr(settings, 'AZURE_SPEECH_STUDIO_URL', None) or os.getenv('AZURE_SPEECH_STUDIO_URL')

        # Trích xuất region từ URL nếu đầu vào có dạng URL
        azure_region = None
        if azure_raw_region:
            if azure_raw_region.startswith("http://") or azure_raw_region.startswith("https://"):
                from urllib.parse import urlparse
                try:
                    hostname = urlparse(azure_raw_region).hostname
                    if hostname:
                        azure_region = hostname.split('.')[0]
                except Exception:
                    pass
            elif ".api.cognitive.microsoft" in azure_raw_region:
                azure_region = azure_raw_region.split('.')[0]
            else:
                azure_region = azure_raw_region
        
        # Lấy cấu hình mềm cho confidence threshold
        confidence_threshold = getattr(settings, 'AZURE_SPEECH_CONFIDENCE_THRESHOLD', None)
        if confidence_threshold is None:
            confidence_threshold = float(os.getenv('AZURE_SPEECH_CONFIDENCE_THRESHOLD', 0.55))

        if not azure_key or not azure_region:
            return Response(
                {"detail": "Azure Speech Service chưa được cấu hình ở Backend (thiếu Key hoặc Region/URL)."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 2. Kiểm tra token trong cache
        cache_key = 'azure_speech_token_cache'
        cached_data = cache.get(cache_key)
        
        if cached_data:
            return Response({
                "token": cached_data,
                "region": azure_region,
                "confidence_threshold": confidence_threshold
            }, status=status.HTTP_200_OK)

        # 3. Request token mới từ Azure STS
        sts_url = f"https://{azure_region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
        headers = {
            "Ocp-Apim-Subscription-Key": azure_key,
            "Content-Type": "application/x-www-form-urlencoded"
        }

        try:
            response = requests.post(sts_url, headers=headers, timeout=10)
            if response.status_code == 200:
                new_token = response.text
                # Cache token trong 9 phút (540 giây)
                cache.set(cache_key, new_token, 540)
                
                return Response({
                    "token": new_token,
                    "region": azure_region,
                    "confidence_threshold": confidence_threshold
                }, status=status.HTTP_200_OK)
            else:
                return Response(
                    {"detail": f"Không thể lấy token từ Azure. HTTP Status: {response.status_code}"},
                    status=status.HTTP_502_BAD_GATEWAY
                )
        except requests.exceptions.RequestException as e:
            return Response(
                {"detail": f"Lỗi kết nối Azure Speech Service: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY
            )

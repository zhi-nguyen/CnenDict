from django.urls import path
from .views import XiaoyueChatSendView, XiaoyueChatSulkingView, XiaoyueChatClearView

urlpatterns = [
    path('send/', XiaoyueChatSendView.as_view(), name='xiaoyue-chat-send'),
    path('sulking/', XiaoyueChatSulkingView.as_view(), name='xiaoyue-chat-sulking'),
    path('clear/', XiaoyueChatClearView.as_view(), name='xiaoyue-chat-clear'),
]

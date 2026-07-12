from django.urls import path
from .views import (
    XiaoyueChatSendView,
    XiaoyueChatSulkingView,
    XiaoyueChatClearView,
    XiaoyueChatPersonaView,
    XiaoyueChatHistoryView,
    XiaoyueChatPersonasListView,
)

urlpatterns = [
    path('send/', XiaoyueChatSendView.as_view(), name='xiaoyue-chat-send'),
    path('sulking/', XiaoyueChatSulkingView.as_view(), name='xiaoyue-chat-sulking'),
    path('clear/', XiaoyueChatClearView.as_view(), name='xiaoyue-chat-clear'),
    path('persona/', XiaoyueChatPersonaView.as_view(), name='xiaoyue-chat-persona'),
    path('personas/', XiaoyueChatPersonasListView.as_view(), name='xiaoyue-chat-personas-list'),
    path('history/', XiaoyueChatHistoryView.as_view(), name='xiaoyue-chat-history'),
]

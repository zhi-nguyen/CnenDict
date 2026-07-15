from django.urls import path
from .views import LeaderboardView

app_name = 'leaderboard'

urlpatterns = [
    path('', LeaderboardView.as_view(), name='leaderboard-get'),
]

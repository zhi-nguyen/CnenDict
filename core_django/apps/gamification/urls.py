from django.urls import path
from .views import (
    StreakView, TargetView, StudyHistoryLogView, ActivityHistoryView, GamificationDashboardView,
    CreateStudySessionView, FinishStudySessionView, WalletBalanceView, InitiateCoinPurchaseView,
    CoinConfigView, CoinPurchaseStatusView, AllCoinConfigsView,
    LevelInfoView, UserInventoryView, EquipInventoryItemView, RewardsPreviewView,
    ShopItemListView, PurchaseItemView
)

urlpatterns = [
    path('streaks/', StreakView.as_view(), name='my-streaks'),
    path('targets/', TargetView.as_view(), name='my-targets'),
    path('history/', StudyHistoryLogView.as_view(), name='log-history'),
    path('activities/', ActivityHistoryView.as_view(), name='my-activities'),
    path('dashboard/', GamificationDashboardView.as_view(), name='gamification-dashboard'),
    path('study-session/', CreateStudySessionView.as_view(), name='create-study-session'),
    path('study-session/<uuid:session_id>/finish/', FinishStudySessionView.as_view(), name='finish-study-session'),
    path('wallet/', WalletBalanceView.as_view(), name='wallet-balance'),
    path('wallet/purchase/', InitiateCoinPurchaseView.as_view(), name='initiate-coin-purchase'),
    path('coin-config/', CoinConfigView.as_view(), name='coin-config'),
    path('wallet/all-configs/', AllCoinConfigsView.as_view(), name='all-coin-configs'),
    path('wallet/purchase/<uuid:order_id>/', CoinPurchaseStatusView.as_view(), name='coin-purchase-status'),
    
    # Level & Inventory endpoints
    path('level/', LevelInfoView.as_view(), name='level-info-all'),
    path('level/<str:lang>/', LevelInfoView.as_view(), name='level-info-lang'),
    path('inventory/', UserInventoryView.as_view(), name='user-inventory'),
    path('inventory/<uuid:item_id>/equip/', EquipInventoryItemView.as_view(), name='equip-inventory-item'),
    path('rewards/preview/', RewardsPreviewView.as_view(), name='rewards-preview'),
    
    # Shop endpoints
    path('shop/items/', ShopItemListView.as_view(), name='shop-items'),
    path('shop/purchase/', PurchaseItemView.as_view(), name='shop-purchase'),
]



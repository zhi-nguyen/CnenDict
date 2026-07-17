from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser
from apps.gamification.models import UserLanguageLevel, UserInventory, CoinWallet

class UserLanguageLevelInline(admin.TabularInline):
    model = UserLanguageLevel
    extra = 0

class UserInventoryInline(admin.TabularInline):
    model = UserInventory
    extra = 0
    raw_id_fields = ('reward_item',)

class CoinWalletInline(admin.TabularInline):
    model = CoinWallet
    extra = 0

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active']
    fieldsets = UserAdmin.fieldsets + (
        ('Extra Info', {'fields': ('bio', 'avatar')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Extra Info', {'fields': ('bio', 'avatar')}),
    )
    inlines = [UserLanguageLevelInline, UserInventoryInline, CoinWalletInline]

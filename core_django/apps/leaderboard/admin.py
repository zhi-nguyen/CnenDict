from django.contrib import admin
from .models import LeaderboardSnapshot, LeaderboardEntry

class LeaderboardEntryInline(admin.TabularInline):
    model = LeaderboardEntry
    readonly_fields = ('user', 'rank', 'score', 'username', 'avatar_url')
    extra = 0
    can_delete = False

@admin.register(LeaderboardSnapshot)
class LeaderboardSnapshotAdmin(admin.ModelAdmin):
    list_display = ('id', 'board_type', 'lang', 'created_at')
    list_filter = ('board_type', 'lang', 'created_at')
    inlines = [LeaderboardEntryInline]

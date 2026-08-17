from django.dispatch import Signal

# Signal emitted when a user performs a tracked action.
# Providing args: user, trigger_type, amount, lang
quest_action_signal = Signal()

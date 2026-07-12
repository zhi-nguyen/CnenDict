from django.urls import path
from .views import GenerateExerciseView, CheckWritingView, CompleteExerciseView, CheckGeneralWritingView

urlpatterns = [
    path('exercises/', GenerateExerciseView.as_view(), name='generate_exercises'),
    path('exercises/complete/', CompleteExerciseView.as_view(), name='complete_exercise'),
    path('check-writing/', CheckWritingView.as_view(), name='check_writing'),
    path('check-general-writing/', CheckGeneralWritingView.as_view(), name='check_general_writing'),
]

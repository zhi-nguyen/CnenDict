from django.urls import path
from .views import (
    GenerateExerciseView,
    CheckWritingView,
    CompleteExerciseView,
    CheckGeneralWritingView,
    PendingWritingTasksView,
    WritingTaskDetailView,
)

urlpatterns = [
    path('exercises/', GenerateExerciseView.as_view(), name='generate_exercises'),
    path('exercises/complete/', CompleteExerciseView.as_view(), name='complete_exercise'),
    path('check-writing/', CheckWritingView.as_view(), name='check_writing'),
    path('check-general-writing/', CheckGeneralWritingView.as_view(), name='check_general_writing'),
    path('writing-tasks/pending/', PendingWritingTasksView.as_view(), name='pending_writing_tasks'),
    path('writing-tasks/<uuid:task_id>/', WritingTaskDetailView.as_view(), name='writing_task_detail'),
]

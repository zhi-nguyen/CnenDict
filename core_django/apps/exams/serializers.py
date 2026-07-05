from rest_framework import serializers
from .models import Exam, Section, Paragraph, Question, Option


class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ['id', 'option_id', 'text', 'image_url', 'image_description', 'ordering']


class ParagraphSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paragraph
        fields = ['id', 'paragraph_id', 'title', 'content', 'ordering']


class QuestionSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True, read_only=True)
    paragraph = ParagraphSerializer(read_only=True)

    class Meta:
        model = Question
        fields = [
            'id', 'question_id', 'question_type', 'difficulty', 'points', 'tags',
            'audio_url', 'audio_start_time', 'audio_end_time', 'audio_script',
            'question_text', 'image_url', 'image_description',
            'correct_answer', 'explanation', 'ordering', 'options', 'paragraph'
        ]


class SectionSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)
    paragraphs = ParagraphSerializer(many=True, read_only=True)

    class Meta:
        model = Section
        fields = [
            'id', 'section_id', 'section_name', 'part_number', 'instruction',
            'section_audio_url', 'ordering', 'questions', 'paragraphs'
        ]


class ExamSerializer(serializers.ModelSerializer):
    sections = SectionSerializer(many=True, read_only=True)

    class Meta:
        model = Exam
        fields = [
            'id', 'exam_id', 'exam_name', 'exam_version', 'level', 'language',
            'total_questions', 'total_time_minutes', 'total_score', 'passing_score',
            'allow_resume', 'max_attempts', 'shuffle_questions', 'shuffle_options',
            'show_explanation_after', 'status', 'created_at', 'sections'
        ]


class ExamListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exam
        fields = [
            'id', 'exam_id', 'exam_name', 'exam_version', 'level', 'language',
            'total_questions', 'total_time_minutes', 'total_score', 'passing_score',
            'status', 'created_at'
        ]

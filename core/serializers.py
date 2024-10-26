# core/serializers.py

from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    AuditLog, Notification, User, VendorProfile,
    CorporateQuestionStructure, CorporateQuestionnaire, CorporateQuestionnaireResponse,
    ContextualQuestion, ContextualQuestionChoice, ContextualQuestionnaire, 
    ContextualQuestionnaireResponse, ContextualRiskModifier,
    MainRiskFactor, SubRiskFactor, Question, QuestionChoice,
    RiskAssessmentQuestionnaire, RiskAssessmentResponse, DocumentSubmission,
    RATeamReview, ManualScore, RiskCalculation
)

# User and Profile Serializers
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'username', 'role')
        read_only_fields = ('id',)

class VendorProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = VendorProfile
        fields = '__all__'

class UserRegistrationSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('email', 'username', 'password', 'company_name')

    def create(self, validated_data):
        company_name = validated_data.pop('company_name')
        user = User.objects.create_user(
            role='Vendor',
            **validated_data
        )
        VendorProfile.objects.create(user=user, company_name=company_name)
        return user

# Corporate Questionnaire Serializers
class CorporateQuestionStructureSerializer(serializers.ModelSerializer):
    class Meta:
        model = CorporateQuestionStructure
        fields = '__all__'

class CorporateQuestionnaireResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = CorporateQuestionnaireResponse
        fields = ('id', 'question', 'response_text')

class CorporateQuestionnaireSerializer(serializers.ModelSerializer):
    responses = CorporateQuestionnaireResponseSerializer(many=True, read_only=True)
    
    class Meta:
        model = CorporateQuestionnaire
        fields = ('id', 'vendor', 'submission_date', 'status', 'progress', 'responses')
        read_only_fields = ('vendor', 'submission_date', 'progress')

# Contextual Questionnaire Serializers
class ContextualQuestionChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContextualQuestionChoice
        fields = ('id', 'text', 'modifier')

class ContextualQuestionSerializer(serializers.ModelSerializer):
    choices = ContextualQuestionChoiceSerializer(many=True, read_only=True)
    
    class Meta:
        model = ContextualQuestion
        fields = ('id', 'text', 'weight', 'order', 'choices')

class ContextualQuestionnaireResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContextualQuestionnaireResponse
        fields = ('id', 'question', 'selected_choice')

class ContextualQuestionnaireSerializer(serializers.ModelSerializer):
    responses = ContextualQuestionnaireResponseSerializer(many=True, read_only=True)
    
    class Meta:
        model = ContextualQuestionnaire
        fields = ('id', 'vendor', 'submission_date', 'status', 'progress', 'responses')
        read_only_fields = ('vendor', 'submission_date', 'progress')

class ContextualRiskModifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContextualRiskModifier
        fields = ('id', 'questionnaire', 'calculated_modifier')

# Risk Assessment Serializers
class QuestionChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionChoice
        fields = ('id', 'text', 'score')

class QuestionSerializer(serializers.ModelSerializer):
    choices = QuestionChoiceSerializer(many=True, read_only=True)
    
    class Meta:
        model = Question
        fields = ('id', 'text', 'type', 'weight', 'order', 'choices')

class SubRiskFactorSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)
    
    class Meta:
        model = SubRiskFactor
        fields = ('id', 'name', 'weight', 'order', 'questions')

class MainRiskFactorSerializer(serializers.ModelSerializer):
    sub_factors = SubRiskFactorSerializer(many=True, read_only=True)
    
    class Meta:
        model = MainRiskFactor
        fields = ('id', 'name', 'weight', 'order', 'sub_factors')

class DocumentSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentSubmission
        fields = ('id', 'question', 'file', 'upload_date')
        read_only_fields = ('upload_date',)

class RiskAssessmentResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskAssessmentResponse
        fields = ('id', 'question', 'response_text', 'selected_choice', 'yes_no_response')

class RiskAssessmentQuestionnaireSerializer(serializers.ModelSerializer):
    main_factors = MainRiskFactorSerializer(many=True, read_only=True, source='main_factors.all')
    responses = RiskAssessmentResponseSerializer(many=True, read_only=True)
    documents = DocumentSubmissionSerializer(many=True, read_only=True)
    
    class Meta:
        model = RiskAssessmentQuestionnaire
        fields = ('id', 'vendor', 'submission_date', 'status', 'progress', 'responses', 'documents')
        read_only_fields = ('vendor', 'submission_date', 'progress')

# RA Team Review Serializers
class ManualScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = ManualScore
        fields = ('id', 'question', 'score', 'comment')

class RATeamReviewSerializer(serializers.ModelSerializer):
    scores = ManualScoreSerializer(many=True, read_only=True)
    
    class Meta:
        model = RATeamReview
        fields = ('id', 'reviewer', 'questionnaire', 'status', 'overall_comments', 'review_date', 'scores')
        read_only_fields = ('reviewer', 'review_date')

# Risk Calculation Serializer
class RiskCalculationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskCalculation
        fields = '__all__'
        read_only_fields = ('calculation_date',)

# Add to core/serializers.py

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'
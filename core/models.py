# core/models.py

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator

class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=10,
        choices=[('Vendor', 'Vendor'), ('RA_Team', 'RA Team')],
        default='Vendor'
    )
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

class VendorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    company_name = models.CharField(max_length=200)
    industry_sector = models.CharField(max_length=100)
    company_size = models.CharField(max_length=50)
    primary_contact_name = models.CharField(max_length=100)
    primary_contact_phone = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.company_name} - {self.user.email}"
    
class BaseQuestionnaire(models.Model):
    progress = models.FloatField(default=0.0)
    last_modified = models.DateTimeField(auto_now=True)
    
    def calculate_progress(self):
        # Override in subclasses
        pass
    
    class Meta:
        abstract = True
    
class CorporateQuestionStructure(models.Model):
    section = models.CharField(max_length=100)
    question_text = models.TextField()
    order = models.IntegerField()

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.section} - {self.question_text}"

class CorporateQuestionnaire(BaseQuestionnaire):
    vendor = models.ForeignKey(User, on_delete=models.CASCADE)
    submission_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=[('In Progress', 'In Progress'), ('Submitted', 'Submitted')],
        default='In Progress'
    )
    progress = models.FloatField(default=0.0)

    def calculate_progress(self):
        total_questions = CorporateQuestionStructure.objects.count()
        answered = self.responses.count()
        self.progress = (answered / total_questions) * 100 if total_questions > 0 else 0
        self.save(update_fields=['progress'])
        return self.progress

    def __str__(self):
        return f"Corporate Questionnaire - {self.vendor.email}"

class CorporateQuestionnaireResponse(models.Model):
    questionnaire = models.ForeignKey(CorporateQuestionnaire, on_delete=models.CASCADE, related_name='responses')
    question = models.ForeignKey(CorporateQuestionStructure, on_delete=models.CASCADE)
    response_text = models.TextField()

    def __str__(self):
        return f"Response to {self.question.question_text}"
    
class ContextualQuestion(models.Model):
    text = models.TextField()
    weight = models.FloatField(help_text="Percentage weight in final calculation")
    order = models.IntegerField()

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.text} (Weight: {self.weight}%)"

class ContextualQuestionChoice(models.Model):
    question = models.ForeignKey(ContextualQuestion, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField(max_length=200)
    modifier = models.FloatField(help_text="Risk modifier percentage")

    def __str__(self):
        return f"{self.text} (Modifier: {self.modifier}%)"

class ContextualQuestionnaire(BaseQuestionnaire):
    vendor = models.ForeignKey(User, on_delete=models.CASCADE)
    submission_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=[('In Progress', 'In Progress'), ('Submitted', 'Submitted')],
        default='In Progress'
    )

    def calculate_progress(self):
        total_questions = ContextualQuestion.objects.count()
        answered = self.responses.count()
        self.progress = (answered / total_questions) * 100 if total_questions > 0 else 0
        self.save(update_fields=['progress'])
        return self.progress

    def __str__(self):
        return f"Contextual Questionnaire - {self.vendor.email}"

class ContextualQuestionnaireResponse(models.Model):
    questionnaire = models.ForeignKey(ContextualQuestionnaire, on_delete=models.CASCADE, related_name='responses')
    question = models.ForeignKey(ContextualQuestion, on_delete=models.CASCADE)
    selected_choice = models.ForeignKey(ContextualQuestionChoice, on_delete=models.CASCADE)

    def __str__(self):
        return f"Response to {self.question.text}"

class ContextualRiskModifier(models.Model):
    questionnaire = models.OneToOneField(ContextualQuestionnaire, on_delete=models.CASCADE)
    calculated_modifier = models.FloatField()

    def __str__(self):
        return f"Risk Modifier for {self.questionnaire.vendor.email}"
    
class MainRiskFactor(models.Model):
    name = models.CharField(max_length=200)
    weight = models.FloatField(help_text="Percentage of total risk score")
    order = models.IntegerField()

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.name} (Weight: {self.weight}%)"

class SubRiskFactor(models.Model):
    name = models.CharField(max_length=200)
    main_factor = models.ForeignKey(MainRiskFactor, on_delete=models.CASCADE, related_name='sub_factors')
    weight = models.FloatField(help_text="Percentage within main factor")
    order = models.IntegerField()

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.name} (Weight: {self.weight}% of {self.main_factor.name})"

class Question(models.Model):
    text = models.TextField()
    type = models.CharField(
        max_length=2,
        choices=[
            ('YN', 'Yes/No'),
            ('MC', 'Multiple Choice'),
            ('SA', 'Short Answer'),
            ('FU', 'File Upload')
        ]
    )
    sub_factor = models.ForeignKey(SubRiskFactor, on_delete=models.CASCADE, related_name='questions')
    weight = models.FloatField()
    order = models.IntegerField()

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.text} ({self.get_type_display()})"

class QuestionChoice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField(max_length=200)
    score = models.FloatField(help_text="Score between 0-10")

    def __str__(self):
        return f"{self.text} (Score: {self.score})"
    
class RiskAssessmentQuestionnaireManager(models.Manager):
    def get_pending_reviews(self):
        return self.filter(status='Submitted')
    
    def get_in_progress(self):
        return self.filter(status='In Progress')
    
    def get_completed(self):
        return self.filter(status='Completed')

class RiskAssessmentQuestionnaire(BaseQuestionnaire):
    objects = RiskAssessmentQuestionnaireManager()
    vendor = models.ForeignKey(User, on_delete=models.CASCADE)
    submission_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('In Progress', 'In Progress'),
            ('Submitted', 'Submitted'),
            ('Under Review', 'Under Review'),
            ('Completed', 'Completed')
        ],
        default='In Progress'
    )
    
    def calculate_progress(self):
        total_questions = Question.objects.count()
        answered = self.responses.count()
        self.progress = (answered / total_questions) * 100 if total_questions > 0 else 0
        self.save(update_fields=['progress'])
        return self.progress

    def __str__(self):
        return f"Risk Assessment - {self.vendor.email}"

class RiskAssessmentResponse(models.Model):
    questionnaire = models.ForeignKey(RiskAssessmentQuestionnaire, on_delete=models.CASCADE, related_name='responses')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    response_text = models.TextField(null=True, blank=True)
    selected_choice = models.ForeignKey(QuestionChoice, null=True, blank=True, on_delete=models.SET_NULL)
    yes_no_response = models.BooleanField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['questionnaire', 'question'])
        ]

    def __str__(self):
        return f"Response to {self.question.text}"

class DocumentSubmission(models.Model):
    questionnaire = models.ForeignKey(RiskAssessmentQuestionnaire, on_delete=models.CASCADE, related_name='documents')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    file = models.FileField(upload_to='submissions/')
    upload_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Document for {self.question.text}"

    def clean(self):
        if self.file.size > 5 * 1024 * 1024:  # 5MB limit
            raise ValidationError('File size cannot exceed 5MB')
        
class RATeamReview(models.Model):
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE)
    questionnaire = models.ForeignKey(RiskAssessmentQuestionnaire, on_delete=models.CASCADE, related_name='reviews')
    status = models.CharField(
        max_length=20,
        choices=[('In Progress', 'In Progress'), ('Completed', 'Completed')],
        default='In Progress'
    )
    overall_comments = models.TextField(blank=True)
    review_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review by {self.reviewer.email}"

class ManualScore(models.Model):
    review = models.ForeignKey(RATeamReview, on_delete=models.CASCADE, related_name='scores')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    score = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text="Score between 0-10"
    )
    comment = models.TextField(blank=True)

    def clean(self):
        if not 0 <= self.score <= 10:
            raise ValidationError("Score must be between 0 and 10")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class RiskCalculation(models.Model):
    questionnaire = models.OneToOneField(RiskAssessmentQuestionnaire, on_delete=models.CASCADE, related_name='risk_calculation')
    initial_score = models.FloatField()
    fuzzy_score = models.FloatField()
    weighted_score = models.FloatField()
    contextual_score = models.FloatField()
    final_score = models.FloatField()
    confidence_interval_low = models.FloatField()
    confidence_interval_high = models.FloatField()
    calculation_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Risk Calculation for {self.questionnaire.vendor.email}"
    
# Add audit logging
class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=50)
    model_type = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(null=True)

    class Meta:
        ordering = ['-timestamp']

# Add notification support
class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    message = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
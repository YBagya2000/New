# core/views.py

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework.permissions import AllowAny, IsAuthenticated, BasePermission
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .tasks import calculate_risk_async
from risk_assessment_system import settings
from .models import *
from .serializers import *

from django.http import JsonResponse

def custom_404(request, exception=None):
    return JsonResponse({
        'error': 'Resource not found',
        'status_code': 404
    }, status=404)

def custom_500(request):
    return JsonResponse({
        'error': 'Internal server error',
        'status_code': 500
    }, status=500)

# Custom Permissions
class IsVendor(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'Vendor'

class IsRATeam(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'RA_Team'

# Authentication Views
class RegisterView(APIView):
    permission_classes = (AllowAny,)

    @transaction.atomic
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                'user': UserSerializer(user).data,
                'message': 'User registered successfully'
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class LoginView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response(
                {'error': 'Please provide both email and password'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(email=email, password=password)

        if user is None:
            return Response(
                {'error': 'Invalid email or password'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {'error': 'User account is disabled'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        return Response({
            'user': UserSerializer(user).data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        })

# Vendor Dashboard View
class VendorDashboardView(APIView):
    permission_classes = (IsVendor,)

    def get(self, request):
        try:
            corporate = CorporateQuestionnaire.objects.filter(vendor=request.user).first()
            contextual = ContextualQuestionnaire.objects.filter(vendor=request.user).first()
            risk_assessment = RiskAssessmentQuestionnaire.objects.filter(vendor=request.user).first()
            
            assessment_status = {
                'corporate': {
                    'status': corporate.status if corporate else 'Not Started',
                    'progress': corporate.progress if corporate else 0
                },
                'contextual': {
                    'status': contextual.status if contextual else 'Not Started',
                    'progress': contextual.progress if contextual else 0
                },
                'risk_assessment': {
                    'status': risk_assessment.status if risk_assessment else 'Not Started',
                    'progress': risk_assessment.progress if risk_assessment else 0
                }
            }

            # Get risk score if assessment is completed
            risk_score = None
            if (risk_assessment and 
                risk_assessment.status == 'Completed' and 
                hasattr(risk_assessment, 'risk_calculation')):
                risk_score = RiskCalculationSerializer(
                    risk_assessment.risk_calculation
                ).data

            return Response({
                'assessment_status': assessment_status,
                'risk_score': risk_score
            })
            
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# Corporate Questionnaire Views
class CorporateQuestionnaireView(APIView):
    permission_classes = (IsVendor,)

    def get(self, request):
        # Get or create questionnaire
        questionnaire, created = CorporateQuestionnaire.objects.get_or_create(
            vendor=request.user,
            defaults={'status': 'In Progress'}
        )
        
        # Get all questions
        questions = CorporateQuestionStructure.objects.all().order_by('order')
        
        return Response({
            'questionnaire_id': questionnaire.id,
            'status': questionnaire.status,
            'progress': questionnaire.progress,
            'questions': CorporateQuestionStructureSerializer(questions, many=True).data
        })

    @transaction.atomic
    def post(self, request):
        questionnaire = get_object_or_404(
            CorporateQuestionnaire, 
            vendor=request.user
        )
        
        if questionnaire.status == 'Submitted':
            return Response(
                {'error': 'Questionnaire already submitted'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate and save responses
        responses = request.data.get('responses', [])
        for response_data in responses:
            question = get_object_or_404(
                CorporateQuestionStructure, 
                id=response_data.get('question_id')
            )
            
            response, created = CorporateQuestionnaireResponse.objects.update_or_create(
                questionnaire=questionnaire,
                question=question,
                defaults={'response_text': response_data.get('response_text')}
            )

        # Update progress
        total_questions = CorporateQuestionStructure.objects.count()
        answered_questions = questionnaire.responses.count()
        questionnaire.progress = (answered_questions / total_questions) * 100
        
        # If submitting final
        if request.data.get('submit', False):
            if answered_questions < total_questions:
                return Response(
                    {'error': 'All questions must be answered before submission'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            questionnaire.status = 'Submitted'
            
        questionnaire.save()

        return Response({
            'status': questionnaire.status,
            'progress': questionnaire.progress,
            'message': 'Responses saved successfully'
        })

# Contextual Questionnaire Views
class ContextualQuestionnaireView(APIView):
    permission_classes = (IsVendor,)

    def get(self, request):
        # Check if corporate questionnaire is completed
        corporate = CorporateQuestionnaire.objects.filter(
            vendor=request.user, 
            status='Submitted'
        ).exists()
        
        if not corporate:
            return Response(
                {'error': 'Please complete corporate questionnaire first'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get or create questionnaire
        questionnaire, created = ContextualQuestionnaire.objects.get_or_create(
            vendor=request.user,
            defaults={'status': 'In Progress'}
        )
        
        # Get all questions with choices
        questions = ContextualQuestion.objects.all().order_by('order')
        
        return Response({
            'questionnaire_id': questionnaire.id,
            'status': questionnaire.status,
            'progress': questionnaire.progress,
            'questions': ContextualQuestionSerializer(questions, many=True).data
        })

    @transaction.atomic
    def post(self, request):
        questionnaire = get_object_or_404(
            ContextualQuestionnaire, 
            vendor=request.user
        )
        
        if questionnaire.status == 'Submitted':
            return Response(
                {'error': 'Questionnaire already submitted'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Save responses and calculate modifier
        responses = request.data.get('responses', [])
        total_modifier = 0
        
        for response_data in responses:
            question = get_object_or_404(
                ContextualQuestion, 
                id=response_data.get('question_id')
            )
            choice = get_object_or_404(
                ContextualQuestionChoice, 
                id=response_data.get('choice_id')
            )
            
            response, created = ContextualQuestionnaireResponse.objects.update_or_create(
                questionnaire=questionnaire,
                question=question,
                defaults={'selected_choice': choice}
            )
            
            # Accumulate modifier
            total_modifier += (choice.modifier * question.weight / 100)

        # Update progress
        total_questions = ContextualQuestion.objects.count()
        answered_questions = questionnaire.responses.count()
        questionnaire.progress = (answered_questions / total_questions) * 100

        # If submitting final
        if request.data.get('submit', False):
            if answered_questions < total_questions:
                return Response(
                    {'error': 'All questions must be answered before submission'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            questionnaire.status = 'Submitted'
            
            # Save final risk modifier
            ContextualRiskModifier.objects.update_or_create(
                questionnaire=questionnaire,
                defaults={'calculated_modifier': total_modifier}
            )
            
        questionnaire.save()

        return Response({
            'status': questionnaire.status,
            'progress': questionnaire.progress,
            'calculated_modifier': total_modifier,
            'message': 'Responses saved successfully'
        })
    
# Risk Assessment Questionnaire Views
class RiskAssessmentQuestionnaireView(APIView):
    permission_classes = (IsVendor,)

    def get(self, request):
        # Verify previous questionnaires are completed
        if not ContextualQuestionnaire.objects.filter(
            vendor=request.user, 
            status='Submitted'
        ).exists():
            return Response(
                {'error': 'Please complete contextual questionnaire first'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get or create questionnaire
        questionnaire, created = RiskAssessmentQuestionnaire.objects.get_or_create(
            vendor=request.user,
            defaults={'status': 'In Progress'}
        )

        # Get hierarchical structure
        main_factors = MainRiskFactor.objects.all().order_by('order')

        return Response({
            'questionnaire_id': questionnaire.id,
            'status': questionnaire.status,
            'progress': questionnaire.progress,
            'main_factors': MainRiskFactorSerializer(main_factors, many=True).data
        })

    @transaction.atomic
    def post(self, request):
        questionnaire = get_object_or_404(
            RiskAssessmentQuestionnaire, 
            vendor=request.user
        )

        if questionnaire.status not in ['In Progress', 'Submitted']:
            return Response(
                {'error': 'Questionnaire cannot be modified in current state'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Process responses
        responses = request.data.get('responses', [])
        for response_data in responses:
            question = get_object_or_404(Question, id=response_data.get('question_id'))
            
            response_kwargs = {
                'questionnaire': questionnaire,
                'question': question
            }

            if question.type == 'YN':
                response_kwargs['yes_no_response'] = response_data.get('answer')
            elif question.type == 'MC':
                choice = get_object_or_404(
                    QuestionChoice, 
                    id=response_data.get('choice_id')
                )
                response_kwargs['selected_choice'] = choice
            elif question.type == 'SA':
                response_kwargs['response_text'] = response_data.get('answer')

            RiskAssessmentResponse.objects.update_or_create(
                questionnaire=questionnaire,
                question=question,
                defaults=response_kwargs
            )

        # Update progress
        total_questions = Question.objects.count()
        answered_questions = questionnaire.responses.count()
        questionnaire.progress = (answered_questions / total_questions) * 100

        # Handle submission
        if request.data.get('submit', False):
            if answered_questions < total_questions:
                return Response(
                    {'error': 'All questions must be answered before submission'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            questionnaire.status = 'Submitted'

        questionnaire.save()

        return Response({
            'status': questionnaire.status,
            'progress': questionnaire.progress,
            'message': 'Responses saved successfully'
        })

class DocumentUploadView(APIView):
    permission_classes = (IsVendor,)

    def post(self, request):
        questionnaire_id = request.data.get('questionnaire_id')
        question_id = request.data.get('question_id')
        file = request.FILES.get('file')

        if not all([questionnaire_id, question_id, file]):
            return Response(
                {'error': 'Missing required fields'},
                status=status.HTTP_400_BAD_REQUEST
            )

        questionnaire = get_object_or_404(
            RiskAssessmentQuestionnaire, 
            id=questionnaire_id,
            vendor=request.user
        )
        question = get_object_or_404(
            Question, 
            id=question_id, 
            type='FU'
        )

        try:
            # Validate file
            if file.size > settings.MAX_UPLOAD_SIZE:
                raise ValidationError('File size too large')

            ext = file.name.split('.')[-1].lower()
            if ext not in settings.ALLOWED_UPLOAD_TYPES:
                raise ValidationError('Invalid file type')

            document = DocumentSubmission.objects.create(
                questionnaire=questionnaire,
                question=question,
                file=file
            )

            return Response({
                'document_id': document.id,
                'file_name': file.name,
                'message': 'File uploaded successfully'
            })

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

# RA Team Views
class RATeamDashboardView(APIView):
    permission_classes = (IsRATeam,)

    def get(self, request):
        pending_submissions = RiskAssessmentQuestionnaire.objects.filter(
            status='Submitted'
        ).select_related('vendor__vendorprofile')

        return Response({
            'pending_reviews': [{
                'id': sub.id,
                'vendor_name': sub.vendor.vendorprofile.company_name,
                'submission_date': sub.submission_date,
                'status': sub.status
            } for sub in pending_submissions]
        })

class RATeamSubmissionView(APIView):
    permission_classes = (IsRATeam,)

    def get(self, request, submission_id):
        submission = get_object_or_404(
            RiskAssessmentQuestionnaire, 
            id=submission_id
        )

        # Get all questionnaire data
        response_data = {
            'vendor_info': VendorProfileSerializer(
                submission.vendor.vendorprofile
            ).data,
            'corporate_questionnaire': CorporateQuestionnaireSerializer(
                submission.vendor.corporatequestionnaire_set.first()
            ).data,
            'contextual_questionnaire': ContextualQuestionnaireSerializer(
                submission.vendor.contextualquestionnaire_set.first()
            ).data,
            'risk_assessment': RiskAssessmentQuestionnaireSerializer(
                submission
            ).data
        }

        return Response(response_data)

    @transaction.atomic
    def post(self, request, submission_id):
        submission = get_object_or_404(
            RiskAssessmentQuestionnaire, 
            id=submission_id
        )

        if submission.status != 'Submitted':
            return Response(
                {'error': 'Invalid submission status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create or update review
        review, created = RATeamReview.objects.get_or_create(
            reviewer=request.user,
            questionnaire=submission,
            defaults={'status': 'In Progress'}
        )

        # Process scores
        scores = request.data.get('scores', [])
        for score_data in scores:
            ManualScore.objects.update_or_create(
                review=review,
                question_id=score_data.get('question_id'),
                defaults={
                    'score': score_data.get('score'),
                    'comment': score_data.get('comment', '')
                }
            )

        # Handle review completion
        if request.data.get('complete', False):
            # Verify all required scores are provided
            required_questions = Question.objects.filter(
                type__in=['SA', 'FU']
            )
            scored_questions = review.scores.values_list('question_id', flat=True)

            if not all(q.id in scored_questions for q in required_questions):
                return Response(
                    {'error': 'All required questions must be scored'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            review.status = 'Completed'
            review.save()

            # Update submission status and trigger risk calculation
            submission.status = 'Under Review'
            submission.save()

            # Trigger async risk calculation
            calculate_risk_async.delay(submission.id)

        return Response({
            'status': review.status,
            'message': 'Review updated successfully'
        })

class RiskScoreView(APIView):
    def get(self, request, submission_id):
        submission = get_object_or_404(
            RiskAssessmentQuestionnaire,
            id=submission_id
        )

        # Check permission
        if not request.user.role == 'RA_Team' and request.user != submission.vendor:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )

        if not hasattr(submission, 'risk_calculation'):
            return Response(
                {'error': 'Risk calculation not completed'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            RiskCalculationSerializer(submission.risk_calculation).data
        )
    
# Add to core/views.py

class NotificationView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        notifications = Notification.objects.filter(
            recipient=request.user,
            read=False
        )
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data)

    def post(self, request, notification_id):
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            recipient=request.user
        )
        notification.read = True
        notification.save()
        return Response({'status': 'marked as read'})

class AuditLogView(APIView):
    permission_classes = (IsRATeam,)

    def get(self, request):
        logs = AuditLog.objects.all()
        if request.query_params.get('user'):
            logs = logs.filter(user_id=request.query_params['user'])
        serializer = AuditLogSerializer(logs, many=True)
        return Response(serializer.data)
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
from .tasks import calculate_risk
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
        # Validate sequence
        QuestionnaireSequenceValidator.validate_corporate_status(request.user)

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

class CorporateQuestionnaireSaveView(APIView):
    permission_classes = (IsVendor,)

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

        # Save responses
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
        questionnaire.save()

        return Response({
            'status': questionnaire.status,
            'progress': questionnaire.progress,
            'message': 'Responses saved successfully'
        })
        
class CorporateQuestionnaireSubmitView(APIView):
    permission_classes = (IsVendor,)

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

        # Save and validate responses
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

        # Validate all questions are answered
        total_questions = CorporateQuestionStructure.objects.count()
        answered_questions = questionnaire.responses.count()
        
        if answered_questions < total_questions:
            return Response(
                {'error': 'All questions must be answered before submission'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update status and progress
        questionnaire.progress = 100
        questionnaire.status = 'Submitted'
        questionnaire.save()

        return Response({
            'status': questionnaire.status,
            'progress': questionnaire.progress,
            'message': 'Questionnaire submitted successfully'
        })

# Contextual Questionnaire Views
# core/views.py

class ContextualQuestionnaireView(APIView):
    permission_classes = (IsVendor,)

    def validate_completion(self, questionnaire):
        """Validate all questions are answered"""
        total_questions = ContextualQuestion.objects.count()
        answered_questions = questionnaire.responses.count()
        return answered_questions >= total_questions

    def calculate_progress(self, questionnaire):
        """Calculate current progress percentage"""
        total_questions = ContextualQuestion.objects.count()
        answered_questions = questionnaire.responses.count()
        return (answered_questions / total_questions * 100) if total_questions > 0 else 0

    def calculate_risk_modifier(self, responses):
        """Calculate the total risk modifier from responses"""
        total_modifier = 0
        total_weight = 0

        for response in responses:
            question = response.question
            choice = response.selected_choice
            weighted_modifier = (choice.modifier * question.weight / 100)
            total_modifier += weighted_modifier
            total_weight += question.weight

        if total_weight == 0:
            raise ValidationError("Invalid weights in questionnaire")

        return total_modifier / total_weight

    def get(self, request, action=None):
        """Get questionnaire structure or current progress"""
        try:
            # Validate sequence
            QuestionnaireSequenceValidator.validate_contextual_status(request.user)

            # Get or create questionnaire
            questionnaire, created = ContextualQuestionnaire.objects.get_or_create(
                vendor=request.user,
                defaults={'status': 'In Progress'}
            )
            
            # Get all questions with choices
            questions = ContextualQuestion.objects.prefetch_related('choices').all().order_by('order')
            
            return Response({
                'questionnaire_id': questionnaire.id,
                'status': questionnaire.status,
                'progress': questionnaire.progress,
                'questions': ContextualQuestionSerializer(questions, many=True).data
            })
        except ValidationError as e:
            return Response(
                {'error': e.messages[0] if isinstance(e.messages, list) else str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @transaction.atomic
    def post(self, request, action=None):
        """Handle save and submit actions"""
        try:
            questionnaire = get_object_or_404(
                ContextualQuestionnaire, 
                vendor=request.user
            )
            
            if questionnaire.status == 'Submitted':
                return Response(
                    {'error': 'Questionnaire already submitted'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate and process responses
            responses = request.data.get('responses', [])
            if not responses:
                return Response(
                    {'error': 'No responses provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Process each response
            saved_responses = []
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
                saved_responses.append(response)

            # Calculate progress
            questionnaire.progress = self.calculate_progress(questionnaire)

            # Handle submit action
            if action == 'submit':
                if not self.validate_completion(questionnaire):
                    return Response(
                        {'error': 'All questions must be answered before submission'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Calculate final risk modifier
                risk_modifier = self.calculate_risk_modifier(saved_responses)
                
                # Create or update risk modifier record
                ContextualRiskModifier.objects.update_or_create(
                    questionnaire=questionnaire,
                    defaults={'calculated_modifier': risk_modifier}
                )

                # Update status
                questionnaire.status = 'Submitted'
                
            questionnaire.save()

            # Prepare response data
            response_data = {
                'status': questionnaire.status,
                'progress': questionnaire.progress,
                'message': 'Questionnaire submitted successfully' if action == 'submit' else 'Progress saved successfully'
            }

            # Include risk modifier if submitted
            if action == 'submit':
                response_data['calculated_modifier'] = risk_modifier

            return Response(response_data)

        except ValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': 'An unexpected error occurred', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
# Risk Assessment Questionnaire Views
class RiskAssessmentQuestionnaireView(APIView):
    permission_classes = (IsVendor,)

    def validate_request_data(self, request_data, questionnaire):
        """Validate request data for risk assessment questionnaire"""
        responses = request_data.get('responses', [])
        if not responses:
            raise ValidationError('Responses are required')

        for response_data in responses:
            if not response_data.get('question_id'):
                raise ValidationError('question_id is required for each response')
            
            try:
                question = Question.objects.get(id=response_data.get('question_id'))
            except Question.DoesNotExist:
                raise ValidationError(f'Invalid question_id: {response_data.get("question_id")}')

            # Validate answer based on question type
            answer = response_data.get('answer', {})
            if question.type == 'YN':
                if not isinstance(answer, bool):
                    raise ValidationError(f'Boolean answer required for question {question.id}')
            elif question.type == 'MC':
                if not response_data.get('choice_id'):
                    raise ValidationError(f'choice_id required for multiple choice question {question.id}')
                try:
                    QuestionChoice.objects.get(id=response_data.get('choice_id'), question=question)
                except QuestionChoice.DoesNotExist:
                    raise ValidationError(f'Invalid choice_id for question {question.id}')
            elif question.type == 'SA':
                if not isinstance(answer, str) or not answer.strip():
                    raise ValidationError(f'Text answer required for question {question.id}')
                
    def validate_prerequisites(self, user):
        if not user.corporatequestionnaire_set.filter(status='Submitted').exists():
            raise ValidationError("Complete corporate questionnaire first")
        if not user.contextualquestionnaire_set.filter(status='Submitted').exists():
            raise ValidationError("Complete contextual questionnaire first")


    def get(self, request, action=None):
        # Validate sequence
        QuestionnaireSequenceValidator.validate_risk_assessment_status(request.user)

        # Get or create questionnaire
        questionnaire, created = RiskAssessmentQuestionnaire.objects.get_or_create(
            vendor=request.user,
            defaults={'status': 'In Progress'}
        )

        # Get hierarchical structure
        main_factors = MainRiskFactor.objects.prefetch_related(
            'sub_factors__questions__choices'
        ).all().order_by('order')

        return Response({
            'questionnaire_id': questionnaire.id,
            'status': questionnaire.status,
            'progress': questionnaire.progress,
            'main_factors': MainRiskFactorSerializer(main_factors, many=True).data
        })

    @transaction.atomic
    def post(self, request, action=None):
        questionnaire = get_object_or_404(
            RiskAssessmentQuestionnaire, 
            vendor=request.user
        )

        if questionnaire.status not in ['In Progress']:
            return Response(
                {'error': 'Questionnaire cannot be modified in current state'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Validate request data
            self.validate_request_data(request.data, questionnaire)

            # Process responses
            responses = request.data.get('responses', [])
            for response_data in responses:
                question = get_object_or_404(
                    Question, 
                    id=response_data.get('question_id')
                )
                
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
                
                StatusTransitionValidator.validate_transition(
                    questionnaire, 
                    'Submitted'
                )
                questionnaire.status = 'Submitted'

            questionnaire.save()

            return Response({
                'status': questionnaire.status,
                'progress': questionnaire.progress,
                'message': 'Responses saved successfully'
            })

        except ValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': 'An unexpected error occurred'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DocumentUploadView(APIView):
    permission_classes = (IsVendor,)
    
    def validate_file(self, file):
        if file.size > settings.MAX_UPLOAD_SIZE:
            raise ValidationError('File size too large')
        
        ext = file.name.split('.')[-1].lower()
        if ext not in settings.ALLOWED_UPLOAD_TYPES:
            raise ValidationError('Invalid file type')

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
            self.validate_file(file)

            questionnaire = RiskAssessmentQuestionnaire.objects.get_or_create(
                id=questionnaire_id,
                vendor=request.user,
                defaults={'status': 'In Progress'}
            )[0]
            
            question = get_object_or_404(Question, id=question_id, type='FU')
            
            document = DocumentSubmission.objects.create(
                questionnaire=questionnaire,
                question=question,
                file=file
            )
            
            return Response({
                'document_id': document.id,
                'file_name': file.name,
                'file_url': document.file.url,
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

    def get(self, request, submission_id=None):
        if submission_id is None:
            # List view code remains the same...
            pass
        else:
            submission = get_object_or_404(
                RiskAssessmentQuestionnaire, 
                id=submission_id
            )

            # Get corporate questionnaire with full question data
            corporate_questionnaire = CorporateQuestionnaire.objects.filter(
                vendor=submission.vendor
            ).prefetch_related('responses__question').first()

            corporate_data = {
                'id': corporate_questionnaire.id,
                'vendor': corporate_questionnaire.vendor.id,
                'submission_date': corporate_questionnaire.submission_date,
                'status': corporate_questionnaire.status,
                'progress': corporate_questionnaire.progress,
                'responses': [{
                    'id': response.id,
                    'question': {
                        'id': response.question.id,
                        'text': response.question.question_text,
                        'section': response.question.section,
                        'order': response.question.order,
                    },
                    'response_text': response.response_text
                } for response in corporate_questionnaire.responses.all()]
            } if corporate_questionnaire else None

            # Get contextual questionnaire with full question data
            contextual_questionnaire = ContextualQuestionnaire.objects.filter(
                vendor=submission.vendor
            ).prefetch_related(
                'responses__question', 
                'responses__selected_choice'
            ).first()

            contextual_data = {
                'id': contextual_questionnaire.id,
                'vendor': contextual_questionnaire.vendor.id,
                'submission_date': contextual_questionnaire.submission_date,
                'status': contextual_questionnaire.status,
                'progress': contextual_questionnaire.progress,
                'responses': [{
                    'id': response.id,
                    'question': {
                        'id': response.question.id,
                        'text': response.question.text,
                        'weight': response.question.weight,
                    },
                    'selected_choice': {
                        'id': response.selected_choice.id,
                        'text': response.selected_choice.text,
                        'modifier': response.selected_choice.modifier,
                    } if response.selected_choice else None
                } for response in contextual_questionnaire.responses.all()],
                'calculated_modifier': getattr(
                    contextual_questionnaire.contextualriskmodifier,
                    'calculated_modifier',
                    None
                ) if contextual_questionnaire else None
            } if contextual_questionnaire else None

            # Rest of the response data structure...
            response_data = {
                'vendor_info': VendorProfileSerializer(
                    submission.vendor.vendorprofile
                ).data,
                'corporate_questionnaire': corporate_data,
                'contextual_questionnaire': contextual_data,
                'risk_assessment': {
                    'id': submission.id,
                    'status': submission.status,
                    'main_factors': MainRiskFactorSerializer(
                        MainRiskFactor.objects.prefetch_related(
                            'sub_factors__questions__choices'
                        ).all().order_by('order'),
                        many=True
                    ).data,
                    'responses': RiskAssessmentResponseSerializer(
                        submission.responses.all(), 
                        many=True
                    ).data,
                    'documents': DocumentSubmissionSerializer(
                        submission.documents.all(), 
                        many=True
                    ).data
                }
            }

            return Response(response_data)

    @transaction.atomic
    def post(self, request, submission_id, action=None):
        submission = get_object_or_404(
            RiskAssessmentQuestionnaire, 
            id=submission_id
        )

        if submission.status not in ['Submitted', 'Under Review']:
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

        # Handle scoring
        if action == 'score':
            scores = request.data.get('scores', [])
            
            # Validate scores
            for score_data in scores:
                if not all(k in score_data for k in ('question_id', 'score')):
                    return Response(
                        {'error': 'Invalid score data format'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                if not 0 <= float(score_data['score']) <= 10:
                    return Response(
                        {'error': 'Scores must be between 0 and 10'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Save scores
            for score_data in scores:
                ManualScore.objects.update_or_create(
                    review=review,
                    question_id=score_data['question_id'],
                    defaults={
                        'score': float(score_data['score']),
                        'comment': score_data.get('comment', '')
                    }
                )

            return Response({
                'status': 'scores_saved',
                'message': 'Scores saved successfully'
            })

        # Handle review completion
        elif action == 'complete':
            # Verify all required scores are provided
            questions_needing_scores = Question.objects.filter(
                type__in=['SA', 'FU'],
                sub_factor__main_factor__in=MainRiskFactor.objects.all()
            )
            
            existing_scores = ManualScore.objects.filter(
                review=review,
                question__in=questions_needing_scores
            )

            if existing_scores.count() < questions_needing_scores.count():
                return Response(
                    {'error': 'All manual scoring must be completed before review submission'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                # Update status
                submission.status = 'Under Review'
                submission.save()

                # Trigger risk calculation
                result = calculate_risk(submission_id)
                
                if not result.get('success', False):
                    raise Exception(result.get('error', 'Unknown error in risk calculation'))

                # Update submission status
                submission.status = 'Completed'
                submission.save()

                # Update review status
                review.status = 'Completed'
                review.save()

                return Response({
                    'status': 'completed',
                    'risk_calculation': {
                        'final_score': result['final_score'],
                        'confidence_interval': result['confidence_interval']
                    }
                })

            except Exception as e:
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(
            {'error': 'Invalid action'},
            status=status.HTTP_400_BAD_REQUEST
        )
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
    
class BaseQuestionnaireView(APIView):
    def validate_sequence(self, user):
        if self.questionnaire_type == 'contextual':
            if not CorporateQuestionnaire.objects.filter(
                vendor=user, 
                status='Submitted'
            ).exists():
                raise ValidationError('Complete corporate questionnaire first')
        elif self.questionnaire_type == 'risk_assessment':
            if not ContextualQuestionnaire.objects.filter(
                vendor=user, 
                status='Submitted'
            ).exists():
                raise ValidationError('Complete contextual questionnaire first')
            
# Add to views.py
class QuestionnaireSequenceValidator:
    @staticmethod
    def validate_corporate_status(vendor):
        """No prerequisites for corporate questionnaire"""
        pass

    @staticmethod
    def validate_contextual_status(vendor):
        """Check if corporate is completed before contextual"""
        if not CorporateQuestionnaire.objects.filter(
            vendor=vendor, 
            status='Submitted'
        ).exists():
            raise ValidationError(
                'Corporate questionnaire must be completed before starting contextual questionnaire'
            )

    @staticmethod
    def validate_risk_assessment_status(vendor):
        """Check if both corporate and contextual are completed"""
        if not CorporateQuestionnaire.objects.filter(
            vendor=vendor, 
            status='Submitted'
        ).exists():
            raise ValidationError(
                'Corporate questionnaire must be completed before risk assessment'
            )
            
        if not ContextualQuestionnaire.objects.filter(
            vendor=vendor, 
            status='Submitted'
        ).exists():
            raise ValidationError(
                'Contextual questionnaire must be completed before risk assessment'
            )

class StatusTransitionValidator:
    VALID_TRANSITIONS = {
        'CorporateQuestionnaire': {
            'In Progress': ['Submitted'],
            'Submitted': []  # End state
        },
        'ContextualQuestionnaire': {
            'In Progress': ['Submitted'],
            'Submitted': []  # End state
        },
        'RiskAssessmentQuestionnaire': {
            'In Progress': ['Submitted'],
            'Submitted': ['Under Review'],
            'Under Review': ['Completed'],
            'Completed': []  # End state
        }
    }

    @classmethod
    def validate_transition(cls, questionnaire, new_status):
        model_name = questionnaire.__class__.__name__
        current_status = questionnaire.status
        valid_transitions = cls.VALID_TRANSITIONS[model_name].get(current_status, [])
        
        if new_status not in valid_transitions:
            raise ValidationError(
                f'Invalid status transition from {current_status} to {new_status}'
            )
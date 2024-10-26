# core/utils.py (create if it doesn't exist)

from django.core.exceptions import ValidationError

from risk_assessment_system import settings

class QuestionnaireValidator:
    @staticmethod
    def validate_responses(responses, questionnaire_type):
        """Validate response data structure"""
        if not isinstance(responses, list):
            raise ValidationError('Responses must be a list')
        
        for response in responses:
            if not isinstance(response, dict):
                raise ValidationError('Each response must be an object')
            
            if 'question_id' not in response:
                raise ValidationError('Each response must have a question_id')
            
            if questionnaire_type == 'contextual' and 'choice_id' not in response:
                raise ValidationError('Each contextual response must have a choice_id')

    @staticmethod
    def validate_file_upload(file):
        """Validate file uploads"""
        if file.size > settings.MAX_UPLOAD_SIZE:
            raise ValidationError('File size exceeds maximum allowed')
        
        ext = file.name.split('.')[-1].lower()
        if ext not in settings.ALLOWED_UPLOAD_TYPES:
            raise ValidationError('File type not allowed')
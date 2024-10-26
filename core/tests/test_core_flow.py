# core/tests/test_core_flow.py

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from core.models import User, VendorProfile, CorporateQuestionnaire, ContextualQuestion, Question
from django.core.management import call_command
import json

class CoreFlowTests(TestCase):
    def setUp(self):
        # Create API client
        self.client = APIClient()
        
        # Load seed data
        call_command('seed_data')
        
        # Create vendor user
        self.vendor_data = {
            'username': 'testvendor',
            'email': 'vendor@test.com',
            'password': 'testpass123',
            'company_name': 'Test Company Inc'
        }
        
        # Register vendor
        register_response = self.client.post(
            reverse('core:register'),
            self.vendor_data
        )
        self.assertEqual(register_response.status_code, status.HTTP_201_CREATED)
        
        # Login to get token
        login_response = self.client.post(
            reverse('core:login'),
            {
                'email': self.vendor_data['email'],
                'password': self.vendor_data['password']
            }
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        
        self.vendor_token = login_response.data['tokens']['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.vendor_token}')
        
        # Store vendor user for later use
        self.vendor = User.objects.get(email=self.vendor_data['email'])
        
        # Get RA team member from seed data
        self.ra_team = User.objects.get(email='ra_team@example.com')

    def test_complete_assessment_flow(self):
        """Test the complete flow from vendor submission to RA team review"""
        
        # 1. Check Initial Dashboard
        response = self.client.get(reverse('core:vendor-dashboard'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 2. Corporate Questionnaire Flow
        # Get questions
        response = self.client.get(reverse('core:corporate-questionnaire'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        questions = response.data.get('questions', [])
        
        corporate_data = {
            'responses': [
                {
                    'question_id': question['id'],
                    'response_text': f'Test answer for {question["question_text"]}'
                }
                for question in questions
            ]
        }
        
        # Save progress first
        response = self.client.post(
            reverse('core:corporate-save'),
            corporate_data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Submit corporate questionnaire
        response = self.client.post(
            reverse('core:corporate-submit'),
            corporate_data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 3. Contextual Questionnaire Flow
        # Get questions
        response = self.client.get(reverse('core:contextual-questionnaire'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        contextual_data = {
            'responses': [
                {
                    'question_id': question['id'],
                    'choice_id': question['choices'][0]['id']
                }
                for question in response.data['questions']
            ]
        }

        # First save progress
        response = self.client.post(
            reverse('core:contextual-action', kwargs={'action': 'save'}),
            contextual_data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Then submit
        response = self.client.post(
            reverse('core:contextual-action', kwargs={'action': 'submit'}),
            contextual_data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('calculated_modifier', response.data)
        
        # 4. Risk Assessment Flow
        # Get questions
        response = self.client.get(reverse('core:risk-assessment'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Prepare responses for all question types
        risk_assessment_data = {
            'responses': []
        }
        
        for main_factor in response.data['main_factors']:
            for sub_factor in main_factor['sub_factors']:
                for question in sub_factor['questions']:
                    response_data = {
                        'question_id': question['id']
                    }
                    
                    if question['type'] == 'YN':
                        response_data['answer'] = True
                    elif question['type'] == 'MC':
                        response_data['choice_id'] = question['choices'][0]['id']
                    elif question['type'] == 'SA':
                        response_data['answer'] = f'Detailed answer for {question["text"]}'
                    # Note: File uploads will be handled separately
                    
                    risk_assessment_data['responses'].append(response_data)
        
        # Save progress first
        response = self.client.post(
            reverse('core:risk-assessment-save'),
            risk_assessment_data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Submit risk assessment
        risk_assessment_data['submit'] = True
        response = self.client.post(
            reverse('core:risk-assessment-submit'),
            risk_assessment_data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 5. RA Team Review Flow
        # Login as RA team
        ra_login_response = self.client.post(
            reverse('core:login'),
            {
                'email': 'ra_team@example.com',
                'password': 'rapass123'
            }
        )
        self.assertEqual(ra_login_response.status_code, status.HTTP_200_OK)
        ra_token = ra_login_response.data['tokens']['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {ra_token}')
        
        # Get pending submissions
        response = self.client.get(reverse('core:submissions-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data) > 0)
        
        submission_id = response.data[0]['id']
        
        # Get submission details
        response = self.client.get(
            reverse('core:submission-detail', kwargs={'submission_id': submission_id})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Prepare scoring data
        scoring_data = {
            'scores': [],
            'start_review': True
        }
        
        # Process questions that need manual scoring
        risk_assessment_data = response.data['risk_assessment']
        self.assertIn('main_factors', risk_assessment_data)

        for main_factor in risk_assessment_data['main_factors']:
            for sub_factor in main_factor['sub_factors']:
                for question in sub_factor['questions']:
                    if question['type'] in ['SA', 'FU']:
                        scoring_data['scores'].append({
                            'question_id': question['id'],
                            'score': 8,  # Example score
                            'comment': f'Good response to {question["text"]}'
                        })
        
        # Submit scores
        response = self.client.post(
            reverse('core:submission-score', kwargs={'submission_id': submission_id}),
            scoring_data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Complete review
        completion_data = {
            'complete': True
        }
        response = self.client.post(
            reverse('core:submission-complete', kwargs={'submission_id': submission_id}),
            completion_data,
            format='json'
        )
        
        if response.status_code != status.HTTP_200_OK:
            print(f"Error response: {response.data}")  # Debug info
            
        self.assertEqual(response.status_code, status.HTTP_200_OK)

         # After completing RA team review, add detailed analysis of the risk calculation:
        risk_score_response = self.client.get(
            reverse('core:risk-score', kwargs={'submission_id': submission_id})
        )
        self.assertEqual(risk_score_response.status_code, status.HTTP_200_OK)
        
        # Print detailed calculation results
        calculation = risk_score_response.data
        print("\n=== Risk Calculation Analysis ===")
        print(f"Initial Score: {calculation['initial_score']}")
        print(f"Fuzzy Score: {calculation['fuzzy_score']}")
        print(f"Weighted Score: {calculation['weighted_score']}")
        print(f"Contextual Score: {calculation['contextual_score']}")
        print(f"Final Score: {calculation['final_score']}")
        print(f"Confidence Interval: {calculation['confidence_interval_low']} - {calculation['confidence_interval_high']}")
        print("===============================\n")

        # Add assertions to verify score ranges
        self.assertGreaterEqual(calculation['final_score'], 0)
        self.assertLessEqual(calculation['final_score'], 10)
        self.assertGreater(calculation['confidence_interval_high'], calculation['confidence_interval_low'])
        
        # Add verification of calculation results
        risk_score_response = self.client.get(
            reverse('core:risk-score', kwargs={'submission_id': submission_id})
        )
        self.assertEqual(risk_score_response.status_code, status.HTTP_200_OK)
        self.assertIn('final_score', risk_score_response.data)
        
        # Verify score is within valid range
        final_score = risk_score_response.data['final_score']
        self.assertGreaterEqual(final_score, 0)
        self.assertLessEqual(final_score, 10)
        
        # Switch back to vendor and verify dashboard
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.vendor_token}')
        response = self.client.get(reverse('core:vendor-dashboard'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('risk_score', response.data)

    def test_invalid_submission_sequence(self):
        """Test that questionnaires must be completed in sequence"""
        
        # Try to access contextual before completing corporate
        response = self.client.get(reverse('core:contextual-questionnaire'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Corporate questionnaire must be completed', str(response.data['error']))
        
        # Try to access risk assessment before completing contextual
        response = self.client.get(reverse('core:risk-assessment'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Corporate questionnaire must be completed', str(response.data['error']))

    def test_invalid_ra_team_access(self):
        """Test RA team access restrictions"""
        
        # Try to access RA team endpoints as vendor
        response = self.client.get(reverse('core:submissions-list'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
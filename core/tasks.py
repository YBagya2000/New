# core/tasks.py

from celery import shared_task
from django.db import transaction
import numpy as np
from scipy import integrate
import logging
from .models import (
    RiskAssessmentQuestionnaire, RiskCalculation, ManualScore,
    MainRiskFactor, SubRiskFactor, Question, RiskAssessmentResponse,
    ContextualQuestionnaire, User
)
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

class FuzzyLogicProcessor:
    def __init__(self):
        self.risk_levels = ['VLR', 'LR', 'MR', 'HR', 'VHR']
        self.membership_functions = {
            'VLR': lambda x: self.trapezoidal(x, 8, 9, 10, 10),
            'LR': lambda x: self.triangular(x, 6, 7.5, 9),
            'MR': lambda x: self.triangular(x, 3, 5, 7),
            'HR': lambda x: self.triangular(x, 1, 2.5, 4),
            'VHR': lambda x: self.trapezoidal(x, 0, 0, 1, 2)
        }

    def trapezoidal(self, x, a, b, c, d):
        if a == b or c == d:
            return 0
        if x <= a or x >= d:
            return 0
        if b <= x <= c:
            return 1
        if a < x < b:
            return (x - a) / (b - a)
        return (d - x) / (d - c)

    def triangular(self, x, a, b, c):
        if a == b or b == c:
            return 0
        if x <= a or x >= c:
            return 0
        if a < x <= b:
            return (x - a) / (b - a)
        return (c - x) / (c - b)

    def process_manual_scores(self, questionnaire):
        """Process manually scored questions (SA and DS) using fuzzy logic"""
        manual_scores = {}
        
        for main_factor in MainRiskFactor.objects.all():
            main_factor_score = 0
            
            for sub_factor in SubRiskFactor.objects.filter(main_factor=main_factor):
                questions = Question.objects.filter(
                    sub_factor=sub_factor,
                    type__in=['SA', 'FU']  # Short Answer and File Upload
                )
                
                if not questions:
                    continue
                    
                question_weight = 1.0 / len(questions)  # Equal weight distribution
                sub_factor_score = 0
                
                for question in questions:
                    try:
                        manual_score = ManualScore.objects.get(
                            review__questionnaire=questionnaire,
                            question=question
                        )
                        
                        # Calculate fuzzy membership values
                        fuzzy_values = {
                            level: func(manual_score.score) 
                            for level, func in self.membership_functions.items()
                        }
                        
                        # Defuzzify to get crisp score
                        crisp_score = self.defuzzify(fuzzy_values)
                        sub_factor_score += crisp_score * question_weight
                        
                    except ManualScore.DoesNotExist:
                        logger.warning(f"No manual score found for question {question.id}")
                        continue
                
                # Apply sub-factor weight
                main_factor_score += sub_factor_score * sub_factor.weight
            
            # Apply main factor weight
            manual_scores[main_factor.id] = main_factor_score * main_factor.weight
        
        return manual_scores

    def defuzzify(self, fuzzy_values):
        """Defuzzify using centroid method"""
        numerator = sum(score * membership for score, membership in fuzzy_values.items())
        denominator = sum(fuzzy_values.values())
        return numerator / denominator if denominator else 0

def calculate_initial_score(questionnaire):
    """Calculate initial scores for Y/N and MC questions"""
    main_factor_scores = {}
    
    for main_factor in MainRiskFactor.objects.all():
        main_factor_score = 0
        
        for sub_factor in SubRiskFactor.objects.filter(main_factor=main_factor):
            questions = Question.objects.filter(
                sub_factor=sub_factor,
                type__in=['YN', 'MC']  # Yes/No and Multiple Choice
            )
            
            if not questions:
                continue
                
            question_weight = 1.0 / len(questions)  # Equal weight distribution
            sub_factor_score = 0
            
            for question in questions:
                try:
                    response = RiskAssessmentResponse.objects.get(
                        questionnaire=questionnaire,
                        question=question
                    )
                    
                    if question.type == 'YN':
                        score = 10 if response.yes_no_response else 0
                    else:  # MC
                        score = response.selected_choice.score if response.selected_choice else 0
                    
                    sub_factor_score += score * question_weight
                    
                except RiskAssessmentResponse.DoesNotExist:
                    logger.warning(f"No response found for question {question.id}")
                    continue
            
            # Apply sub-factor weight
            main_factor_score += sub_factor_score * sub_factor.weight
        
        # Apply main factor weight
        main_factor_scores[main_factor.id] = main_factor_score * main_factor.weight
    
    return sum(main_factor_scores.values())

def calculate_contextual_modifier(questionnaire):
    """Calculate risk modifier from contextual questionnaire"""
    try:
        contextual = ContextualQuestionnaire.objects.get(
            vendor=questionnaire.vendor,
            status='Submitted'
        )
        
        total_modifier = 0
        total_weight = 0
        
        for response in contextual.responses.all():
            question = response.question
            choice = response.selected_choice
            
            # Accumulate weighted modifier
            modifier = choice.modifier * question.weight
            total_modifier += modifier
            total_weight += question.weight
        
        if total_weight == 0:
            raise ValidationError("Invalid contextual questionnaire weights")
            
        return total_modifier / total_weight
        
    except ContextualQuestionnaire.DoesNotExist:
        raise ValidationError("Contextual questionnaire not completed")
    except Exception as e:
        raise Exception(f"Error calculating contextual modifier: {str(e)}")

def perform_monte_carlo(score, iterations=10000):
    """Perform Monte Carlo simulation for confidence interval"""
    try:
        # Generate samples around the score
        std_dev = 0.5  # Configurable standard deviation
        samples = np.random.normal(score, std_dev, iterations)
        
        # Clip values to valid range
        samples = np.clip(samples, 0, 10)
        
        # Calculate statistics
        mean_score = np.mean(samples)
        confidence_low = np.percentile(samples, 2.5)  # 95% confidence interval
        confidence_high = np.percentile(samples, 97.5)
        
        return mean_score, confidence_low, confidence_high
        
    except Exception as e:
        raise Exception(f"Error in Monte Carlo simulation: {str(e)}")

def combine_scores(initial_scores, manual_scores):
    """Combine initial and manual scores"""
    total_score = 0
    
    for main_factor in MainRiskFactor.objects.all():
        # Get both types of scores for this factor
        initial = initial_scores.get(main_factor.id, 0)
        manual = manual_scores.get(main_factor.id, 0)
        
        # Combine scores (could be weighted differently if needed)
        factor_score = initial + manual
        total_score += factor_score
    
    return total_score

@shared_task
def calculate_risk_async(questionnaire_id):
    """Asynchronous task to calculate risk score"""
    logger.info(f"Starting risk calculation for questionnaire {questionnaire_id}")
    
    try:
        with transaction.atomic():
            questionnaire = RiskAssessmentQuestionnaire.objects.get(id=questionnaire_id)
            
            # Verify questionnaire is ready for calculation
            if questionnaire.status != 'Under Review':
                raise ValidationError("Invalid questionnaire status for calculation")
            
            # 1. Calculate initial scores (Y/N and MC questions)
            logger.debug("Calculating initial scores...")
            initial_scores = calculate_initial_score(questionnaire)
            
            # 2. Process manual scores with fuzzy logic (SA and DS questions)
            logger.debug("Processing manual scores...")
            fuzzy_processor = FuzzyLogicProcessor()
            manual_scores = fuzzy_processor.process_manual_scores(questionnaire)
            
            # 3. Combine scores
            logger.debug("Combining scores...")
            base_score = combine_scores(initial_scores, manual_scores)
            
            # 4. Calculate and apply contextual modifier
            logger.debug("Applying contextual modifier...")
            contextual_modifier = calculate_contextual_modifier(questionnaire)
            adjusted_score = base_score * (1 + contextual_modifier)
            
            # 5. Perform Monte Carlo simulation
            logger.debug("Performing Monte Carlo simulation...")
            final_score, confidence_low, confidence_high = perform_monte_carlo(adjusted_score)
            
            # Save calculation results
            RiskCalculation.objects.update_or_create(
                questionnaire=questionnaire,
                defaults={
                    'initial_score': base_score,
                    'fuzzy_score': manual_scores,
                    'weighted_score': base_score,
                    'contextual_score': adjusted_score,
                    'final_score': final_score,
                    'confidence_interval_low': confidence_low,
                    'confidence_interval_high': confidence_high
                }
            )
            
            # Update questionnaire status
            questionnaire.status = 'Completed'
            questionnaire.save()
            
            # Notify relevant users
            logger.info(f"Risk calculation completed for questionnaire {questionnaire_id}")
            
            return True
            
    except ValidationError as e:
        logger.error(f"Validation error in risk calculation: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error in risk calculation: {str(e)}")
        raise
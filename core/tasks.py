# core/tasks.py

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
        self.risk_levels = {
            'VLR': 0,  # Very Low Risk
            'LR': 1,   # Low Risk
            'MR': 2,   # Moderate Risk
            'HR': 3,   # High Risk
            'VHR': 4   # Very High Risk
        }
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
        try:
            total_score = 0.0
            total_weight = 0.0
            
            manual_scores = ManualScore.objects.filter(
                review__questionnaire=questionnaire,
                question__type__in=['SA', 'FU']
            ).select_related('question', 'question__sub_factor', 'question__sub_factor__main_factor')
            
            if not manual_scores.exists():
                logger.warning(f"No manual scores found for questionnaire {questionnaire.id}")
                return 0.0

            for score in manual_scores:
                # Get weights
                main_factor_weight = float(score.question.sub_factor.main_factor.weight)
                sub_factor_weight = float(score.question.sub_factor.weight)
                
                # Calculate fuzzy value
                fuzzy_values = {
                    level: func(float(score.score)) 
                    for level, func in self.membership_functions.items()
                }
                
                # Defuzzify to get crisp score
                crisp_score = self.defuzzify(fuzzy_values)
                
                # Apply weights
                weighted_score = crisp_score * main_factor_weight * sub_factor_weight
                
                total_score += weighted_score
                total_weight += (main_factor_weight * sub_factor_weight)

                logger.debug(f"""
                    Processed manual score:
                    Question: {score.question.id}
                    Raw score: {score.score}
                    Crisp score: {crisp_score}
                    Weighted score: {weighted_score}
                """)
            
            final_score = total_score / total_weight if total_weight > 0 else 0.0
            return final_score
            
        except Exception as e:
            logger.error(f"Error processing manual scores: {str(e)}")
            raise ValueError(f"Error processing manual scores: {str(e)}")

    def defuzzify(self, fuzzy_values):
        """Defuzzify using centroid method"""
        try:
            # Convert fuzzy values to numeric scores
            numeric_values = {}
            for risk_level, membership in fuzzy_values.items():
                # Use center points for each risk level
                center_points = {
                    'VLR': 9.0,  # Center of VLR trapezoid
                    'LR': 7.5,   # Peak of LR triangle
                    'MR': 5.0,   # Peak of MR triangle
                    'HR': 2.5,   # Peak of HR triangle
                    'VHR': 1.0   # Center of VHR trapezoid
                }
                numeric_values[center_points[risk_level]] = float(membership)

            # Calculate centroid
            numerator = sum(score * membership for score, membership in numeric_values.items())
            denominator = sum(float(val) for val in numeric_values.values())
            
            if denominator == 0:
                return 5.0  # Default middle score if no membership values
                
            return numerator / denominator
            
        except Exception as e:
            logger.error(f"Defuzzification error: {str(e)}")
            raise ValueError(f"Error in defuzzification: {str(e)}")

def calculate_initial_score(questionnaire):
    """Calculate initial scores for Y/N and MC questions"""
    total_score = 0.0
    total_weight = 0.0
    
    for main_factor in MainRiskFactor.objects.all():
        main_factor_score = 0.0
        
        for sub_factor in SubRiskFactor.objects.filter(main_factor=main_factor):
            questions = Question.objects.filter(
                sub_factor=sub_factor,
                type__in=['YN', 'MC']  # Yes/No and Multiple Choice
            )
            
            if not questions:
                continue
                
            question_weight = 1.0 / len(questions) if questions else 0  # Equal weight distribution
            sub_factor_score = 0.0
            
            for question in questions:
                try:
                    response = RiskAssessmentResponse.objects.get(
                        questionnaire=questionnaire,
                        question=question
                    )
                    
                    if question.type == 'YN':
                        score = 10.0 if response.yes_no_response else 0.0
                    else:  # MC
                        score = float(response.selected_choice.score) if response.selected_choice else 0.0
                    
                    sub_factor_score += score * question_weight
                    
                except RiskAssessmentResponse.DoesNotExist:
                    logger.warning(f"No response found for question {question.id}")
                    continue
            
           # Apply sub-factor weight
            main_factor_score += sub_factor_score * float(sub_factor.weight)
            
        # Apply main factor weight
        total_score += main_factor_score * float(main_factor.weight)
        total_weight += float(main_factor.weight)
    
    return total_score / total_weight if total_weight > 0 else 0.0

def calculate_contextual_modifier(questionnaire):
    """Calculate risk modifier from contextual questionnaire"""
    try:
        contextual = ContextualQuestionnaire.objects.get(
            vendor=questionnaire.vendor,
            status='Submitted'
        )
        
        total_modifier = 0.0
        total_weight = 0.0
        
        for response in contextual.responses.all():
            question = response.question
            choice = response.selected_choice
            
            # Accumulate weighted modifier
            modifier = choice.modifier * question.weight
            total_modifier += modifier
            total_weight += question.weight
        
        if total_weight == 0.0:
            raise ValidationError("Invalid contextual questionnaire weights")
            
        return total_modifier / total_weight
        
    except ContextualQuestionnaire.DoesNotExist:
        raise ValidationError("Contextual questionnaire not completed")
    except Exception as e:
        raise Exception(f"Error calculating contextual modifier: {str(e)}")

def perform_monte_carlo(score, iterations=10000):
    """Perform Monte Carlo simulation for confidence interval"""
    try:
        # Ensure input score is float
        input_score = float(score)
        
        # Generate samples around the score
        std_dev = 0.5  # Configurable standard deviation
        
        # Use numpy for efficient computation
        import numpy as np
        samples = np.random.normal(input_score, std_dev, iterations)
        
        # Clip values to valid range [0, 10]
        samples = np.clip(samples, 0, 10)
        
        # Calculate statistics
        mean_score = float(np.mean(samples))
        confidence_low = float(np.percentile(samples, 2.5))  # 95% confidence interval
        confidence_high = float(np.percentile(samples, 97.5))
        
        logger.debug(f"""
            Monte Carlo simulation results:
            Input score: {input_score}
            Mean: {mean_score}
            Confidence interval: [{confidence_low}, {confidence_high}]
        """)
        
        return mean_score, confidence_low, confidence_high
        
    except Exception as e:
        logger.error(f"Monte Carlo simulation error: {str(e)}")
        raise ValueError(f"Error in Monte Carlo simulation: {str(e)}")

def combine_scores(initial_score, manual_scores):
    """Combine initial and manual scores"""
    try:
        # Ensure both scores are float values
        initial_score = float(initial_score)
        
        # If manual_scores is a dict, calculate weighted average
        if isinstance(manual_scores, dict):
            total_manual = sum(float(score) for score in manual_scores.values())
            num_scores = len(manual_scores)
            manual_avg = total_manual / num_scores if num_scores > 0 else 0
        else:
            manual_avg = float(manual_scores)
        
        # Equal weight to automatic and manual scores
        combined_score = (initial_score + manual_avg) / 2.0
        
        return max(0.0, min(10.0, combined_score))  # Ensure score is between 0 and 10
        
    except Exception as e:
        logger.error(f"Error combining scores: {str(e)}")
        raise ValueError(f"Error combining scores: {str(e)}")

def calculate_risk(questionnaire_id):
    logger.info(f"Starting risk calculation for questionnaire {questionnaire_id}")
    
    try:
        with transaction.atomic():
            questionnaire = RiskAssessmentQuestionnaire.objects.get(id=questionnaire_id)
            
            if questionnaire.status != 'Under Review':
                raise ValidationError("Invalid questionnaire status for calculation")
            
            # 1. Calculate initial scores
            initial_score = calculate_initial_score(questionnaire)
            logger.debug(f"Initial score calculated: {initial_score}")
            
            # 2. Process manual scores
            fuzzy_processor = FuzzyLogicProcessor()
            manual_score = fuzzy_processor.process_manual_scores(questionnaire)
            logger.debug(f"Manual score calculated: {manual_score}")
            
            # 3. Combine scores
            base_score = combine_scores(initial_score, manual_score)
            logger.debug(f"Combined base score: {base_score}")
            
            # 4. Calculate contextual modifier
            modifier = calculate_contextual_modifier(questionnaire)
            adjusted_score = base_score * (1 + modifier)
            logger.debug(f"Adjusted score with modifier: {adjusted_score}")
            
            # 5. Monte Carlo simulation
            final_score, conf_low, conf_high = perform_monte_carlo(adjusted_score)
            logger.debug(f"Final score after Monte Carlo: {final_score}")
            
            # Save results
            calculation = RiskCalculation.objects.create(
                questionnaire=questionnaire,
                initial_score=float(initial_score),
                fuzzy_score=float(manual_score),
                weighted_score=float(base_score),
                contextual_score=float(adjusted_score),
                final_score=float(final_score),
                confidence_interval_low=float(conf_low),
                confidence_interval_high=float(conf_high)
            )
            
            # Update status
            questionnaire.status = 'Completed'
            questionnaire.save()
            
            return {
                'success': True,
                'questionnaire_id': questionnaire_id,
                'final_score': final_score,
                'confidence_interval': {
                    'low': conf_low,
                    'high': conf_high
                }
            }
            
    except Exception as e:
        logger.error(f"Error in risk calculation: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
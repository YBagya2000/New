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
        """Process manually scored questions (SA and FU) using fuzzy logic"""
        try:
            total_score = 0.0
            total_weight = 0.0
            
            # Get manual scores directly from the database
            manual_scores = ManualScore.objects.filter(
                review__questionnaire=questionnaire,
                question__type__in=['SA', 'FU']
            ).select_related('question', 'question__sub_factor', 'question__sub_factor__main_factor')
            
            if not manual_scores.exists():
                logger.warning(f"No manual scores found for questionnaire {questionnaire.id}")
                return 0.0

            for score_obj in manual_scores:
                try:
                    # Get weights
                    main_factor_weight = float(score_obj.question.sub_factor.main_factor.weight)
                    sub_factor_weight = float(score_obj.question.sub_factor.weight)
                    
                    # Calculate fuzzy value for this score
                    fuzzy_values = {
                        level: func(float(score_obj.score)) 
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
                        Question: {score_obj.question.id}
                        Raw score: {score_obj.score}
                        Crisp score: {crisp_score}
                        Weighted score: {weighted_score}
                    """)
                except Exception as e:
                    logger.error(f"Error processing individual score: {str(e)}")
                    continue
            
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
        manual_scores = float(manual_scores)
        
        # If manual_scores is a dict, calculate weighted average
        if isinstance(manual_scores, dict):
            total_manual = sum(float(score) for score in manual_scores.values())
            num_scores = len(manual_scores)
            manual_avg = total_manual / num_scores if num_scores > 0 else 0
        else:
            # If it's a single value, ensure it's a float
            manual_avg = float(manual_scores.score if hasattr(manual_scores, 'score') else manual_scores)
        
        # Equal weight to automatic and manual scores
        combined_score = (initial_score + manual_avg) / 2.0
        
        return max(0.0, min(10.0, combined_score))  # Ensure score is between 0 and 10
        
    except Exception as e:
        logger.error(f"Error combining scores: {str(e)}")
        raise ValueError(f"Error combining scores: {str(e)}")

def calculate_risk(questionnaire_id):
    try:
        with transaction.atomic():
            questionnaire = RiskAssessmentQuestionnaire.objects.get(id=questionnaire_id)
            
            # Calculate initial scores
            initial_score = calculate_initial_score(questionnaire)
            manual_score = FuzzyLogicProcessor().process_manual_scores(questionnaire)  # Pass questionnaire object
            base_score = combine_scores(initial_score, manual_score)
            modifier = calculate_contextual_modifier(questionnaire)
            adjusted_score = base_score * (1 + modifier)
            final_score, conf_low, conf_high = perform_monte_carlo(adjusted_score)
            
            # Rest of the calculation remains the same...
            factor_scores = {}
            for main_factor in MainRiskFactor.objects.all():
                main_factor_score = 0
                sub_factors = {}
                
                for sub_factor in SubRiskFactor.objects.filter(main_factor=main_factor):
                    questions = Question.objects.filter(sub_factor=sub_factor)
                    sub_factor_score = 0
                    
                    for question in questions:
                        try:
                            response = RiskAssessmentResponse.objects.get(
                                questionnaire=questionnaire,
                                question=question
                            )
                            
                            if question.type == 'YN':
                                score = 10.0 if response.yes_no_response else 0.0
                            elif question.type == 'MC':
                                score = float(response.selected_choice.score) if response.selected_choice else 0.0
                            else:  # SA or FU
                                try:
                                    manual_score_obj = ManualScore.objects.get(
                                        review__questionnaire=questionnaire,
                                        question=question
                                    )
                                    score = float(manual_score_obj.score)
                                except ManualScore.DoesNotExist:
                                    score = 0.0
                            
                            sub_factor_score += score * float(question.weight)
                            
                        except RiskAssessmentResponse.DoesNotExist:
                            continue
                    
                    weighted_sub_factor_score = sub_factor_score * float(sub_factor.weight)
                    sub_factors[sub_factor.name] = {
                        'score': float(sub_factor_score),
                        'weight': float(sub_factor.weight),
                        'weighted_score': float(weighted_sub_factor_score)
                    }
                    main_factor_score += weighted_sub_factor_score
                
                weighted_main_factor_score = main_factor_score * float(main_factor.weight)
                factor_scores[main_factor.name] = {
                    'score': float(main_factor_score),
                    'weight': float(main_factor.weight),
                    'weighted_score': float(weighted_main_factor_score),
                    'sub_factors': sub_factors
                }

            calculation_stages = {
                'initial_scoring': {
                    'score': float(initial_score),
                    'description': 'Initial scoring of Yes/No and Multiple Choice questions',
                    'details': {
                        'yes_no_count': questionnaire.responses.filter(question__type='YN').count(),
                        'mc_count': questionnaire.responses.filter(question__type='MC').count()
                    }
                },
                'fuzzy_processing': {
                    'score': float(manual_score),
                    'description': 'Fuzzy logic processing of manual scores',
                    'details': {
                        'manual_scores_count': questionnaire.responses.filter(
                            question__type__in=['SA', 'FU']
                        ).count()
                    }
                },
                'weight_application': {
                    'score': float(base_score),
                    'description': 'Application of hierarchical weights',
                    'details': factor_scores
                },
                'contextual_adjustment': {
                    'score': float(adjusted_score),
                    'description': 'Adjustment based on contextual factors',
                    'details': {
                        'modifier': float(modifier)
                    }
                },
                'final_calculation': {
                    'score': float(final_score),
                    'description': 'Final score after Monte Carlo simulation',
                    'details': {
                        'confidence_interval': {
                            'low': float(conf_low),
                            'high': float(conf_high)
                        }
                    }
                }
            }

            # Create calculation record
            calculation = RiskCalculation.objects.create(
                questionnaire=questionnaire,
                initial_score=float(initial_score),
                fuzzy_score=float(manual_score),
                weighted_score=float(base_score),
                contextual_score=float(adjusted_score),
                final_score=float(final_score),
                confidence_interval_low=float(conf_low),
                confidence_interval_high=float(conf_high),
                factor_scores=factor_scores,
                calculation_stages=calculation_stages
            )
            
            return {
                'success': True,
                'final_score': float(final_score),
                'confidence_interval': {
                    'low': float(conf_low),
                    'high': float(conf_high)
                }
            }
            
    except Exception as e:
        logger.error(f"Error in risk calculation: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

    
def calculate_factor_scores(questionnaire):
    """Calculate detailed scores for each factor and sub-factor"""
    factor_scores = {}
        
    for main_factor in MainRiskFactor.objects.all():
        main_factor_score = 0
        sub_factors = {}
            
        for sub_factor in SubRiskFactor.objects.filter(main_factor=main_factor):
            # Get all questions for this sub-factor
            questions = Question.objects.filter(sub_factor=sub_factor)
            sub_factor_score = 0
            question_scores = {}
                
            for question in questions:
                try:
                    response = RiskAssessmentResponse.objects.get(
                        questionnaire=questionnaire,
                        question=question
                    )
                        
                    # Calculate score based on question type
                    if question.type == 'YN':
                        question_score = 10.0 if response.yes_no_response else 0.0
                    elif question.type == 'MC':
                        question_score = float(response.selected_choice.score) if response.selected_choice else 0.0
                    else:  # SA or FU
                        manual_score = ManualScore.objects.get(
                            review__questionnaire=questionnaire,
                            question=question
                        )
                        question_score = float(manual_score.score)
                        
                    # Store individual question score
                    question_scores[question.text] = {
                        'score': question_score,
                        'type': question.type,
                        'weight': float(question.weight)
                    }
                        
                    # Add weighted question score to sub-factor total
                    sub_factor_score += question_score * float(question.weight)
                        
                except (RiskAssessmentResponse.DoesNotExist, ManualScore.DoesNotExist):
                    logger.warning(f"No score found for question {question.id}")
                    continue
                
            # Average the sub-factor score if there were questions
            if questions:
                sub_factor_score = sub_factor_score / len(questions)
                    
            # Store sub-factor details
            sub_factors[sub_factor.name] = {
                'score': sub_factor_score,
                'weight': float(sub_factor.weight),
                'weighted_score': sub_factor_score * float(sub_factor.weight),
                'questions': question_scores
            }
                
            # Add weighted sub-factor score to main factor total
            main_factor_score += sub_factor_score * float(sub_factor.weight)
            
            # Store main factor details
            factor_scores[main_factor.name] = {
                'score': main_factor_score,
                'weight': float(main_factor.weight),
                'weighted_score': main_factor_score * float(main_factor.weight),
                'sub_factors': sub_factors
            }
        
    return factor_scores
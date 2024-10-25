# core/management/commands/seed_data.py

from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import (
    ContextualQuestion, ContextualQuestionChoice, CorporateQuestionStructure,
    MainRiskFactor, SubRiskFactor, Question, QuestionChoice,
    User, VendorProfile
)

class Command(BaseCommand):
    help = 'Seed initial data for risk assessment system'

    def handle(self, *args, **kwargs):
        try:
            with transaction.atomic():
                self.stdout.write('Starting data seeding...')
                
                # Create RA Team user first
                self.create_ra_team()
                
                # Seed all questionnaires
                self.seed_corporate_questions()
                self.seed_contextual_questions()
                self.seed_risk_assessment_questions()
                
                self.stdout.write(self.style.SUCCESS('Data seeding completed successfully'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error seeding data: {str(e)}'))
            raise e

    def create_ra_team(self):
        """Create initial RA team user"""
        self.stdout.write('Creating RA team user...')
        User.objects.create_user(
            username='ra_team',
            email='ra_team@example.com',
            password='rapass123',
            role='RA_Team'
        )
        self.stdout.write('Created RA team user')
        
    def seed_corporate_questions(self):
        """Seed the structure for corporate questionnaire"""
        self.stdout.write('Seeding corporate questionnaire structure...')
        
        # Define questions by section
        questions = {
            'Basic Information': [
                "Company name",
                "Industry sector",
                "Years in operation",
                "Primary service/product",
                "Company website"
            ],
            'Contact Details': [
                "Primary contact name",
                "Contact email",
                "Contact phone"
            ],
            'Compliance Overview': [
                "List of current certifications",
                "Key markets served"
            ]
        }
        
        # Create questions
        question_count = 0
        for section, section_questions in questions.items():
            for order, question_text in enumerate(section_questions, 1):
                CorporateQuestionStructure.objects.create(
                    section=section,
                    question_text=question_text,
                    order=order
                )
                question_count += 1
                self.stdout.write(f'  Created question: {question_text} in {section}')
        
        self.stdout.write(self.style.SUCCESS(f'Created {question_count} corporate questions'))

    def seed_contextual_questions(self):
        """Seed contextual questionnaire with weighted choices"""
        self.stdout.write('Seeding contextual questions...')
        
        # Service Maturity (20%)
        maturity = ContextualQuestion.objects.create(
            text="How long has your company been providing these services?",
            weight=20.0,
            order=1
        )
        ContextualQuestionChoice.objects.create(question=maturity, text="More than 10 years", modifier=-0.10)
        ContextualQuestionChoice.objects.create(question=maturity, text="5-10 years", modifier=-0.05)
        ContextualQuestionChoice.objects.create(question=maturity, text="3-5 years", modifier=0.00)
        ContextualQuestionChoice.objects.create(question=maturity, text="1-3 years", modifier=0.10)
        ContextualQuestionChoice.objects.create(question=maturity, text="Less than 1 year", modifier=0.20)

        # Service Criticality (25%)
        criticality = ContextualQuestion.objects.create(
            text="What level of service criticality do you typically support?",
            weight=25.0,
            order=2
        )
        ContextualQuestionChoice.objects.create(question=criticality, text="Mission-critical", modifier=0.20)
        ContextualQuestionChoice.objects.create(question=criticality, text="Business-critical", modifier=0.10)
        ContextualQuestionChoice.objects.create(question=criticality, text="Operational", modifier=0.00)
        ContextualQuestionChoice.objects.create(question=criticality, text="Support all levels", modifier=0.15)

        # Market Position (15%)
        position = ContextualQuestion.objects.create(
            text="How would you characterize your company's market position?",
            weight=15.0,
            order=3
        )
        ContextualQuestionChoice.objects.create(question=position, text="Major global provider", modifier=-0.15)
        ContextualQuestionChoice.objects.create(question=position, text="Regional leader", modifier=-0.05)
        ContextualQuestionChoice.objects.create(question=position, text="Specialized niche provider", modifier=0.05)
        ContextualQuestionChoice.objects.create(question=position, text="Emerging provider", modifier=0.15)

        # Geographic Distribution (10%)
        geography = ContextualQuestion.objects.create(
            text="In how many geographic regions do you operate?",
            weight=10.0,
            order=4
        )
        ContextualQuestionChoice.objects.create(question=geography, text="5 or more regions", modifier=-0.10)
        ContextualQuestionChoice.objects.create(question=geography, text="3-4 regions", modifier=-0.05)
        ContextualQuestionChoice.objects.create(question=geography, text="2 regions", modifier=0.05)
        ContextualQuestionChoice.objects.create(question=geography, text="1 region", modifier=0.15)

        # Financial Sector Experience (20%)
        experience = ContextualQuestion.objects.create(
            text="What percentage of your client base is from the financial sector?",
            weight=20.0,
            order=5
        )
        ContextualQuestionChoice.objects.create(question=experience, text="More than 50%", modifier=-0.15)
        ContextualQuestionChoice.objects.create(question=experience, text="25-50%", modifier=-0.10)
        ContextualQuestionChoice.objects.create(question=experience, text="10-25%", modifier=0.00)
        ContextualQuestionChoice.objects.create(question=experience, text="Less than 10%", modifier=0.10)

        # Service Model (10%)
        model = ContextualQuestion.objects.create(
            text="Which service model best describes your offering?",
            weight=10.0,
            order=6
        )
        ContextualQuestionChoice.objects.create(question=model, text="Managed service", modifier=-0.10)
        ContextualQuestionChoice.objects.create(question=model, text="Hybrid model", modifier=-0.05)
        ContextualQuestionChoice.objects.create(question=model, text="Self-service", modifier=0.05)
        ContextualQuestionChoice.objects.create(question=model, text="Custom model", modifier=0.00)

        self.stdout.write(self.style.SUCCESS('Created all contextual questions with weights'))

    def seed_risk_assessment_questions(self):
        """Seed the simplified 20-question risk assessment"""
        self.stdout.write('Seeding risk assessment questions...')

        # 1. Security Measures (35%)
        security = MainRiskFactor.objects.create(
            name="Security Measures",
            weight=0.35,
            order=1
        )

        # 1.1 Data Security (40%)
        data_security = SubRiskFactor.objects.create(
            name="Data Security",
            main_factor=security,
            weight=0.40,
            order=1
        )
        
        # Questions for Data Security
        Question.objects.create(
            text="Do you encrypt data at rest and in transit?",
            type="YN",
            sub_factor=data_security,
            weight=1/3,
            order=1
        )

        q2 = Question.objects.create(
            text="Which encryption standards do you use?",
            type="MC",
            sub_factor=data_security,
            weight=1/3,
            order=2
        )
        QuestionChoice.objects.bulk_create([
            QuestionChoice(question=q2, text="AES-256", score=10),
            QuestionChoice(question=q2, text="TLS 1.2+", score=8),
            QuestionChoice(question=q2, text="ChaCha20", score=6),
            QuestionChoice(question=q2, text="Other", score=4)
        ])

        Question.objects.create(
            text="Describe your key management process.",
            type="SA",
            sub_factor=data_security,
            weight=1/3,
            order=3
        )

        # 1.2 Access Management (30%)
        access_mgmt = SubRiskFactor.objects.create(
            name="Access Management",
            main_factor=security,
            weight=0.30,
            order=2
        )

        Question.objects.create(
            text="Do you implement MFA for all privileged accounts?",
            type="YN",
            sub_factor=access_mgmt,
            weight=0.5,
            order=1
        )

        q5 = Question.objects.create(
            text="What access control model do you use?",
            type="MC",
            sub_factor=access_mgmt,
            weight=0.5,
            order=2
        )
        QuestionChoice.objects.bulk_create([
            QuestionChoice(question=q5, text="Role-Based", score=10),
            QuestionChoice(question=q5, text="Attribute-Based", score=8),
            QuestionChoice(question=q5, text="Discretionary", score=6),
            QuestionChoice(question=q5, text="Other", score=4)
        ])

        # 1.3 Infrastructure Security (30%)
        infra_security = SubRiskFactor.objects.create(
            name="Infrastructure Security",
            main_factor=security,
            weight=0.30,
            order=3
        )

        Question.objects.create(
            text="Do you use IDS/IPS systems?",
            type="YN",
            sub_factor=infra_security,
            weight=1/3,
            order=1
        )

        Question.objects.create(
            text="Describe your network segmentation strategy.",
            type="SA",
            sub_factor=infra_security,
            weight=1/3,
            order=2
        )

        Question.objects.create(
            text="Please provide your security architecture document.",
            type="FU",
            sub_factor=infra_security,
            weight=1/3,
            order=3
        )

        # 2. Compliance & Regulations (25%)
        compliance = MainRiskFactor.objects.create(
            name="Compliance & Regulations",
            weight=0.25,
            order=2
        )

        # 2.1 Regulatory Compliance (60%)
        reg_compliance = SubRiskFactor.objects.create(
            name="Regulatory Compliance",
            main_factor=compliance,
            weight=0.60,
            order=1
        )

        q9 = Question.objects.create(
            text="Which regulations do you comply with?",
            type="MC",
            sub_factor=reg_compliance,
            weight=0.5,
            order=1
        )
        QuestionChoice.objects.bulk_create([
            QuestionChoice(question=q9, text="GDPR", score=2),
            QuestionChoice(question=q9, text="PCI DSS", score=2),
            QuestionChoice(question=q9, text="SOC 2", score=2),
            QuestionChoice(question=q9, text="ISO 27001", score=2),
            QuestionChoice(question=q9, text="HIPAA", score=2)
        ])

        q10 = Question.objects.create(
            text="When was your last compliance audit?",
            type="MC",
            sub_factor=reg_compliance,
            weight=0.5,
            order=2
        )
        QuestionChoice.objects.bulk_create([
            QuestionChoice(question=q10, text="Within 3 months", score=10),
            QuestionChoice(question=q10, text="3-6 months ago", score=7),
            QuestionChoice(question=q10, text="6-12 months ago", score=4),
            QuestionChoice(question=q10, text="Over 12 months", score=1)
        ])

        # 2.2 Data Governance (40%)
        data_gov = SubRiskFactor.objects.create(
            name="Data Governance",
            main_factor=compliance,
            weight=0.40,
            order=2
        )

        Question.objects.create(
            text="In which regions do you store data?",
            type="SA",
            sub_factor=data_gov,
            weight=0.5,
            order=1
        )

        Question.objects.create(
            text="Upload your data governance policy.",
            type="FU",
            sub_factor=data_gov,
            weight=0.5,
            order=2
        )

        # 3. Business Continuity (20%)
        continuity = MainRiskFactor.objects.create(
            name="Business Continuity",
            weight=0.20,
            order=3
        )

        # 3.1 Disaster Recovery (60%)
        dr = SubRiskFactor.objects.create(
            name="Disaster Recovery",
            main_factor=continuity,
            weight=0.60,
            order=1
        )

        q13 = Question.objects.create(
            text="How frequently do you perform DR tests?",
            type="MC",
            sub_factor=dr,
            weight=0.5,
            order=1
        )
        QuestionChoice.objects.bulk_create([
            QuestionChoice(question=q13, text="Monthly", score=10),
            QuestionChoice(question=q13, text="Quarterly", score=8),
            QuestionChoice(question=q13, text="Bi-annually", score=6),
            QuestionChoice(question=q13, text="Annually", score=4)
        ])

        Question.objects.create(
            text="Describe your DR process and RTOs.",
            type="SA",
            sub_factor=dr,
            weight=0.5,
            order=2
        )

        # 3.2 Service Availability (40%)
        availability = SubRiskFactor.objects.create(
            name="Service Availability",
            main_factor=continuity,
            weight=0.40,
            order=2
        )

        q15 = Question.objects.create(
            text="What is your guaranteed uptime?",
            type="MC",
            sub_factor=availability,
            weight=1.0,
            order=1
        )
        QuestionChoice.objects.bulk_create([
            QuestionChoice(question=q15, text="99.99%+", score=10),
            QuestionChoice(question=q15, text="99.9-99.98%", score=8),
            QuestionChoice(question=q15, text="99-99.89%", score=6),
            QuestionChoice(question=q15, text="Below 99%", score=4)
        ])

        # 4. Incident Management (10%)
        incident = MainRiskFactor.objects.create(
            name="Incident Management",
            weight=0.10,
            order=4
        )

        # 4.1 Incident Response (100%)
        incident_response = SubRiskFactor.objects.create(
            name="Incident Response",
            main_factor=incident,
            weight=1.00,
            order=1
        )

        Question.objects.create(
            text="Do you have an incident response plan?",
            type="YN",
            sub_factor=incident_response,
            weight=1/3,
            order=1
        )

        Question.objects.create(
            text="Upload your incident response plan.",
            type="FU",
            sub_factor=incident_response,
            weight=1/3,
            order=2
        )

        Question.objects.create(
            text="What is your target incident response time?",
            type="SA",
            sub_factor=incident_response,
            weight=1/3,
            order=3
        )

        # 5. Vendor Management (10%)
        vendor_mgmt = MainRiskFactor.objects.create(
            name="Vendor Management",
            weight=0.10,
            order=5
        )

        # 5.1 Third-Party Risk (100%)
        third_party = SubRiskFactor.objects.create(
            name="Third-Party Risk",
            main_factor=vendor_mgmt,
            weight=1.00,
            order=1
        )

        Question.objects.create(
            text="How do you assess third-party vendors?",
            type="SA",
            sub_factor=third_party,
            weight=0.5,
            order=1
        )

        Question.objects.create(
            text="Upload your vendor management policy.",
            type="FU",
            sub_factor=third_party,
            weight=0.5,
            order=2
        )

        self.stdout.write(self.style.SUCCESS('Created all risk assessment questions'))
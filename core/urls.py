# core/urls.py

from django.urls import path
from rest_framework import routers
from django.conf.urls.static import static
from django.conf import settings
from . import views

app_name = 'core'

# API Version
API_VERSION = 'v1'

urlpatterns = [
    # Authentication URLs
    path(f'{API_VERSION}/auth/register/', views.RegisterView.as_view(), name='register'),
    path(f'{API_VERSION}/auth/login/', views.LoginView.as_view(), name='login'),
    
    # Vendor Routes
    path(f'{API_VERSION}/vendor/dashboard/', 
        views.VendorDashboardView.as_view(), 
        name='vendor-dashboard'
    ),
    
    # Corporate Questionnaire
    path(f'{API_VERSION}/vendor/questionnaires/corporate/', 
        views.CorporateQuestionnaireView.as_view(), 
        name='corporate-questionnaire'
    ),
    path(f'{API_VERSION}/vendor/questionnaires/corporate/save/', 
        views.CorporateQuestionnaireView.as_view(), 
        {'action': 'save'},
        name='corporate-save'
    ),
    path(f'{API_VERSION}/vendor/questionnaires/corporate/submit/', 
        views.CorporateQuestionnaireView.as_view(), 
        {'action': 'submit'},
        name='corporate-submit'
    ),
    
    # Contextual Questionnaire
    path(f'{API_VERSION}/vendor/questionnaires/contextual/', 
        views.ContextualQuestionnaireView.as_view(), 
        name='contextual-questionnaire'
    ),
    path(f'{API_VERSION}/vendor/questionnaires/contextual/save/', 
        views.ContextualQuestionnaireView.as_view(), 
        {'action': 'save'},
        name='contextual-save'
    ),
    path(f'{API_VERSION}/vendor/questionnaires/contextual/submit/', 
        views.ContextualQuestionnaireView.as_view(), 
        {'action': 'submit'},
        name='contextual-submit'
    ),
    
    # Risk Assessment
    path(f'{API_VERSION}/vendor/questionnaires/risk-assessment/', 
        views.RiskAssessmentQuestionnaireView.as_view(), 
        name='risk-assessment'
    ),
    path(f'{API_VERSION}/vendor/questionnaires/risk-assessment/save/', 
        views.RiskAssessmentQuestionnaireView.as_view(), 
        {'action': 'save'},
        name='risk-assessment-save'
    ),
    path(f'{API_VERSION}/vendor/questionnaires/risk-assessment/submit/', 
        views.RiskAssessmentQuestionnaireView.as_view(), 
        {'action': 'submit'},
        name='risk-assessment-submit'
    ),
    
    # Document Upload
    path(f'{API_VERSION}/vendor/questionnaires/risk-assessment/upload/', 
        views.DocumentUploadView.as_view(), 
        name='document-upload'
    ),
    
    # RA Team Routes
    path(f'{API_VERSION}/ra-team/dashboard/', 
        views.RATeamDashboardView.as_view(), 
        name='ra-team-dashboard'
    ),
    path(f'{API_VERSION}/ra-team/submissions/', 
        views.RATeamSubmissionView.as_view(), 
        name='submissions-list'
    ),
    path(f'{API_VERSION}/ra-team/submissions/<int:submission_id>/', 
        views.RATeamSubmissionView.as_view(), 
        name='submission-detail'
    ),
    path(f'{API_VERSION}/ra-team/submissions/<int:submission_id>/score/', 
        views.RATeamSubmissionView.as_view(), 
        {'action': 'score'},
        name='submission-score'
    ),
    path(f'{API_VERSION}/ra-team/submissions/<int:submission_id>/complete/', 
        views.RATeamSubmissionView.as_view(), 
        {'action': 'complete'},
        name='submission-complete'
    ),
    # Risk Score
    path(f'{API_VERSION}/risk-scores/<int:submission_id>/', 
        views.RiskScoreView.as_view(), 
        name='risk-score'
    ),
    path(f'{API_VERSION}/notifications/', 
    views.NotificationView.as_view(), 
    name='notifications'
    ),
    path(f'{API_VERSION}/notifications/<int:notification_id>/read/', 
        views.NotificationView.as_view(), 
        name='mark-notification-read'
    ),

    # Audit log endpoints
    path(f'{API_VERSION}/audit-logs/', 
        views.AuditLogView.as_view(), 
        name='audit-logs'
    ),
]

# Add URLs for serving media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Custom 404 and 500 handlers
handler404 = 'core.views.custom_404'
handler500 = 'core.views.custom_500'
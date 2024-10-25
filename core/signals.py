# Add new file: core/signals.py

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import *

@receiver(post_save, sender=RiskAssessmentQuestionnaire)
def notify_ra_team_new_submission(sender, instance, created, **kwargs):
    if created and instance.status == 'Submitted':
        ra_team = User.objects.filter(role='RA_Team')
        for user in ra_team:
            Notification.objects.create(
                recipient=user,
                title='New Submission',
                message=f'New risk assessment submission from {instance.vendor.vendorprofile.company_name}'
            )

@receiver([post_save, post_delete], sender=RiskAssessmentQuestionnaire)
def create_audit_log(sender, instance, **kwargs):
    if kwargs.get('created', False):
        action = 'created'
    elif 'deleted' in kwargs:
        action = 'deleted'
    else:
        action = 'updated'
        
    AuditLog.objects.create(
        user=instance.vendor,
        action=action,
        model_type='RiskAssessment',
        object_id=instance.id,
        details={'status': instance.status}
    )
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import (
    User, AdminProfile, StaffProfile, TutorProfile, 
    CompanyProfile, StudentProfile, StaffPermission
)


@receiver(post_save, sender=User)
def create_profile_and_permissions(sender, instance, created, **kwargs):
    """
    Auto-create profiles and permissions when user is created
    """
    if created:
        profile_map = {
            'super_admin': AdminProfile,
            'admin': AdminProfile,
            'staff': StaffProfile,
            'tutor': TutorProfile,
            'company': CompanyProfile,
            'student': StudentProfile,
        }
        
        ProfileModel = profile_map.get(instance.role)
        if ProfileModel:
            profile, _ = ProfileModel.objects.get_or_create(user=instance)
            
            # If staff user, ensure permissions are created
            if instance.role == 'staff':
                StaffPermission.objects.get_or_create(staff=profile)
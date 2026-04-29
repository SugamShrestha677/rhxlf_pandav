from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, StaffProfile, StaffPermission


@receiver(post_save, sender=User)
def create_profile_and_permissions(sender, instance, created, **kwargs):
    """
    Auto-create profiles and permissions when user is created
    """
    if created:
        # Profiles are already created in the serializer
        
        # If staff user, ensure permissions are created
        if instance.role == 'staff':
            staff_profile = instance.staff_profile
            if not hasattr(staff_profile, 'permissions'):
                StaffPermission.objects.create(staff=staff_profile)
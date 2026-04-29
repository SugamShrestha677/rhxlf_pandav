from datetime import timedelta
import random

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone


def generate_otp():
    return f"{random.randint(0, 999999):06d}"


def is_otp_expired(otp_created_at):
    if not otp_created_at:
        return True
    return timezone.now() > otp_created_at + timedelta(minutes=10)


def send_otp_email(email, full_name, otp, purpose="email verification"):
    subject = f"LMS {purpose.title()} OTP"
    context = {
        "full_name": full_name,
        "otp": otp,
        "purpose": purpose,
    }
    message = (
        f"Hello {full_name},\n\n"
        f"Your {purpose} OTP is: {otp}\n"
        "It expires in 10 minutes.\n"
    )
    email_message = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[email],
    )
    email_message.send(fail_silently=False)
    print(f"[{purpose.upper()} OTP] {email}: {otp}")

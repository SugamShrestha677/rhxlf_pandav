from __future__ import annotations

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from .models import User


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_credentials_email_task(self, user_id: int, temp_password: str) -> bool:
    user = User.objects.select_related("created_by").get(id=user_id)
    recipient_email = user.notification_email
    subject = "Welcome to Leapfrog Connect - Your Account Credentials"
    login_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/login"

    html_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
            .content {{ background-color: #f9f9f9; padding: 30px; border: 1px solid #ddd; }}
            .credentials-box {{ background-color: #fff; border: 2px solid #4CAF50; border-radius: 5px; padding: 20px; margin: 20px 0; }}
            .temp-password {{ background-color: #ffeb3b; padding: 5px 10px; border-radius: 3px; font-family: monospace; font-size: 16px; }}
            .warning {{ background-color: #fff3cd; border: 1px solid #ffc107; padding: 15px; border-radius: 5px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Welcome to Leapfrog Connect!</h1>
            </div>
            <div class="content">
                <p>Hello,</p>
                <p>Your account has been created as a <strong>{user.get_role_display()}</strong>.</p>
                <div class="credentials-box">
                    <h3>Your Login Credentials:</h3>
                    <p><strong>Organization Email (Login):</strong><br>{user.email}</p>
                    <p><strong>Temporary Password:</strong><br><span class="temp-password">{temp_password}</span></p>
                </div>
                <div class="warning">
                    <strong>Important:</strong> You must change your password on first login.
                </div>
                <p><strong>Login URL:</strong> {login_url}</p>
                <p>Created by: {user.created_by.email if user.created_by else 'System'}</p>
            </div>
        </div>
    </body>
    </html>
    """

    plain_message = f"""
    Welcome to Leapfrog Connect!

    Your account has been created.
    Organization Email (Login): {user.email}
    Temporary Password: {temp_password}
    Role: {user.get_role_display()}

    You must change your password on first login.
    Login URL: {login_url}
    """

    send_mail(
        subject=subject,
        message=plain_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient_email],
        html_message=html_message,
        fail_silently=False,
    )
    return True

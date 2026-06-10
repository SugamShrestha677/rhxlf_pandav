# Generated manually for Notification model

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_staffpermission_can_manage_payments_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('message', models.TextField()),
                ('notification_type', models.CharField(
                    choices=[
                        ('course_enrollment', 'Course Enrollment'),
                        ('course_completion', 'Course Completion'),
                        ('assignment_graded', 'Assignment Graded'),
                        ('quiz_graded', 'Quiz Graded'),
                        ('system_alert', 'System Alert'),
                        ('message', 'Message'),
                        ('attendance_alert', 'Attendance Alert'),
                        ('certificate_available', 'Certificate Available'),
                        ('general', 'General'),
                    ],
                    default='general',
                    max_length=50,
                )),
                ('link', models.URLField(blank=True, max_length=500, null=True)),
                ('is_read', models.BooleanField(default=False)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('recipient', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notifications',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Notification',
                'verbose_name_plural': 'Notifications',
                'db_table': 'notifications',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', '-created_at'], name='notificatio_recipie_8e0f0d_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', 'is_read'], name='notificatio_recipie_4a8b2a_idx'),
        ),
    ]

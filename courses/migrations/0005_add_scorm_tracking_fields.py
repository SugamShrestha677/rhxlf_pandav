from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0004_add_scorm_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='scorm_import_job_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='courseenrollment',
            name='scorm_registration_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]

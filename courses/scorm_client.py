# scorm_client.py
import rustici_software_cloud_v2 as scorm_cloud
from django.conf import settings

def get_scorm_client():
    """
    Returns an authenticated SCORM Cloud API client.
    """
    config = scorm_cloud.Configuration()
    config.username = settings.SCORM_CLOUD_APP_ID
    config.password = settings.SCORM_CLOUD_SECRET_KEY
    config.host = settings.SCORM_CLOUD_BASE_URL
    # You can also set some basic headers here if needed
    # config.api_key['Authorization'] = 'Basic ...'
    return scorm_cloud.ApiClient(config)
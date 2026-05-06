import os
import sys
import json

# Ensure Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'LMS.settings')
# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Provide an in-memory cache to avoid requiring a running Redis instance during smoke tests.
from django.core.cache.backends.locmem import LocMemCache
import types

# Build a minimal fake django.core.cache module expected during setup
fake_cache_mod = types.ModuleType('django.core.cache')
_loc_cache = LocMemCache('smoke', {})
fake_cache_mod.cache = _loc_cache
fake_cache_mod.DEFAULT_CACHE_ALIAS = 'default'

class _Caches:
    def __getitem__(self, key):
        return _loc_cache
    def all(self):
        return [_loc_cache]

fake_cache_mod.caches = _Caches()
sys.modules['django.core.cache'] = fake_cache_mod

# Stub third-party modules used by settings to avoid requiring them for smoke tests
fake_cloudinary = types.ModuleType('cloudinary')
def _fake_cloudinary_config(**kwargs):
    return None
fake_cloudinary.config = _fake_cloudinary_config
sys.modules['cloudinary'] = fake_cloudinary
sys.modules['cloudinary.uploader'] = types.ModuleType('cloudinary.uploader')
sys.modules['cloudinary.api'] = types.ModuleType('cloudinary.api')
fake_cloudinary.__file__ = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'LMS', 'settings.py'))
fake_cloudinary.models = types.ModuleType('cloudinary.models')
class CloudinaryField:
    def __init__(self, *args, **kwargs):
        pass
fake_cloudinary.models.CloudinaryField = CloudinaryField
sys.modules['cloudinary.models'] = fake_cloudinary.models
def _fake_upload(file, **kwargs):
    return {'secure_url': 'https://example.com/fake.jpg'}
sys.modules['cloudinary.uploader'].upload = _fake_upload
fake_cloudinary.utils = types.ModuleType('cloudinary.utils')
def _fake_cloudinary_url(public_id, **kwargs):
    return (f'https://res.cloudinary.com/demo/{public_id}.jpg', {})
fake_cloudinary.utils.cloudinary_url = _fake_cloudinary_url
sys.modules['cloudinary.utils'] = fake_cloudinary.utils

fake_cloudinary_storage = types.ModuleType('cloudinary_storage')
fake_cloudinary_storage.storage = types.ModuleType('cloudinary_storage.storage')
class MediaCloudinaryStorage:
    pass
class StaticHashedCloudinaryStorage:
    pass
fake_cloudinary_storage.storage.MediaCloudinaryStorage = MediaCloudinaryStorage
fake_cloudinary_storage.storage.StaticHashedCloudinaryStorage = StaticHashedCloudinaryStorage
sys.modules['cloudinary_storage'] = fake_cloudinary_storage
sys.modules['cloudinary_storage.storage'] = fake_cloudinary_storage.storage
fake_cloudinary_storage.__file__ = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'LMS', 'settings.py'))

fake_decouple = types.ModuleType('decouple')
class Csv:
    def __call__(self, v):
        return v.split(',') if v else []
def _fake_config(name, default=None, cast=None):
    if default is not None:
        return default
    return ''
fake_decouple.Csv = Csv
fake_decouple.config = _fake_config
sys.modules['decouple'] = fake_decouple

import django
django.setup()

from django.test import Client

c = Client()

def pretty(resp):
    try:
        return json.dumps(resp.json(), indent=2)[:2000]
    except Exception:
        return resp.content[:2000]

print('GET /api/categories/')
resp = c.get('/api/categories/', HTTP_HOST='localhost')
print(resp.status_code)
print(pretty(resp))

print('\nGET /api/courses/')
resp = c.get('/api/courses/', HTTP_HOST='localhost')
print(resp.status_code)
print(pretty(resp))

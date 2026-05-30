from pathlib import Path
import sys

CURRENT_FILE = Path(__file__).resolve()
path_candidates = [CURRENT_FILE.parent.parent, CURRENT_FILE.parent.parent.parent]

for candidate in path_candidates:
	if candidate.exists() and str(candidate) not in sys.path:
		sys.path.insert(0, str(candidate))

# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
from .celery import app as celery_app

__all__ = ('celery_app',)

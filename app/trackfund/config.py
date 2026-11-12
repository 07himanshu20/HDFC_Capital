"""Runtime settings, all from environment variables (see .env.example)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('TRACKFUND_DATA_DIR', BASE_DIR / 'data')).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get('DATABASE_URL', f"sqlite:///{DATA_DIR / 'trackfund.db'}")
STORAGE_DIR = Path(os.environ.get('TRACKFUND_STORAGE_DIR', DATA_DIR / 'storage')).resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_MB = int(os.environ.get('TRACKFUND_MAX_UPLOAD_MB', '300'))
MAX_FILES_PER_UPLOAD = int(os.environ.get('TRACKFUND_MAX_FILES', '2000'))
SESSION_HOURS = int(os.environ.get('TRACKFUND_SESSION_HOURS', '12'))
# How long the upload window's staged progress bar runs for a zip (seconds). The work itself usually takes 1-3 s; the bar
# paces the stages so they can be followed. 0 shows the result as soon as it is ready.
UPLOAD_PROGRESS_SECONDS = max(0.0, min(120.0, float(os.environ.get('TRACKFUND_UPLOAD_PROGRESS_SECONDS', '20'))))
COOKIE_SECURE = os.environ.get('TRACKFUND_COOKIE_SECURE', 'false').lower() == 'true'
SEED_PROFILE = Path(os.environ.get('TRACKFUND_SEED_PROFILE', BASE_DIR / 'seed' / 'org_profile.json'))


def _secret():
    s = os.environ.get('TRACKFUND_SECRET_KEY')
    if s:
        return s
    p = DATA_DIR / '.secret_key'
    if not p.exists():
        p.write_text(secrets.token_hex(32))
        p.chmod(0o600)
    return p.read_text().strip()


SECRET_KEY = _secret()

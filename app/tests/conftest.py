import os
import sys
import tempfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
DATASET = Path(os.environ.get('TRACKFUND_TEST_DATASET', APP.parent / 'dataset' / 'Q2FY27'))

# every test session gets its own data directory and database
_tmp = tempfile.mkdtemp(prefix='trackfund_test_')
os.environ.setdefault('TRACKFUND_DATA_DIR', _tmp)
os.environ.setdefault('TRACKFUND_INITIAL_PASSWORD', 'test-password-123')


@pytest.fixture(scope='session')
def dataset():
    if not (DATASET / 'scheme_A_gift').exists():
        pytest.skip(f"dataset not found at {DATASET}")
    return DATASET

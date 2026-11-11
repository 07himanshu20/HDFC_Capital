"""End to end through HTTP: sign-in, upload, dashboard, maker-checker, period lock, permissions, regulator report files, files, exports."""
import hashlib
import io
import shutil
import zipfile

import pytest
from fastapi.testclient import TestClient

from trackfund.api import app

H = {'X-Requested-With': 'trackfund'}
PW = 'test-password-123'


def _zip(folder):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in folder.rglob('*'):
            if p.is_file() and not p.name.startswith('.'):
                z.write(p, 'Q2FY27/' + str(p.relative_to(folder)))
    return buf.getvalue()


def login(c, user, pw=PW):
    c.post('/api/auth/logout', headers=H)
    r = c.post('/api/auth/login', json={'username': user, 'password': pw}, headers=H)
    assert r.status_code == 200, r.text


@pytest.fixture(scope='module')
def client(dataset):
    with TestClient(app) as c:
        yield c


def test_requires_sign_in(client):
    assert client.get('/api/dashboard').status_code == 401
    r = client.post('/api/auth/login', json={'username': 'pallav', 'password': 'wrong'}, headers=H)
    assert r.status_code == 401


def test_csrf_header_required(client):
    assert client.post('/api/auth/login', json={'username': 'pallav', 'password': PW}).status_code == 403


def test_upload_and_workflow(client, dataset):
    login(client, 'devika')        # investor relations cannot upload
    r = client.post('/api/uploads', files={'files': ('q.zip', b'x', 'application/zip')}, headers=H)
    assert r.status_code == 403

    login(client, 'pallav')
    r = client.post('/api/uploads', files={'files': ('Q2FY27.zip', _zip(dataset), 'application/zip')}, data={'mode': 'auto'}, headers=H)
    run = r.json()
    assert run['status'] == 'succeeded', run
    assert run['summary']['A']['nav'] == 64.8077 and run['summary']['B']['nav'] == 298.9544
    assert run['summary']['A']['failed'] == 0 and run['summary']['B']['failed'] == 0

    d = client.get('/api/dashboard').json()
    assert d['state']['nav'] == {'A': 'draft', 'B': 'draft'}
    assert len(d['data']['schemes']['A']['journals']) == 28

    assert client.post('/api/actions/navlock', json={'scheme': 'A'}, headers=H).status_code == 403
    assert client.post('/api/actions/navsubmit', json={'scheme': 'A'}, headers=H).status_code == 200
    login(client, 'renuka')
    r = client.post('/api/actions/navlock', json={'scheme': 'A'}, headers=H)
    assert r.status_code == 200 and r.json()['state']['nav']['A'] == 'locked'
    assert 'Refused' in client.post('/api/actions/trypost', json={'scheme': 'A'}, headers=H).json()['message']

    # a locked quarter's files cannot change
    fx = (dataset / 'scheme_A_gift' / 'FX_Rates_USDINR_Daily_Jul-Sep26.csv').read_bytes().replace(b'89.4000', b'89.4100')
    r = client.post('/api/uploads', files={'files': ('FX_Rates_USDINR_Daily_Jul-Sep26.csv', fx, 'text/csv')}, data={'mode': 'merge', 'scheme': 'A'}, headers=H).json()
    assert r['status'] == 'failed' and 'locked' in r['error']
    # the open scheme can still be corrected
    xls = (dataset / 'scheme_B_onshore' / 'Bank_Statement_SchemeB_INR_Jul-Sep26.xls').read_bytes()
    r = client.post('/api/uploads', files={'files': ('Bank_Statement_SchemeB_INR_Jul-Sep26.xls', xls, 'application/vnd.ms-excel')}, data={'mode': 'merge', 'scheme': 'B'}, headers=H).json()
    assert r['status'] == 'succeeded'
    assert client.get('/api/dashboard').json()['state']['nav']['A'] == 'locked'

    assert 'no breaks' in client.post('/api/actions/verify', json={}, headers=H).json()['message']


def test_regulator_report_file(client, tmp_path):
    """after test_upload_and_workflow: scheme A is locked, scheme B is a draft"""
    from decimal import Decimal as D
    from trackfund.catalog import classify
    from trackfund.db import SessionLocal
    from trackfund.models import ReportRun
    from trackfund.parsing.extract import parse_prior_report
    from trackfund.parsing.util import num

    r15 = lambda data, s: next(x for x in data['schemes'][s]['rules'] if x['rule'] == 'R15')
    login(client, 'pallav')
    d = client.get('/api/dashboard').json()
    name_a, name_b = (d['data']['schemes'][s]['reg_report']['title'] for s in ('A', 'B'))
    assert (name_a, name_b) == ('IFSCA quarterly report', 'SEBI quarterly activity report')
    assert r15(d['data'], 'A')['status'] == 'PARTIAL'

    r = client.post('/api/actions/gen', json={'scheme': 'B', 'arg': name_b}, headers=H)       # NAV B not locked
    assert r.status_code == 409 and 'locked NAV' in r.json()['detail']
    login(client, 'devika')                                                                    # investor relations
    assert client.post('/api/actions/gen', json={'scheme': 'A', 'arg': name_a}, headers=H).status_code == 403

    login(client, 'pallav')
    r = client.post('/api/actions/gen', json={'scheme': 'A', 'arg': name_a}, headers=H)
    assert r.status_code == 200, r.text
    j = r.json()
    rep = j['state']['regrep']['A']
    assert rep['check'] == 'PASS' and rep['file'] == 'IFSCA_Quarterly_Report_Q2FY27.xlsx' and rep['nav_v'] == 1
    assert r15(j['data'], 'A')['status'] == 'PASS' and r15(j['data'], 'B')['status'] == 'PARTIAL'
    assert r15(client.get('/api/dashboard').json()['data'], 'A')['status'] == 'PASS'
    assert 'R15,PASS' in client.get('/api/export/A/rules.csv').text

    # every signed-in user can download it; the bytes are the ones hashed at generation
    login(client, 'auditor')
    f = client.get(f"/api/reports/{rep['id']}/file")
    assert f.status_code == 200 and f.headers['content-type'].startswith('application/vnd.openxmlformats') and hashlib.sha256(f.content).hexdigest() == rep['sha']
    p = tmp_path / rep['file']
    p.write_bytes(f.content)
    pr = parse_prior_report(str(p))                       # how next quarter's upload reads it
    assert classify(rep['file'])[0].key == 'prior_report'
    assert num(pr['kv']['Net asset value']) == D('64.8077') and num(pr['kv']['Cumulative drawn']) == D('66')
    assert pr['kv']['Reporting period'] == 'Q2 FY27 (01-Jul-2026 to 30-Sep-2026)'
    pv = client.get(f"/api/reports/{rep['id']}/preview").json()
    assert [s['name'] for s in pv['sheets']] == ['Report', 'Investments', 'Investors'] and all(c[3] for c in pv['checks'])
    actions = [e['action'] for e in client.get('/api/state').json()['audit']]
    assert 'REPORT_GENERATED' in actions and 'REPORT_DOWNLOADED' in actions

    # a stored file that no longer matches its hash is not served
    with SessionLocal() as db:
        path = db.get(ReportRun, rep['id']).file_path
    with open(path, 'ab') as fh:
        fh.write(b'x')
    assert client.get(f"/api/reports/{rep['id']}/file").status_code == 409
    assert client.get('/api/reports/999999/file').status_code == 404


def test_files_and_exports(client):
    login(client, 'auditor')
    r = client.get('/api/files/A/Deal_Master_SchemeA.xlsx')
    assert r.status_code == 200 and len(r.content) > 1000
    assert client.get('/api/files/A/../../../../etc/passwd').status_code == 404
    r = client.get('/api/export/B/trial-balance.csv')
    assert r.status_code == 200 and '1100,Cash at bank,54.9531,14.0698,69.0229' in r.text
    assert client.post('/api/actions/obl', json={'scheme': 'A', 'arg': 'A-OB-02'}, headers=H).status_code == 403


def test_admin_users(client):
    login(client, 'pallav')
    assert client.get('/api/admin/users').status_code == 403
    login(client, 'admin')
    r = client.post('/api/admin/users', json={'username': 'newuser', 'full_name': 'New User', 'role': 'IR', 'password': 'another-password-1'}, headers=H)
    assert r.status_code == 200
    login(client, 'newuser', 'another-password-1')
    assert client.get('/api/auth/me').json()['role'] == 'IR'

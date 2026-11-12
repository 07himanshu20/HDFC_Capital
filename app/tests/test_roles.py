"""Role-based access: each role gets only its pages and their data; the administrator gets everything and alone can delete
source files and manage users.  Runs after test_api.py (same database): scheme A is locked there, scheme B is a draft."""
import pytest
from fastapi.testclient import TestClient

from trackfund import access
from trackfund.api import app

H = {'X-Requested-With': 'trackfund'}
PW = 'test-password-123'
USERS = {'admin': 'ADMIN', 'ishaan': 'PO', 'jaideep': 'CRO', 'pallav': 'FIN_MAKER', 'renuka': 'FIN_CHECKER', 'farhan': 'AML_PO', 'devika': 'IR',
         'nakul': 'INV_TEAM', 'trustee': 'TRUSTEE_RO', 'auditor': 'AUDITOR_RO'}
KYC_ONLY = {'bo', 'fatca', 'giin', 'pep'}


def login(c, user, pw=PW):
    c.post('/api/auth/logout', headers=H)
    r = c.post('/api/auth/login', json={'username': user, 'password': pw}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def upload_quarter(c, dataset):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for p in dataset.rglob('*'):
            if p.is_file() and not p.name.startswith('.'):
                z.write(p, 'Q2FY27/' + str(p.relative_to(dataset)))
    r = c.post('/api/uploads', files={'files': ('q.zip', buf.getvalue(), 'application/zip')}, headers=H).json()
    assert r['status'] == 'succeeded', r.get('error')
    return r


@pytest.fixture(scope='module')
def client(dataset):
    with TestClient(app) as c:
        login(c, 'admin')
        if not c.get('/api/dashboard').json()['data']:          # running this file alone: load the quarter first
            upload_quarter(c, dataset)
        yield c


def test_matrix_is_consistent():
    for a, (roles, page) in access.ACTIONS.items():
        assert page in access.PAGE_KEYS
        for r in roles:
            assert page in access.ROLE_PAGES[r], f"{r} may {a} but cannot open {page}"
    assert set(access.ROLE_PAGES['ADMIN']) == set(access.PAGE_KEYS)
    for r, ps in access.ROLE_PAGES.items():
        assert 'home' in ps
        if r != 'ADMIN':
            assert 'admin' not in ps
    # only the administrator sees all of fund accounting, fund administration and reporting
    groups = {'Fund accounting', 'Fund administration', 'Reporting'}
    every = {k for k, _, g in access.PAGES if g in groups}
    assert [r for r, ps in access.ROLE_PAGES.items() if every <= set(ps)] == ['ADMIN']


@pytest.mark.parametrize('user,role', USERS.items())
def test_each_role_gets_only_its_pages_and_data(client, user, role):
    me = login(client, user)
    assert me['role'] == role and me['access']['pages'] == [p for p in access.PAGE_KEYS if p in access.ROLE_PAGES[role]]
    d = client.get('/api/dashboard').json()
    pages = set(d['user']['access']['pages'])
    allowed_keys = set(access.ALWAYS) | {k for p in pages for k in access.PAGE_DATA[p]} | {'instruments', 'rules'}
    for sid, sv in d['data']['schemes'].items():
        if role == 'ADMIN':
            assert 'investors' in sv and 'pep' in sv['investors'][0] and 'journals' in sv          # everything
        else:
            assert set(sv) <= allowed_keys, (role, set(sv) - allowed_keys)
            assert 'journals' not in sv or pages & {'nav-close', 'ledger', 'instruments', 'fx', 'valuation', 'tally', 'calls', 'distributions', 'bank'}
            for i in sv.get('investors', []):
                if 'kyc' not in pages:
                    assert not (set(i) & KYC_ONLY), (role, set(i) & KYC_ONLY)
            for f in sv['files']:
                assert any(p in pages for p in access.file_pages(f['page'])), (role, f['file'])
    st = d['state']
    if 'audit' not in pages:
        assert st['audit'] == []
    if 'kyc' not in pages:
        assert st['str'] == []

    expect = lambda page: 200 if page in pages else 403
    assert client.get('/api/runs').status_code == expect('ingestion')
    assert client.get('/api/export/B/journals.csv').status_code == expect('ledger')
    assert client.get('/api/export/B/capital-accounts.csv').status_code == expect('capital')
    assert client.get('/api/files/B/KYC_Register_SchemeB.xlsx').status_code == expect('kyc')
    assert client.get('/api/files/B/Deal_Master_SchemeB.xlsx').status_code == (200 if pages & {'instruments', 'deals'} else 403)
    assert client.get('/api/admin/users').status_code == (200 if role == 'ADMIN' else 403)
    assert client.get('/api/dashboard').headers['cache-control'] == 'no-store'


def test_actions_follow_the_role(client):
    login(client, 'jaideep')                                  # CRO
    assert client.post('/api/actions/navsubmit', json={'scheme': 'B'}, headers=H).status_code == 403
    assert client.post('/api/actions/str', json={'scheme': 'B'}, headers=H).status_code == 403
    login(client, 'auditor')                                  # read only
    assert client.post('/api/actions/ack', json={'scheme': 'B', 'arg': 'x'}, headers=H).status_code == 403
    assert client.post('/api/actions/verify', json={}, headers=H).status_code == 200
    assert client.post('/api/uploads', files={'files': ('x.csv', b'x', 'text/csv')}, headers=H).status_code == 403

    # obligations: only the owner role (or the Principal Officer / administrator) marks one filed
    login(client, 'admin')
    obl = [o for o in client.get('/api/dashboard').json()['data']['schemes']['B']['obligations'] if o['status'] == 'Open']
    mine = next(o for o in obl if o['owner'] == 'IR')
    other = next(o for o in obl if o['owner'] not in ('IR',))
    login(client, 'devika')                                   # investor relations
    assert client.post('/api/actions/obl', json={'scheme': 'B', 'arg': other['ref']}, headers=H).status_code == 403
    assert client.post('/api/actions/obl', json={'scheme': 'B', 'arg': mine['ref']}, headers=H).status_code == 200


def test_admin_can_act_but_maker_checker_holds(client):
    login(client, 'admin')
    assert client.post('/api/actions/navsubmit', json={'scheme': 'B'}, headers=H).status_code == 200
    r = client.post('/api/actions/navlock', json={'scheme': 'B'}, headers=H)
    assert r.status_code == 403 and 'submitted' in r.json()['detail']
    login(client, 'renuka')
    # the checker approves; then put B back to a draft for the delete tests by re-checking state only
    assert client.get('/api/dashboard').json()['state']['nav']['B'] == 'submitted'


def test_delete_files(client):
    login(client, 'renuka')
    assert client.get('/api/admin/files').status_code == 403
    assert client.post('/api/admin/files/delete', json={'scheme': 'B', 'files': ['AML_Policy_Extract.pdf']}, headers=H).status_code == 403

    login(client, 'admin')
    files = {(x['scheme'], x['file']): x for x in client.get('/api/admin/files').json()}
    assert files[('B', 'Deal_Master_SchemeB.xlsx')]['refused']                       # required, only one
    assert files[('A', 'Deal_Master_SchemeA.xlsx')]['refused']
    assert all(x['refused'] for (s, _), x in files.items() if s == 'A')               # scheme A is locked
    r = client.post('/api/admin/files/delete', json={'scheme': 'B', 'files': ['Deal_Master_SchemeB.xlsx']}, headers=H)
    assert r.status_code == 409 and 'Required' in r.json()['detail']
    r = client.post('/api/admin/files/delete', json={'scheme': 'A', 'files': ['CTR_FY26_extract.pdf']}, headers=H)
    assert r.status_code == 409
    assert client.post('/api/admin/files/delete', json={'scheme': 'B', 'files': ['../../etc/passwd']}, headers=H).status_code == 409

    # an evidence document: the books are recomputed without it
    target = next(f for (s, f), x in files.items() if s == 'B' and f.startswith('KYC_Pack_') and not x['refused'])
    before = client.get('/api/dashboard').json()
    n_before = len(before['data']['schemes']['B']['files'])
    r = client.post('/api/admin/files/delete', json={'scheme': 'B', 'files': [target]}, headers=H).json()
    assert r['status'] == 'succeeded', r
    after = client.get('/api/dashboard').json()
    assert len(after['data']['schemes']['B']['files']) == n_before - 1
    assert target not in {f['file'] for f in after['data']['schemes']['B']['files']}
    assert after['data']['schemes']['B']['nav_close'] == before['data']['schemes']['B']['nav_close']
    assert after['state']['nav']['B'] == 'draft'                                       # the submitted NAV is superseded by a new draft
    assert any(e['action'] == 'FILE_DELETED' and target in e['obj'] for e in after['state']['audit'])

    # a file the books cannot do without (one month of developer MIS): nothing changes
    run_before = after['run']['id']
    r = client.post('/api/admin/files/delete', json={'scheme': 'B', 'files': ['Developer_MIS_SPV-B1_Sep26.xlsx']}, headers=H).json()
    assert r['status'] == 'failed' and r['error'].startswith('Nothing was deleted')
    assert client.get('/api/dashboard').json()['run']['id'] == run_before


def test_user_administration(client):
    login(client, 'pallav')
    assert client.post('/api/admin/users', json={'username': 'x', 'full_name': 'X', 'role': 'IR', 'password': 'long-enough-pw'}, headers=H).status_code == 403
    login(client, 'admin')
    r = client.post('/api/admin/users', json={'username': 'kavya', 'full_name': 'Kavya Rao', 'role': 'CRO', 'password': 'kavya-password-1'}, headers=H)
    assert r.status_code == 200, r.text
    uid = r.json()['id']
    assert login(client, 'kavya', 'kavya-password-1')['access']['pages'] == [p for p in access.PAGE_KEYS if p in access.ROLE_PAGES['CRO']]

    login(client, 'admin')
    assert client.patch(f'/api/admin/users/{uid}', json={'role': 'IR'}, headers=H).status_code == 200
    login(client, 'kavya', 'kavya-password-1')
    assert 'capital' in client.get('/api/auth/me').json()['access']['pages']
    login(client, 'admin')
    assert client.patch(f'/api/admin/users/{uid}', json={'active': False}, headers=H).status_code == 200
    assert client.post('/api/auth/login', json={'username': 'kavya', 'password': 'kavya-password-1'}, headers=H).status_code == 401

    me = client.get('/api/auth/me').json()
    assert client.patch(f"/api/admin/users/{me['id']}", json={'active': False}, headers=H).status_code == 409      # not yourself
    assert client.patch(f"/api/admin/users/{me['id']}", json={'role': 'IR'}, headers=H).status_code == 409        # last administrator
    assert client.get('/api/admin/access').json()['roles'][0]['role'] == 'ADMIN'


def test_delete_all_then_upload_again(client, dataset, monkeypatch):
    ALL = {'confirm': 'DELETE ALL'}
    login(client, 'renuka')
    assert client.post('/api/admin/files/delete-all', json=ALL, headers=H).status_code == 403
    login(client, 'admin')
    assert client.post('/api/admin/files/delete-all', json={'confirm': 'yes'}, headers=H).status_code == 400
    r = client.post('/api/admin/files/delete-all', json=ALL, headers=H)
    assert r.status_code == 409 and 'locked' in r.json()['detail']                       # scheme A was approved in test_api
    before = client.get('/api/dashboard').json()
    run_before = before['run']['id']
    assert before['data'] is not None

    # the rest as if no quarter were locked
    from trackfund.services import ingest
    monkeypatch.setattr(ingest, 'is_locked', lambda *a: False)
    r = client.post('/api/admin/files/delete-all', json=ALL, headers=H).json()
    assert r['status'] == 'succeeded' and r['note'].startswith('All ') and not r['is_current']
    d = client.get('/api/dashboard').json()
    assert d['data'] is None and d['run'] is None                                       # nothing loaded, for every role
    login(client, 'auditor')
    assert client.get('/api/dashboard').json()['data'] is None
    assert client.get('/api/files/B/Deal_Master_SchemeB.xlsx').status_code == 404
    login(client, 'admin')
    assert client.get('/api/admin/files').json() == []
    assert client.post('/api/admin/files/delete-all', json=ALL, headers=H).status_code == 409          # nothing left to delete
    runs = client.get('/api/runs').json()
    assert runs[0]['id'] == r['id'] and runs[0]['note'] and not any(x['is_current'] for x in runs)
    assert client.get(f'/api/runs/{run_before}').status_code == 200                      # history kept

    # upload the quarter again: the same books
    upload_quarter(client, dataset)
    after = client.get('/api/dashboard').json()
    for s, v in before['data']['schemes'].items():
        assert after['data']['schemes'][s]['nav_close'] == v['nav_close']
        assert {f['file'] for f in v['files']} <= {f['file'] for f in after['data']['schemes'][s]['files']}
    assert after['state']['nav']['B'] == 'draft'
    assert sum(e['action'] == 'ALL_FILES_DELETED' for e in after['state']['audit']) == len(before['data']['schemes'])

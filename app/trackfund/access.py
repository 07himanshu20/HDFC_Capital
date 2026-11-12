"""Who can see what, and who can do what.

The administrator sees every page and can do every action. Every other role sees only the pages listed for it in
ROLE_PAGES and receives only the data those pages read. Hiding a menu item is not the control: the server filters the
dashboard data, the workflow state, the source files, the exports and the report files for each role, and refuses
actions the role may not take.

PAGE_DATA and PAGE_INVESTOR_FIELDS were recorded by rendering every page of the dashboard (and every report preview)
against a proxy that logs which parts of the scheme data it reads.
"""
PAGES = [
    # key, label, menu group
    ('home', 'Command centre', 'Overview'),
    ('ingestion', 'Data ingestion', 'Data'),
    ('nav-close', 'Quarter close & NAV', 'Fund accounting'), ('ledger', 'Ledger & trial balance', 'Fund accounting'),
    ('instruments', 'Instruments & accruals', 'Fund accounting'), ('fx', 'FX & translation', 'Fund accounting'),
    ('valuation', 'Valuation', 'Fund accounting'), ('capital', 'Capital accounts', 'Fund accounting'),
    ('waterfall', 'Waterfall', 'Fund accounting'), ('tally', 'Tally bridge', 'Fund accounting'),
    ('investors', 'Investors', 'Fund administration'), ('kyc', 'KYC / AML / FATCA', 'Fund administration'),
    ('calls', 'Capital calls', 'Fund administration'), ('distributions', 'Distributions', 'Fund administration'),
    ('bank', 'Bank & custody', 'Fund administration'), ('deals', 'Deals, CPs & filings', 'Fund administration'),
    ('approvals', 'Approvals & controls', 'Fund administration'),
    ('reports', 'Report centre', 'Reporting'), ('projects', 'Project monitoring', 'Reporting'),
    ('calendar', 'Calendar', 'Compliance'), ('exceptions', 'Exceptions', 'Compliance'), ('audit', 'Audit log', 'Compliance'),
    ('admin', 'Users and access', 'Administration'),
]
PAGE_KEYS = [p[0] for p in PAGES]

FUND_ACCOUNTING = ['nav-close', 'ledger', 'instruments', 'fx', 'valuation', 'capital', 'waterfall', 'tally']
_FINANCE = ['home', 'ingestion', *FUND_ACCOUNTING, 'investors', 'calls', 'distributions', 'bank', 'approvals', 'reports', 'calendar', 'exceptions']

ROLE_PAGES = {
    'ADMIN': PAGE_KEYS,
    # books, quarter close, cash, investor money flows, reports
    'FIN_MAKER': _FINANCE,
    'FIN_CHECKER': _FINANCE + ['audit'],
    # Principal Officer: the scheme's compliance, investors and KYC, approvals, filings, oversight of the NAV
    'PO': ['home', 'nav-close', 'investors', 'kyc', 'deals', 'approvals', 'reports', 'projects', 'calendar', 'exceptions', 'audit'],
    # Chief Risk Officer: portfolio risk, valuation, covenants
    'CRO': ['home', 'instruments', 'valuation', 'deals', 'projects', 'calendar', 'exceptions'],
    # AML officer: KYC, screening, STRs, money in and out of investor accounts
    'AML_PO': ['home', 'investors', 'kyc', 'calls', 'distributions', 'calendar', 'exceptions'],
    # Investor relations: investors, their capital, notices and investor reports
    'IR': ['home', 'investors', 'capital', 'calls', 'distributions', 'reports', 'projects', 'calendar', 'exceptions'],
    # Investment team: the portfolio and the developers
    'INV_TEAM': ['home', 'instruments', 'valuation', 'deals', 'projects', 'calendar', 'exceptions'],
    # Trustee: oversight and NAV approval, read only otherwise
    'TRUSTEE_RO': ['home', 'nav-close', 'valuation', 'capital', 'waterfall', 'investors', 'approvals', 'reports', 'projects', 'calendar', 'exceptions', 'audit'],
    # Statutory auditor: books and evidence, read only; no investor KYC
    'AUDITOR_RO': ['home', 'ingestion', *FUND_ACCOUNTING, 'calls', 'distributions', 'bank', 'deals', 'approvals', 'reports', 'calendar', 'exceptions', 'audit'],
}

# action -> roles allowed (the administrator may always act). Each action lives on one page, which the role must also see.
ACTIONS = {
    'navsubmit': (('FIN_MAKER',), 'nav-close'),
    'navlock': (('FIN_CHECKER', 'TRUSTEE_RO'), 'nav-close'),
    'valok': (('FIN_CHECKER', 'CRO'), 'valuation'),
    'trypost': (('FIN_MAKER', 'FIN_CHECKER'), 'approvals'),
    'apprbank': (('FIN_CHECKER',), 'approvals'),
    'obl': (('PO', 'AML_PO', 'IR', 'FIN_MAKER', 'FIN_CHECKER', 'INV_TEAM'), 'calendar'),     # and only obligations the role owns (PO: all)
    'str': (('AML_PO', 'PO'), 'kyc'),
    'strnext': (('AML_PO', 'PO'), 'kyc'),
    'mapok': (('FIN_MAKER', 'FIN_CHECKER'), 'ingestion'),
    'notice': (('IR', 'PO', 'CRO', 'INV_TEAM'), 'projects'),
    'gen': (('FIN_MAKER', 'FIN_CHECKER', 'PO', 'IR'), 'reports'),
    'gen_regulator': (('FIN_MAKER', 'FIN_CHECKER', 'PO'), 'reports'),
    'ack': (('FIN_MAKER', 'FIN_CHECKER', 'PO', 'CRO', 'AML_PO', 'IR', 'INV_TEAM'), 'exceptions'),
    'verify': (('FIN_CHECKER', 'PO', 'TRUSTEE_RO', 'AUDITOR_RO'), 'audit'),
    'upload': (('FIN_MAKER', 'FIN_CHECKER'), 'ingestion'),
    'delete_files': ((), 'ingestion'),          # administrator only
    'manage_users': ((), 'admin'),              # administrator only
}

# calendar 'Owner role' -> application role
OWNER_ROLE = {'CO': 'PO'}

# scheme data each page reads (recorded); 'meta' and 'files' are read by every page header
PAGE_DATA = {
    'home': [],                       # the command centre shows tiles only for pages the role can open (their data is already included)
    'ingestion': ['rules'],
    'nav-close': ['bank', 'classes', 'close_tb', 'dist', 'expected', 'fx_info', 'fx_work', 'investors', 'journals', 'nav_close', 'nav_open', 'open_tb'],
    'ledger': ['bank', 'close_tb', 'journals', 'open_tb'],
    'instruments': ['bank', 'instruments', 'journals'],
    'fx': ['bank', 'close_tb', 'fx', 'fx_info', 'fx_work', 'journals', 'open_tb'],
    'valuation': ['instruments', 'journals'],
    'capital': ['call', 'classes', 'expected', 'investors', 'nav_close', 'nav_open'],
    'waterfall': ['calls_perf', 'dists_perf', 'nav_close'],
    'tally': ['fx_info', 'journals', 'tally'],
    'investors': ['call', 'investors', 'side_letters'],
    'kyc': ['aml', 'investors'],
    'calls': ['bank', 'call', 'dist', 'investors', 'journals'],
    'distributions': ['bank', 'call', 'close_tb', 'dist', 'investors', 'journals'],
    'bank': ['bank', 'close_tb', 'instruments', 'journals', 'open_cash'],
    'deals': ['instruments'],
    'approvals': ['investors'],
    'reports': ['call', 'classes', 'close_tb', 'dist', 'expected', 'instruments', 'investors', 'nav_close', 'obligations', 'reg_report'],
    'projects': ['instruments', 'obligations'],
    'calendar': ['obligations'],
    'exceptions': ['obligations'],    # plus instruments / rules when the role sees the pages those exceptions point to
    'audit': [],
    'admin': [],
}
ALWAYS = ['meta', 'files']

# investor fields each page reads (recorded)
PAGE_INVESTOR_FIELDS = {
    'nav-close': ['ca', 'cls', 'id', 'name'],
    'capital': ['ca', 'commit', 'id', 'name'],
    'investors': ['bank', 'cls', 'commit', 'country', 'id', 'name', 'refresh', 'risk', 'tin', 'type', 'wht'],
    'kyc': ['bo', 'cls', 'crs', 'fatca', 'giin', 'id', 'kyc_docs', 'name', 'pep', 'refresh', 'reportable', 'risk', 'screened', 'screening', 'selfcert', 'tin'],
    'calls': ['commit', 'id', 'name'],
    'distributions': ['id', 'name'],
    'approvals': ['name'],
    'reports': ['ca', 'cls', 'commit', 'country', 'crs', 'id', 'name'],
}

# where each source file is used (catalog page label) -> dashboard pages
FILE_PAGE = {
    'KYC / AML / FATCA': ['kyc'], 'Deals, CPs & filings': ['deals'], 'Distributions': ['distributions'], 'Investors & commitments': ['investors'],
    'Ingestion / Bank reconciliation': ['bank'], 'Bank & custody reconciliation': ['bank'], 'Tally bridge': ['tally'], 'Calendar': ['calendar'],
    'Quarter close & NAV': ['nav-close'], 'Capital calls': ['calls'], 'Report centre': ['reports'], 'Valuation': ['valuation'],
    'Project monitoring': ['projects'], 'Ledger & TB': ['ledger'], 'Instruments & accruals / Deals, CPs & filings': ['instruments', 'deals'],
    'Capital accounts': ['capital'], 'FX & translation': ['fx'], 'Calendar / Exceptions': ['calendar', 'exceptions'],
}

ROLE_LABELS = {'ADMIN': 'Administrator', 'PO': 'Principal Officer', 'CRO': 'Chief Risk Officer', 'FIN_MAKER': 'Finance maker', 'FIN_CHECKER': 'Finance checker',
               'AML_PO': 'AML officer', 'IR': 'Investor relations', 'INV_TEAM': 'Investment team', 'TRUSTEE_RO': 'Trustee (read + approve)',
               'AUDITOR_RO': 'Auditor (read only)'}


def role_of(user):
    return 'ADMIN' if user.is_admin else user.role


def pages(user):
    allowed = set(ROLE_PAGES.get(role_of(user), ['home']))
    return [p for p in PAGE_KEYS if p in allowed]


def can_see(user, page):
    return page in pages(user)


def can(user, action):
    roles, page = ACTIONS[action]
    if user.is_admin:
        return True
    return user.role in roles and can_see(user, page)


def actions(user):
    return sorted(a for a in ACTIONS if can(user, a))


def who_can(action):
    """labels of the roles that may take an action, for messages"""
    roles, _ = ACTIONS[action]
    return [ROLE_LABELS[r] for r in roles] + ['Administrator']


def file_pages(page_label):
    return FILE_PAGE.get(page_label or '', [])


def can_open_file(user, page_label):
    if user.is_admin:
        return True
    ps = file_pages(page_label)
    return any(can_see(user, p) for p in ps)


def access_info(user):
    return dict(role=role_of(user), pages=pages(user), actions=actions(user), admin=bool(user.is_admin))


def matrix():
    """roles x pages and roles x actions, for the administration page and the docs"""
    return dict(pages=[dict(key=k, label=l, group=g) for k, l, g in PAGES],
                roles=[dict(role=r, label=ROLE_LABELS[r], pages=[p for p in PAGE_KEYS if p in set(ps)],
                            actions=sorted(a for a, (rs, pg) in ACTIONS.items() if r == 'ADMIN' or (r in rs and pg in ps)))
                       for r, ps in ROLE_PAGES.items()])


# ------------------------------------------------------------------ filtering
def filter_scheme(sv, user):
    """the part of one scheme's dashboard data this user's pages read"""
    if user.is_admin:
        return sv
    ps = pages(user)
    keys = set(ALWAYS)
    for p in ps:
        keys.update(PAGE_DATA.get(p, []))
    # exceptions raised from the portfolio or the checks are shown only to roles that can open the page they point to
    if 'exceptions' in ps and ({'projects', 'valuation', 'deals'} & set(ps)):
        keys.add('instruments')
    if 'ingestion' in ps:
        keys.add('rules')
    out = {k: v for k, v in sv.items() if k in keys}
    if 'investors' in out:
        fields = set()
        for p in ps:
            fields.update(PAGE_INVESTOR_FIELDS.get(p, []))
        out['investors'] = [{k: v for k, v in i.items() if k in fields} for i in sv['investors']]
    out['files'] = [f for f in sv.get('files', []) if any(p in ps for p in file_pages(f.get('page')))]
    return out


def filter_dashboard(data, user):
    if not data or user.is_admin:
        return data
    return dict(data, schemes={s: filter_scheme(v, user) for s, v in data.get('schemes', {}).items()})


STATE_PAGE = {'audit': 'audit', 'str': 'kyc', 'reports': 'reports', 'regrep': 'reports', 'appr': 'approvals', 'mapOk': 'ingestion',
              'valOk': 'valuation', 'notice': 'projects', 'obl': 'calendar'}


def filter_state(st, user):
    if user.is_admin:
        return st
    ps = set(pages(user))
    out = dict(st)
    for k, page in STATE_PAGE.items():
        if page not in ps and k in out:
            out[k] = [] if isinstance(st[k], list) else {}
    return out

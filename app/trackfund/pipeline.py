"""End-to-end processing of one quarter's upload: classify -> parse -> post -> reconcile -> dashboard view model."""
import os
import re
import json
import time

from .parsing.extract import extract_scheme, opening_schemes, ParseError
from .parsing.util import sha_file
from .engine.books import compute
from .engine.view import scheme_view, dashboard_data

SCHEME_DIR = re.compile(r'^scheme_([A-Za-z0-9]+)_')


def layout_from_dir(root):
    """Find scheme folders, the shared opening-balances workbook and the optional manifest / expected-results files
    under an extracted upload. Accepts the dataset layout (scheme_A_gift/, scheme_B_onshore/, shared/)."""
    root = os.path.abspath(root)
    # descend through single wrapper folders (e.g. repo/dataset/Q2FY27)
    while True:
        entries = [e for e in os.listdir(root) if not e.startswith('.') and e != '__MACOSX']
        if len(entries) == 1 and os.path.isdir(os.path.join(root, entries[0])):
            root = os.path.join(root, entries[0])
            continue
        if not any(SCHEME_DIR.match(e) for e in entries):
            subs = [os.path.join(dp, d) for dp, dns, _ in os.walk(root) for d in dns if SCHEME_DIR.match(d)]
            if subs:
                root = os.path.dirname(subs[0])
        break
    schemes = {}
    opening = None
    manifest = expected = None
    for e in sorted(os.listdir(root)):
        p = os.path.join(root, e)
        m = SCHEME_DIR.match(e)
        if m and os.path.isdir(p):
            files = {}
            for dp, _, fns in os.walk(p):
                for fn in fns:
                    if fn.startswith('.'):
                        continue
                    full = os.path.join(dp, fn)
                    files[os.path.relpath(full, p).replace(os.sep, '/')] = full
            schemes[m.group(1)] = dict(folder=e, files=files)
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if re.match(r'^Opening_Balances_.*\.xlsx$', fn):
                opening = os.path.join(dp, fn)
            elif fn == 'manifest.json':
                manifest = os.path.join(dp, fn)
            elif fn == 'expected_results.json':
                expected = os.path.join(dp, fn)
    return dict(root=root, schemes=schemes, opening=opening, manifest=manifest, expected=expected)


def global_rules(layout, profile):
    rows = []
    root = layout['root']
    if layout.get('manifest'):
        man = json.load(open(layout['manifest']))
        bad = [m['file'] for m in man['files'] if not os.path.exists(os.path.join(root, m['file'])) or sha_file(os.path.join(root, m['file'])) != m['sha256']]
        rows.append(dict(rule='R20', scheme='all', title='Manifest: every listed file exists and matches its SHA-256', status='PASS' if not bad else 'FAIL',
                         left=f"{len(man['files'])} files", right=f"{len(bad)} mismatches", detail='', src='manifest.json'))
    allf = [(f"{s['folder']}/{rel}", p) for s in layout['schemes'].values() for rel, p in s['files'].items()]
    if layout.get('opening'):
        allf.append((os.path.relpath(layout['opening'], root), layout['opening']))
    rec = layout.get('recorded_sha') or {}
    bad = [n for n, p in allf if n in rec and sha_file(p) != rec[n]]
    rows.append(dict(rule='R20', scheme='all', title='Integrity: every stored source file still matches the SHA-256 recorded when it was uploaded', status='PASS' if not bad else 'FAIL',
                     left=f"{len(allf)} files", right=f"{len(bad)} differing", detail=', '.join(bad[:5]), src='file register'))
    terms = [t.lower() for t in profile.get('name_screen_terms', []) if t]
    if terms:
        txt = ' '.join(n for n, _ in allf)
        for n, p in allf:
            if os.path.splitext(p)[1].lower() in ('.csv', '.xml', '.mt940'):
                txt += open(p, errors='ignore').read()
        hits = sum(txt.lower().count(t) for t in terms)
        rows.append(dict(rule='N1', scheme='all', title='Names: the firm name does not appear in file names or text-format files (PDF/xlsx text is scanned in the QA step)',
                         status='PASS' if not hits else 'FAIL', left='occurrences', right=str(hits), detail='', src='manifest + csv/xml/mt940'))
    return rows


def run_layout(layout, profile, log=None):
    """Process every scheme in an extracted upload. Returns dict(data=dashboard DATA, books={sid: books}, bundles={sid: X}, log=[...])"""
    log = log if log is not None else []
    t0 = time.time()
    if not layout['schemes']:
        raise ParseError('No scheme folders found (expected folders named like scheme_A_..., scheme_B_...)')
    if not layout['opening']:
        raise ParseError('Opening balances workbook (Opening_Balances_*.xlsx) not found')
    expected = json.load(open(layout['expected'])) if layout.get('expected') else None
    have = opening_schemes(layout['opening'])
    views, books, bundles = {}, {}, {}
    for sid in sorted(layout['schemes']):
        if sid not in have:
            raise ParseError(f"Opening balances workbook has no sheets for scheme {sid} (found {have})")
        s = layout['schemes'][sid]
        log.append(('k', f"Scheme {sid}: reading {len(s['files'])} files from {s['folder']}/"))
        X = extract_scheme(sid, s['files'], layout['opening'], log)
        sp = profile.get('schemes', {}).get(sid, {})
        settings = dict(journal_seq_start=sp.get('journal_seq_start', 1), accrual_history=sp.get('accrual_history', {}))
        Bk = compute(X, settings, expected)
        v = scheme_view(X, Bk, profile)
        npass = sum(1 for r in Bk['rules'] if r['status'] == 'PASS')
        log.append(('g', f"Scheme {sid}: {len(Bk['journals'])} journals posted; NAV {Bk['nav_close']} {X['opening']['unit']}; {npass} of {len(Bk['rules'])} checks pass, "
                         f"{sum(1 for r in Bk['rules'] if r['status'] == 'FAIL')} fail"))
        views[sid], books[sid], bundles[sid] = v, Bk, X
    g = global_rules(layout, profile)
    data = dashboard_data(views, profile.get('manager', {}), g)
    log.append(('g', f"Done in {time.time() - t0:.1f}s"))
    return dict(data=data, books=books, bundles=bundles, global_rules=g, log=log)

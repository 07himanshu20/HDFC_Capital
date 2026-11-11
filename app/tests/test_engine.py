"""The books rebuilt from the source files must equal the golden totals and the dashboard the client approved."""
import json
import re
from decimal import Decimal as D
from pathlib import Path

import pytest

from trackfund.catalog import classify
from trackfund.pipeline import layout_from_dir, run_layout

PROFILE = json.load(open(Path(__file__).resolve().parents[1] / 'seed' / 'org_profile.json'))
SNAPSHOT = json.load(open(Path(__file__).parent / 'fixtures' / 'dashboard_snapshot.json'))

# rules that differ from the original demo on purpose (see docs/DATA_FLOW.md, "Checks")
RULE_CHANGES = {('G2', 'A'), ('R20', 'all'), ('N1', 'all')}


@pytest.fixture(scope='module')
def result(dataset):
    return run_layout(layout_from_dir(dataset), PROFILE)


def test_every_file_is_classified(dataset):
    man = json.load(open(dataset / 'manifest.json'))
    for f in man['files']:
        d, _ = classify(f['file'].split('/', 1)[1])
        assert d is not None, f['file']
        assert set(d.feeds) <= set(f['feeds']), f['file']


def test_no_check_fails(result):
    for sid, b in result['books'].items():
        fails = [r for r in b['rules'] if r['status'] == 'FAIL']
        assert not fails, fails


def test_golden_totals(result, dataset):
    exp = json.load(open(dataset / 'expected_results.json'))
    for sid, b in result['books'].items():
        e = exp[sid]
        assert b['nav_close'] == D(e['nav_close'])
        assert b['nav_open'] == D(e['nav_open'])
        for g, v in e['closing_tb'].items():
            assert b['close_tb'].get(int(g), D(0)) == D(v), (sid, g)
        for k, c in e['capital_accounts'].items():
            assert b['capital'][k]['closing'] == D(c['closing'])
            assert b['capital'][k]['nav_per_unit'] == D(c['nav_per_unit'])
        assert len(b['journals']) == e['counts']['journals_q2']
        assert b['units_total'] == e['units_total']
        g1 = [r for r in b['rules'] if r['rule'] == 'G1']
        assert g1 and g1[0]['status'] == 'PASS'


def _num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 9)
    if isinstance(v, str) and re.fullmatch(r'-?\d[\d,]*(\.\d+)?', v):
        return round(float(v.replace(',', '')), 9)
    return v


def _diff(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            if k not in a or k not in b:
                # added by the product (not in the original demo): meta.period, val_dates.prior, the regulator report model
                if not (path.endswith('.meta') and k == 'period') and not (path.endswith('.val_dates') and k == 'prior') and k != 'reg_report':
                    out.append(f"{path}.{k} missing on one side")
            else:
                _diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: {len(a)} vs {len(b)} items")
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", out)
    elif _num(a) != _num(b):
        out.append(f"{path}: built {a!r} vs snapshot {b!r}")


def test_dashboard_equals_snapshot(result):
    built = json.loads(json.dumps(result['data']))
    for sid in ('A', 'B'):
        b, s = built['schemes'][sid], SNAPSHOT['schemes'][sid]
        keep = lambda rules: [r for r in rules if (r['rule'], r['scheme']) not in RULE_CHANGES and r['rule'] != 'R15']
        b_rules, s_rules = keep(b.pop('rules')), keep(s.pop('rules'))
        out = []
        _diff(b, s, f"schemes.{sid}", out)
        _diff(b_rules, s_rules, f"schemes.{sid}.rules", out)
        s['rules'] = s_rules
        assert not out, '\n'.join(out[:30])
    assert built['gl'] == SNAPSHOT['gl']
    assert built['manager'] == SNAPSHOT['manager']


def test_tampered_file_is_caught(dataset, tmp_path):
    """change one amount in the bank CSV: the cross-format bank check must fail"""
    import shutil
    work = tmp_path / 'ds'
    shutil.copytree(dataset, work)
    p = work / 'scheme_A_gift' / 'IBU_Statement_SchemeA_USD_Jul-Sep26.csv'
    txt = p.read_text()
    assert '"525,000.00"' in txt
    p.write_text(txt.replace('"525,000.00"', '"525,100.00"', 1))
    res = run_layout(layout_from_dir(work), PROFILE)
    r3 = [r for r in res['books']['A']['rules'] if r['rule'] == 'R3' and 'CSV' in r['title']]
    assert r3 and r3[0]['status'] == 'FAIL'


def test_regulator_workbook(result, dataset, tmp_path):
    """The IFSCA / SEBI workbook is written in last quarter's filed layout, reads back with the prior-report parser and ties to the books."""
    import openpyxl
    from trackfund.engine import regreport
    from trackfund.parsing.extract import parse_prior_report

    for sid, folder in (('A', 'scheme_A_gift'), ('B', 'scheme_B_onshore')):
        m = json.loads(json.dumps(result['data']['schemes'][sid]['reg_report']))      # as stored with the run
        assert m['ok'], m['ties']
        b = result['books'][sid]
        books = dict(nav=b['nav_close'], drawn=-b['close_tb'][3100], cash=b['close_tb'][1100], investments=b['close_tb'][1200],
                     committed=D(str(result['data']['schemes'][sid]['meta']['committed'])))
        p = tmp_path / m['file_name']
        regreport.write_workbook(m, [['Prepared by', 'test'], ['Filed on', ''], ['Filed by', '']], p)
        ok, checks = regreport.verify_workbook(p, books, parse_prior_report)
        assert ok, checks
        assert len(checks) == 9

        # next quarter, the generated file is recognised and read as the prior report
        assert classify(m['file_name'])[0].key == 'prior_report'
        assert regreport.title_base(parse_prior_report(str(p))['title'], 'x') == m['title']

        # same sheets, labels and column headings as the report as filed
        prior = next((dataset / folder).glob('*_as_filed.xlsx'))
        a, g = openpyxl.load_workbook(prior), openpyxl.load_workbook(p)
        assert a.sheetnames == g.sheetnames
        labels = lambda wb: {r[0] for r in wb['Report'].iter_rows(values_only=True) if r[0] and not str(r[0]).startswith(('PART D', 'IFSCA q', 'SEBI q'))}
        assert labels(a) <= labels(g)
        for sh in ('Investments', 'Investors'):
            assert [c.value for c in a[sh][4]] == [c.value for c in g[sh][4]]

        # a changed figure is caught by the read-back
        ws = g['Report']
        row = next(r for r in ws.iter_rows() if r[0].value == 'Net asset value')
        row[1].value = row[1].value + 0.0001
        p2 = tmp_path / ('changed_' + m['file_name'])
        g.save(p2)
        ok, checks = regreport.verify_workbook(p2, books, parse_prior_report)
        assert not ok and {c[0] for c in checks if not c[3]} == {'Net asset value', 'Part C total equals the NAV line'}

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
# keys the product added to the dashboard data (not in the original demo)
PRODUCT_KEYS = {'reg_report', 'fx_info', 'aml', 'screened', 'reportable', 'selfcert', 'kyc_docs', 'screening', 'cp', 'filings'}


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
                # added by the product (not in the original demo): meta.period, val_dates.prior, the regulator report model,
                # fx_info (rate pair, source, quarter-end and Tally rates for the page captions), and what the KYC and Deals pages
                # read from the files instead of fixed text: aml, investor KYC documents / screening, instrument CP checklists / filings
                if not (path.endswith('.meta') and k == 'period') and not (path.endswith('.val_dates') and k == 'prior') and k not in PRODUCT_KEYS:
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


def test_fx_captions_come_from_the_files(result):
    """The FX, quarter-close and Tally pages print the pair, source, quarter-end and Tally rates sent with the data, not fixed text."""
    data = json.loads(json.dumps(result['data']))
    a = data['schemes']['A']['fx_info']
    assert a['pair'] == 'USD/INR' and a['first'] == '2026-07-01' and a['last'] == a['close_date'] == '2026-09-30'
    assert _num(a['close_rate']) == 89.4 and _num(a['memo_rate']) == 89.4
    assert len(a['sources']) == len(data['schemes']['A']['fx']) == 66 and set(a['sources']) == {'FBIL reference rate (synthetic)'}
    b = data['schemes']['B']['fx_info']
    assert b['close_rate'] is None and b['memo_rate'] is None and b['sources'] == []


def test_fx_pik_is_converted_for_a_usd_scheme(result):
    """PIK interest accrues in INR. A USD scheme books it, capitalises it and adds it to cost at the quarter-end rate
    (the dataset has no PIK in scheme A, so 2% PIK is set on I-A2 here)."""
    import copy
    from trackfund.engine.books import compute
    from trackfund.parsing.util import q

    base = result['books']['A']
    X = copy.deepcopy(result['bundles']['A'])
    row = next(r for r in X['deal']['instruments'] if r['Instrument ID'] == 'I-A2')
    row[next(k for k in row if 'PIK coupon' in k)] = 2
    Bk = compute(X, dict(journal_seq_start=1))
    rate = X['fx'][X['period']['q_end']]
    s = Bk['sched']['I-A2']
    p_inr, p_fn = s['pik'], s['pik_fn']
    assert p_inr > 0 and p_fn == q(p_inr * 10 / rate) and p_fn < p_inr / 8           # USD m, not INR cr
    accr = next(j for j in Bk['journals'] if j['kind'] == 'ACCR_PIK')
    cap = next(j for j in Bk['journals'] if j['kind'] == 'PIK_CAP')
    assert [(l['gl'], l['amt']) for l in accr['lines']] == [(1300, p_fn), (4110, -p_fn)]
    assert [(l['gl'], l['amt']) for l in cap['lines']] == [(1200, p_fn), (1300, -p_fn)]
    assert all(l['txn_ccy'] == 'INR' and l['txn_amt'] == p_inr and l['rate'] == rate for l in accr['lines'] + cap['lines'])
    assert Bk['cost']['I-A2'] == base['cost']['I-A2'] + p_fn and Bk['principal']['I-A2'] == base['principal']['I-A2'] + p_inr
    assert Bk['tq'][4110] == -p_fn and Bk['close_tb'][1300] == 0
    assert Bk['accr_hist']['I-A2'][-1]['fn'] == s['cash_fn'] + p_fn
    # the translation is still recomputed from INR principal and USD cost, and the FX check passes
    assert next(r for r in Bk['rules'] if r['rule'] == 'R9')['status'] == 'PASS'


def test_fx_file_without_quarter_end_rate_is_refused(dataset, tmp_path):
    """The translation needs the rate of the quarter's last day: without it the upload is refused with a clear reason."""
    import shutil
    from trackfund.parsing.extract import ParseError
    work = tmp_path / 'ds'
    shutil.copytree(dataset, work)
    p = next((work / 'scheme_A_gift').glob('FX_Rates_*.csv'))
    lines = p.read_text().splitlines(keepends=True)
    assert lines[-1].startswith('30-Sep-2026')
    p.write_text(''.join(lines[:-1]))
    with pytest.raises(ParseError, match='no rate for 30-Sep-2026'):
        run_layout(layout_from_dir(work), PROFILE)


def test_kyc_and_deals_pages_read_the_files(result):
    """Screening runs, KYC documents, FIU registration, Form 61B, CP checklists and filings are sent as the files give them."""
    data = json.loads(json.dumps(result['data']))
    a, b = data['schemes']['A'], data['schemes']['B']
    i3 = next(i for i in a['investors'] if i['id'] == 'LP-A3')
    assert i3['screened'] == '2026-10-12' and i3['reportable'] is True
    assert [(r['date'], r['hits']) for r in i3['screening']] == [('2026-10-12', 1)] and i3['screening'][0]['outcome'].startswith('False positive')
    assert len(i3['kyc_docs']) == 5 and i3['kyc_docs'][0]['received'] == '2025-09-19' and i3['kyc_docs'][0]['file'].startswith('KYC_Pack_')
    assert next(i for i in a['investors'] if i['id'] == 'LP-A4')['kyc_docs'] == []
    assert a['aml']['fiu']['reg_no'] == 'FIUREID/IFSC/9999999' and a['aml']['fiu']['reg_date'] == '2025-09-18'
    assert a['aml']['form61b']['period'] == 'CY2025' and a['aml']['form61b']['filed'] == '2026-05-28'
    assert b['aml']['fiu'] is None and [(n['investor'], _num(n['amount'])) for n in b['aml']['networth']] == [('LP-B3', 412.6)]
    assert not any(i['reportable'] for i in b['investors'])

    ia1 = next(x for x in a['instruments'] if x['id'] == 'I-A1')
    cp = ia1['cp'][0]
    assert cp['tranche'] == 2 and cp['file'] == 'CP_Checklist_I-A1_T2.xlsx' and len(cp['rows']) == 8 and all(r['met'] for r in cp['rows'])
    assert [r['date'] for r in cp['rows']] == sorted(r['date'] for r in cp['rows'])                       # in date order
    assert cp['rows'][0]['condition'].startswith('Investment committee') and cp['rows'][0]['date'] == '2026-07-24'
    fl = {g['kind']: g for g in ia1['filings']}
    assert (fl['charge']['ref'], fl['charge']['event'], fl['charge']['due'], fl['charge']['filed']) == ('ZZ99990001', '2026-08-05', '2026-09-04', '2026-08-10')
    assert (fl['fema']['ref'], fl['fema']['due'], fl['fema']['filed'], fl['fema']['status_date']) == ('FCGPR/2026/AD999/000999', '2026-09-04', '2026-08-28', '2026-09-02')
    assert (fl['pricing']['ref'], fl['pricing']['filed']) == ('BSC/FEMA/26-27/099', '2026-08-03')
    ib1 = next(x for x in b['instruments'] if x['id'] == 'I-B1')
    assert len(ib1['cp'][0]['rows']) == 6 and [g['kind'] for g in ib1['filings']] == ['charge']

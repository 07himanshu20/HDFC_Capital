"""Renderers part 2: valuation, deal docs, MIS, KYC, compliance, invoices, registers, shared."""
import csv, io
from decimal import Decimal as D
from datetime import date, timedelta
import openpyxl
from openpyxl.styles import Font, Alignment
from .core import q, dmy, MEMO, Q_START, Q_END, OPEN_DT, GL, MANAGER, MAKER, CHECKER
from .base import *
from .files1 import ctx, lh, sec_name

MONTHS = [(date(2026, 7, 31), 'Jul26', 'Jul-26'), (date(2026, 8, 31), 'Aug26', 'Aug-26'), (date(2026, 9, 30), 'Sep26', 'Sep-26')]
f4 = lambda v: f"{D(v):,.4f}"; f2 = lambda v: f"{D(v):,.2f}"


def r_val(o, B):
    S, A, F, mf, base, cur = ctx(B); vd = S['val_dates']; pr = S['providers']; ins = {x['id']: x for x in S['instruments']}
    rows, inp, sens = [], [], []
    for v in B.val_items:
        x = ins[v['instrument']]; m = x['mis']
        rows.append([x['id'], x['isin'], v['method'], f"Level {v['level']}", v['principal_inr'], v['accrued_inr'], v['adj_inr'], v['fv_inr'], v['prior_adj_inr'], v['adj_inr'] - v['prior_adj_inr']])
        inp.append([x['id'], x['spv_name'], v['y'], v['y_prior'], q(D(sum(m['sold'])) / 3, 2), m['price'], m['cost_total'] - m['cost'][2], D(m['cons'][2]), m['cum'] + sum(m['sold']), v['note']])
        dlt = q(v['principal_inr'] * (D('0.024') if x['kind'] == 'NCD' else D('0.08')), 4)
        sens.append([x['id'], v['fv_inr'] - dlt, v['fv_inr'], v['fv_inr'] + dlt])
    H1 = ['Instrument', 'ISIN', 'Method', 'Hierarchy', 'Principal (INR cr)', 'Accrued interest (INR cr)', 'FV adjustment (INR cr)', 'Fair value (INR cr)', 'FV adjustment at 31-Mar-2026 (INR cr)', 'Change vs 31-Mar-2026 (INR cr)']
    H2 = ['Instrument', 'Project SPV', 'Yield / discount rate', 'Prior-cycle rate', 'Sales velocity (units/month)', 'Average price (INR cr/unit)', 'Cost to complete (INR cr)', 'Construction %', 'Cumulative units sold', 'Valuer note']
    H3 = ['Instrument', 'Fair value at +100 bp (INR cr)', 'Base fair value (INR cr)', 'Fair value at -100 bp (INR cr)']
    ref = f"MVA/VAL/{S['short']}/30SEP26"
    meta = [('Report reference', ref), ('Valuation date', dmy(Q_END)), ('Report date', dmy(vd['report'])), ('Client', f"{S['providers']['trustee']} A/c {S['name']}"),
            ('Registered valuer', f"{pr['valuer']}, {pr['valuer_reg']}"), ('Standards', 'IPEV Valuation Guidelines; Ind AS 113 (Level 3 inputs)'),
            ('Total fair value (INR cr)', f4(sum(v['fv_inr'] for v in B.val_items))), ('Independence', 'Confirmed - no other engagement with the manager or investee groups')]
    st = lambda rws, cols: [[(f4(c) if isinstance(c, D) and k in cols else c) for k, c in enumerate(r)] for r in rws]
    blocks = [kv(meta), h('1. Scope and basis'),
              p('We were engaged to estimate the fair value of the unquoted debt and convertible instruments held by the scheme as at the valuation date. '
                'Fair value is the price that would be received to sell an asset in an orderly transaction between market participants. Inputs were taken from the debenture documents, '
                'developer MIS for July to September 2026, covenant certificates and discussions with the investment team.'),
              h('2. Summary of fair values'), table(H1, st(rows, range(4, 10)), range(4, 10)),
              h('3. Key inputs'), table(H2, [[r[0], r[1], r[2], r[3], f2(r[4]), f2(r[5]), f2(r[6]), f"{r[7]}%", r[8], r[9]] for r in inp], (4, 5, 6, 7, 8)),
              h('4. Sensitivity to yield / discount rate'), table(H3, st(sens, range(1, 4)), range(1, 4)),
              h('5. Limitations'), p('This report is for the use of the scheme, its trustee, auditors and investors. It is not an opinion on recoverability of security.'),
              sign('Girish Venkataraghavan', 'Partner, Registered Valuer (Securities or Financial Assets)', pr['valuer'])]
    o.pdf(f"{F}/Valuation_Report_{S['short']}_30Sep26.pdf", doc('valuer', pr['valuer'], f"Registered Valuer Entity · {pr['valuer_reg']} · 99 Fictional Chambers, Fort, Mumbai 400001",
          'VALUATION REPORT AS AT 30 SEPTEMBER 2026', blocks, f"{ref} · Strictly confidential"), ['valuation_cycle', 'valuation_item'], 'Independent registered valuer', 'Valuation', landscape=True)
    wb = openpyxl.Workbook()
    kvsheet(wb, 'Cover', [f"{pr['valuer']} - valuation inputs workbook", ref], [(k, v) for k, v in meta] + [('Received by FME', vd['received']), ('Valuation date (date)', Q_END), ('Report date (date)', vd['report'])], first=True)
    sheet(wb, 'Summary', ['Summary of fair values (INR cr)'], H1, rows, {3: 40}); sheet(wb, 'Inputs', ['Key inputs'], H2, inp, {2: 36, 10: 60}); sheet(wb, 'Sensitivity', ['Sensitivity'], H3, sens)
    o.xlsx(f"{F}/Valuation_Inputs_{S['short']}_30Sep26.xlsx", wb, ['valuation_item'], 'Independent registered valuer', 'Valuation')


def r_deal(o, B):
    S, A, F, mf, base, cur = ctx(B); tr = S['providers']['trustee']
    wb = openpyxl.Workbook()
    sheet(wb, 'Instruments', [f"{S['name']} - deal master"],
          ['Instrument ID', 'Project SPV', 'SPV legal name', 'Developer', 'City', 'Micro-market', 'Kind', 'ISIN', 'Face value (INR)', 'Cash coupon % p.a.', 'PIK coupon % p.a.', 'Day count',
           'Coupon frequency', 'Moratorium (months)', 'Tenor (months)', 'Prepayment premium %', 'Security', 'Charge filing ref', 'RERA No', 'Homes planned', 'Escrow bank'],
          [[x['id'], x['spv'], x['spv_name'], x['developer'], x['city'], x['micro'], x['kind'], x['isin'], x['fv'], x['cash'] * 100, x['pik'] * 100, 'ACT/365',
            'Quarterly, calendar quarter-end' if x['cash'] else 'n/a', 0, x['tenor'], D('2.00') if x['kind'] == 'NCD' else D('0.00'), x['security'], x['chg'], x['rera'], x['homes'], x['escrow']] for x in S['instruments']],
          {3: 36, 17: 60}, first=True)
    trs = []
    for x in S['instruments']:
        for t in x['tranches']:
            cur_q = t['date'] >= Q_START
            trs.append([x['id'], t['no'], t['date'], t['inr'], t['rate'] if A else None, t['fn'] if A else None, t['units'], t['date'],
                        f"CP_Checklist_{x['id']}_T{t['no']}.xlsx" if cur_q else 'on file (prior period)',
                        (f"FC-GPR - FCGPR_Acknowledgement_{x['id']}_T{t['no']}.pdf" if cur_q else 'FC-GPR - on file (prior period)') if A else 'n/a (domestic)'])
    sheet(wb, 'Tranches', ['Tranche register'], ['Instrument ID', 'Tranche no', 'Disbursement date', 'Amount (INR cr)', 'FX rate (USD/INR)', 'Amount (USD m)', 'Units allotted',
                                                'Demat credit date', 'CP checklist', 'FEMA filing'], trs, {9: 34, 10: 44})
    sheet(wb, 'Covenants', ['Financial covenants tested quarterly on developer MIS'], ['Instrument ID', 'Test', 'Minimum', 'Basis'],
          [r for x in S['instruments'] for r in ([x['id'], 'Sales velocity (units sold in quarter)', D(x['cov']['vel_min']), 'Units sold in the calendar quarter per MIS'],
                                                 [x['id'], 'Collection cover', x['cov']['cover_min'], f"Collections in quarter / covenant debt service of INR {x['cov']['ds']:.2f} cr"])], {2: 40, 4: 60})
    sheet(wb, 'Covenant basis', ['Covenant debt-service amounts'], ['Instrument ID', 'Covenant debt service (INR cr)'], [[x['id'], x['cov']['ds']] for x in S['instruments']])
    o.xlsx(f"{F}/Deal_Master_{S['short']}.xlsx", wb, ['project_spv', 'instrument', 'tranche', 'covenant_test'], 'Investment team', 'Instruments & accruals / Deals, CPs & filings')
    for x in S['instruments']:
        nm = f"{'CCD_Subscription_Summary' if x['kind'] == 'CCD' else 'DTD_Summary'}_{x['id']}.pdf"
        o.pdf(f"{F}/{nm}", doc('law', 'Lexwell Partners LLP', 'Advocates & Solicitors · Summary of principal terms (not a substitute for the executed documents)',
              f"{'DEBENTURE SUBSCRIPTION AGREEMENT' if x['kind'] == 'CCD' else 'DEBENTURE TRUST DEED'} - SUMMARY - {x['id']}",
              [kv([('Instrument ID', x['id']), ('Issuer', x['spv_name']), ('Developer group', x['developer']), ('Subscriber', f"{tr} A/c {S['name']}"), ('Instrument', x['kind_long']),
                   ('ISIN', x['isin']), ('Face value (INR)', ind(x['fv'])), ('Aggregate sanctioned amount (INR cr)', f2(sum(t['inr'] for t in x['tranches']))),
                   ('Cash coupon', f"{x['cash'] * 100:.2f}% p.a." if x['cash'] else 'None - return through conversion and project profit share'),
                   ('PIK coupon', f"{x['pik'] * 100:.2f}% p.a., capitalised quarterly" if x['pik'] else 'None'), ('Day count', 'ACT/365, from the day after allotment to period end inclusive'),
                   ('Coupon dates', 'Calendar quarter-ends' if x['cash'] else 'n/a'), ('Tenor', f"{x['tenor']} months"), ('Security', x['security']), ('Charge filing', x['chg']),
                   ('Sales-velocity covenant', f"Minimum {x['cov']['vel_min']} units per quarter"), ('Collection-cover covenant', f"Minimum {x['cov']['cover_min']}x on covenant debt service of INR {x['cov']['ds']:.2f} cr"),
                   ('Covenant reporting', 'Developer CFO certificate within 15 days of each quarter-end')])]),
              ['instrument'], 'Fund counsel', 'Deals, CPs & filings')
        for t in [t for t in x['tranches'] if t['date'] >= Q_START]:
            tn = f"{x['id']}_T{t['no']}"
            o.pdf(f"{F}/Tranche{t['no']}_Disbursement_Advice_{x['id']}.pdf", doc('scheme', *lh(S), f"DISBURSEMENT ADVICE - {x['id']} TRANCHE {t['no']}",
                  [kv([('Instrument ID', x['id']), ('Tranche no', t['no']), ('Value date', dmy(t['date'])), ('Beneficiary', x['spv_name']), ('Amount (INR cr)', f2(t['inr'])),
                       ('Amount (INR)', ind(t['inr'] * 10000000))] + ([('FX rate (USD/INR reference rate)', t['rate']), ('Amount remitted (USD)', us(base(t['fn'])))] if A else []) +
                      [('Units allotted', f"{t['units']:,}"), ('Demat credit date', dmy(t['date'])), ('Bank reference', f"DISB {x['id']} T{t['no']}"), ('CP checklist', 'Complete - all conditions met'),
                       ('Prepared by (maker)', MAKER), ('Approved by (checker)', CHECKER)])]), ['tranche'], 'FME finance', 'Deals, CPs & filings')
            cps = [('Board and shareholder resolutions of the issuer', dmy(t['date'] - timedelta(days=9)), 'on file'), ('Drawdown request signed by two directors', dmy(t['date'] - timedelta(days=7)), 'on file'),
                   ('No-default and covenant compliance certificate', dmy(t['date'] - timedelta(days=5)), 'on file'), ('RERA registration valid; escrow account operational', dmy(t['date'] - timedelta(days=5)), 'on file'),
                   ('Security cover confirmed by debenture trustee; charge modification (CHG-9)', dmy(t['date'] + timedelta(days=5 if A else 3)), f"Charge_Filing_CHG9_{x['id']}.pdf")]
            if A: cps += [('Pricing certificate from chartered accountant', '03-Aug-2026', f"Pricing_Certificate_{tn}.pdf"),
                          ('FC-GPR filed within 30 days of allotment', 'filed 28-Aug-2026, ack FCGPR/2026/AD999/000999', f"FCGPR_Acknowledgement_{tn}.pdf")]
            cps.append(('Investment committee approval for tranche release', dmy(t['date'] - timedelta(days=12)), 'on file'))
            wb = openpyxl.Workbook()
            sheet(wb, 'CP checklist', [f"Conditions precedent / subsequent - {x['id']} tranche {t['no']}", f"Disbursement date {dmy(t['date'])}"],
                  ['#', 'Condition', 'Met', 'Date / detail', 'Evidence file'], [[k, c, 'Yes', d_, e] for k, (c, d_, e) in enumerate(cps, 1)], {2: 62, 4: 44, 5: 40}, first=True)
            o.xlsx(f"{F}/CP_Checklist_{tn}.xlsx", wb, ['cp_item'], 'Investment team / legal', 'Deals, CPs & filings')
            amt_sec = sum(tt['inr'] for tt in x['tranches'])
            o.pdf(f"{F}/Charge_Filing_CHG9_{x['id']}.pdf", doc('govt', 'MINISTRY OF CORPORATE AFFAIRS - SPECIMEN', 'Certificate of registration of modification of charge (synthetic)',
                  'FORM CHG-9 - ACKNOWLEDGEMENT', [kv([('Form', 'CHG-9'), ('SRN', x['chg'].split('SRN ')[1]), ('Company', x['spv_name']), ('Charge holder', f"{tr} (debenture trustee)"),
                                                     ('Instrument ID', x['id']), ('Type', 'Modification of charge - enhancement on tranche 2'), ('Amount secured (INR cr)', f2(amt_sec)),
                                                     ('Date of modification', dmy(t['date'])), ('Filed date', dmy(t['date'] + timedelta(days=5 if A else 3))), ('Status', 'Registered')])]),
                  ['charge_filing', 'evidence'], 'ROC / company secretary of the SPV', 'Deals, CPs & filings')
            if A:
                o.pdf(f"{F}/FCGPR_Acknowledgement_{tn}.pdf", doc('govt', 'FOREIGN INVESTMENT REPORTING - SPECIMEN', 'Single Master Form acknowledgement through the Authorised Dealer bank (synthetic)',
                      'FORM FC-GPR - ACKNOWLEDGEMENT', [kv([('Form', 'FC-GPR'), ('Acknowledgement No', 'FCGPR/2026/AD999/000999'), ('Investee company', x['spv_name']),
                                                           ('Foreign investor', f"{tr} A/c {S['name']} (IFSC)"), ('Instrument ID', x['id']), ('Tranche no', t['no']),
                                                           ('Allotment date', dmy(t['date'])), ('Due date', dmy(t['date'] + timedelta(days=30))), ('Filed date', '28-Aug-2026'),
                                                           ('Acknowledgement date', '02-Sep-2026'), ('Amount of consideration (INR cr)', f2(t['inr'])), ('Units allotted', f"{t['units']:,}"),
                                                           ('Authorised Dealer', 'Deccan Union Bank Ltd, AD Category-I'), ('Status', 'Approved')])]),
                      ['fema_filing', 'evidence'], 'AD bank / RBI reporting portal', 'Deals, CPs & filings')
                o.pdf(f"{F}/Pricing_Certificate_{tn}.pdf", doc('vendor', 'Bhatawdekar Sule & Co', 'Chartered Accountants · FRN 999999W · Pune', 'CERTIFICATE ON PRICING OF INSTRUMENTS',
                      [kv([('Certificate No', 'BSC/FEMA/26-27/099'), ('Certificate date', '03-Aug-2026'), ('Issuer', x['spv_name']), ('Instrument ID', x['id']), ('Tranche no', t['no']),
                           ('Face value per instrument (INR)', ind(x['fv'])), ('Issue price per instrument (INR)', ind(x['fv'])), ('Number of instruments', f"{t['units']:,}"),
                           ('Basis', 'Issue at face value; coupon within the range for comparable secured project debt')]),
                       sign('Ojas Bhatawdekar', 'Partner, M. No. 999999', 'Bhatawdekar Sule & Co')]), ['evidence'], 'Chartered accountant', 'Deals, CPs & filings')


def mis_rows(x, upto):
    m = x['mis']; out = []; cum = m['cum']
    for k in range(upto + 1):
        cum += m['sold'][k]
        out.append(dict(label=MONTHS[k][2], sold=m['sold'][k], cum=cum, value=q(m['price'] * m['sold'][k], 2), coll=m['coll'][k], esc=m['escrow'][k], cons=D(m['cons'][k]),
                        cost=m['cost'][k], ctc=m['cost_total'] - m['cost'][k]))
    return out


def r_mis(o, B):
    S, A, F, mf, base, cur = ctx(B); B.cov = []
    for x in S['instruments']:
        m = x['mis']
        for k, (me, tag, lab) in enumerate(MONTHS):
            rows = mis_rows(x, k); wb = openpyxl.Workbook()
            if m['layout'] == 1:
                kvsheet(wb, 'Cover', [f"{x['developer']} - MONTHLY PROJECT MIS", f"Report month: {lab}"],
                        [('Project', f"{x['micro']} residential project"), ('SPV', x['spv_name']), ('Developer', x['developer']), ('Location', f"{x['micro']}, {x['city']}"),
                         ('RERA No', x['rera']), ('Homes planned', x['homes']), ('Escrow bank', x['escrow']), ('Report month end', me), ('Prepared by', 'Project finance - MIS cell')], first=True)
                sheet(wb, 'Sales', ['Sales performance'], ['Month', 'Units sold', 'Cumulative units sold', 'Sales value (INR cr)'], [[r['label'], r['sold'], r['cum'], r['value']] for r in rows])
                sheet(wb, 'Collections', ['Collections and escrow'], ['Month', 'Collections (INR cr)', 'RERA escrow balance (INR cr)'], [[r['label'], r['coll'], r['esc']] for r in rows])
                sheet(wb, 'Construction', ['Construction and cost'], ['Month', 'Construction %', 'Cost incurred to date (INR cr)', 'Cost to complete (INR cr)'], [[r['label'], r['cons'], r['cost'], r['ctc']] for r in rows])
                for ws in wb.worksheets: ws.page_setup.orientation = 'landscape'
            else:
                ws = wb.active; ws.title = 'MIS'
                ws.cell(1, 1, f"{x['developer'].upper()} :: PROJECT {x['micro'].upper()} :: MIS FOR {lab.upper()}").font = Font(bold=True, size=13); ws.merge_cells('A1:I1')
                for r, t in enumerate([f"Company: {x['spv_name']}", f"RERA Regn: {x['rera']}    Total flats: {x['homes']}", f"Escrow with: {x['escrow']}    Site: {x['micro']}, {x['city']}"], 2): ws.cell(r, 1, t)
                ws.cell(6, 1, 'Month'); ws.merge_cells('A6:A7'); ws.cell(6, 2, 'Sales'); ws.merge_cells('B6:D6'); ws.cell(6, 5, 'Cash'); ws.merge_cells('E6:F6'); ws.cell(6, 7, 'Works'); ws.merge_cells('G6:I6')
                for c, t in enumerate(['Nos. booked', 'Cum. nos.', 'Booking value (Rs cr)', 'Receipts (Rs cr)', 'Escrow bal. (Rs cr)', '% complete', 'Spent to date (Rs cr)', 'Balance cost (Rs cr)'], 2): ws.cell(7, c, t)
                for rr in (6, 7):
                    for c in range(1, 10): ws.cell(rr, c).font = Font(bold=True); ws.cell(rr, c).alignment = Alignment(horizontal='center', wrap_text=True)
                for r, d in enumerate(rows, 8):
                    for c, v in enumerate([d['label'], d['sold'], d['cum'], d['value'], d['coll'], d['esc'], d['cons'], d['cost'], d['ctc']], 1): ws.cell(r, c, wr(v))
                ws.cell(8 + len(rows) + 1, 1, 'Note: figures as per books of the project company; unaudited.')
                for c in 'ABCDEFGHI': ws.column_dimensions[c].width = 16
            o.xlsx(f"{F}/Developer_MIS_{x['spv']}_{tag}.xlsx", wb, ['mis_month'], f"Developer ({x['developer']})", 'Project monitoring')
        vel = sum(m['sold']); coll = sum(m['coll']); cover = q(coll / x['cov']['ds'], 2)
        tests = [('Sales velocity (units sold in quarter)', D(x['cov']['vel_min']), D(vel), vel >= x['cov']['vel_min']), ('Collection cover (times)', x['cov']['cover_min'], cover, cover >= x['cov']['cover_min'])]
        B.cov.append(dict(instrument=x['id'], spv=x['spv'], tests=tests, vel=vel, coll=coll, cover=cover))
        cfo = {'SPV-A1': 'Mrunal Kshirsagar-Dhume', 'SPV-A2': 'Tejas Annigeri', 'SPV-B1': 'Kavya Thimmaiah', 'SPV-B2': 'Sudhakar Yellapragada'}[x['spv']]
        blocks = [kv([('Certificate date', '15-Oct-2026'), ('Test date', dmy(Q_END)), ('Issuer', x['spv_name']), ('Instrument ID', x['id']), ('Addressed to', f"{S['providers']['trustee']} A/c {S['name']}"),
                      ('Units sold in quarter', vel), ('Collections in quarter (INR cr)', f2(coll)), ('Covenant debt service (INR cr)', f2(x['cov']['ds']))]),
                  table(['Test', 'Minimum', 'Actual', 'Result'], [[n, f2(mn), f2(ac), 'PASS' if ok else 'BREACH'] for n, mn, ac, ok in tests], (1, 2)),
                  p('I certify that the above is drawn from the books of account and the monthly MIS of the company for July, August and September 2026.' +
                    ('' if all(t[3] for t in tests) else ' The company acknowledges the breaches noted above and will submit a cure plan within 30 days.')),
                  sign(cfo, 'Chief Financial Officer', x['spv_name'])]
        o.pdf(f"{F}/Covenant_Certificate_{x['spv']}_30Sep26.pdf", doc('dev1' if m['layout'] == 1 else 'dev2', x['developer'], f"{x['spv_name']} · {x['micro']}, {x['city']}",
              'COVENANT COMPLIANCE CERTIFICATE - QUARTER ENDED 30 SEPTEMBER 2026', blocks), ['covenant_test'], f"Developer CFO ({x['developer']})", 'Project monitoring')


def r_kyc(o, B):
    S, A, F, mf, base, cur = ctx(B); ext = S['investors'][:3]; run = date(2026, 10, 12)
    lists = 'UNSC / OFAC / local' if A else 'UNSC / MHA-UAPA / SEBI debarred'
    fp = ext[2]['id']
    docs = (['checklist.pdf', 'screening_report.pdf', 'CRS_self_certification.pdf', 'FATCA_W8BENE_summary.pdf', 'BO_declaration.pdf'] if A else
            ['checklist.pdf', 'screening_report.pdf', 'CKYC_record.pdf', 'BO_declaration.pdf'])
    wb = openpyxl.Workbook()
    stat = lambda i: 'Refresh due' if i['refresh'] <= date(2026, 12, 31) else 'Complete'
    sheet(wb, 'KYC Register', [f"{S['name']} - KYC / AML register", 'Maintained by the AML Principal Officer'],
          ['Investor ID', 'Legal name', 'Risk rating', 'PEP flag', 'Beneficial ownership summary', 'Last screening date', 'Next refresh date', 'Status', 'Approved by', 'Approved at'],
          [[i['id'], i['name'], i['risk'], i['pep'], i['bo'], run, i['refresh'], stat(i), MANAGER['aml_po'], S['first_close'] - timedelta(days=6)] for i in S['investors']], {2: 44, 5: 60}, first=True)
    drows = []
    for i in ext:
        dl = docs + (['NetWorth_Certificate.pdf'] if i['id'] == 'LP-B3' else [])
        for dn in dl:
            drows.append([i['id'], dn.replace('.pdf', '').replace('_', ' '), f"KYC_Pack_{i['slug']}/{dn}", S['first_close'] - timedelta(days=12) if 'screening' not in dn else run,
                          i['refresh'] if 'screening' not in dn else None, MANAGER['aml_po']])
        if not A: drows.append([i['id'], 'FATCA CRS self certification', f"FATCA_CRS_SelfCert_{i['slug']}.pdf", S['first_close'] - timedelta(days=12), i['refresh'], MANAGER['aml_po']])
    sheet(wb, 'Documents', ['Document vault index'], ['Investor ID', 'Document type', 'File', 'Received date', 'Expiry / refresh date', 'Verified by'], drows, {2: 32, 3: 60})
    sheet(wb, 'Screening Log', ['Sanctions / PEP / adverse-media screening'], ['Investor ID', 'Run date', 'Lists', 'Hits', 'Disposition', 'Reviewer'],
          [[i['id'], run, lists, 1 if i['id'] == fp else 0, 'False positive - name similarity only; date of birth and nationality differ; closed' if i['id'] == fp else 'No hits', MANAGER['aml_po']]
           for i in S['investors']], {3: 30, 5: 70})
    sheet(wb, 'FATCA-CRS', ['FATCA / CRS classification'], ['Investor ID', 'FATCA status', 'CRS status', 'GIIN', 'TIN / PAN', 'Self-certification file', 'Reportable', 'Controlling persons'],
          [[i['id'], i['fatca'], i['crs'], i['giin'], i['tin'], (f"KYC_Pack_{i['slug']}/CRS_self_certification.pdf" if A else f"FATCA_CRS_SelfCert_{i['slug']}.pdf") if i in ext else 'manager file',
            'Yes' if (A and i['country'] != 'India (IFSC)') else 'No', i['bo']] for i in S['investors']], {2: 40, 3: 40, 6: 56, 8: 60})
    o.xlsx(f"{F}/KYC_Register_{S['short']}.xlsx", wb, ['kyc_file', 'kyc_document', 'screening_log', 'fatca_crs'], 'FME compliance (AML PO)', 'KYC / AML / FATCA')
    for i in ext:
        P = f"{F}/KYC_Pack_{i['slug']}"; feeds = ['kyc_document', 'evidence']; L = lh(S)
        base_kv = [('Investor', i['name']), ('Investor ID', i['id']), ('Country', i['country'])]
        o.pdf(f"{P}/checklist.pdf", doc('fme', MANAGER['name'], 'KYC / CDD checklist', 'CUSTOMER DUE DILIGENCE CHECKLIST',
              [kv(base_kv + [('Risk rating', i['risk']), ('PEP flag', i['pep']), ('Due diligence level', 'Enhanced (EDD)' if i['risk'] != 'Low' or 'Yes' in i['pep'] else 'Standard'),
                             ('Next refresh date', dmy(i['refresh']))]),
               table(['Item', 'Obtained', 'Verified by'], [[t, 'Yes', MANAGER['aml_po']] for t in (['Constitutional documents', 'Board resolution and authorised signatory list', 'Proof of address',
                     'Beneficial ownership declaration', 'Source of funds statement', 'Sanctions and PEP screening'] + (['CRS self-certification', 'FATCA form'] if A else ['PAN', 'CKYC record', 'FATCA/CRS self-certification']) +
                     (['Net-worth certificate (accredited/HNI basis)'] if i['id'] == 'LP-B3' else []) + (['Senior management approval for PEP-linked relationship'] if 'Yes' in i['pep'] else []))]),
               sign(MANAGER['aml_po'], 'AML Principal Officer', MANAGER['name'])]), feeds, 'FME compliance', 'KYC / AML / FATCA')
        o.pdf(f"{P}/screening_report.pdf", doc('vendor', 'Sentinel Screening Services', 'Sanctions, PEP and adverse-media screening report (synthetic)', 'SCREENING REPORT',
              [kv(base_kv + [('Run date', dmy(run)), ('Lists screened', lists), ('Parties screened', 'Entity, directors, authorised signatories, beneficial owners'),
                             ('Potential matches', 1 if i['id'] == fp else 0), ('True hits', 0),
                             ('Disposition', 'False positive - name similarity only; date of birth and nationality differ; closed' if i['id'] == fp else 'No hits'), ('Reviewer', MANAGER['aml_po'])])]),
              feeds + ['screening_log'], 'Screening vendor', 'KYC / AML / FATCA')
        o.pdf(f"{P}/BO_declaration.pdf", doc('vendor', i['name'], 'Declaration of beneficial ownership', 'BENEFICIAL OWNERSHIP DECLARATION',
              [kv(base_kv + [('Beneficial ownership', i['bo']), ('Declaration date', dmy(S['first_close'] - timedelta(days=14)))]), sign('Authorised signatory', 'For and on behalf of the investor', i['name'])]),
              feeds, 'Investor', 'KYC / AML / FATCA')
        if A:
            o.pdf(f"{P}/CRS_self_certification.pdf", doc('vendor', i['name'], 'Entity tax residency self-certification (CRS)', 'CRS SELF-CERTIFICATION - ENTITY',
                  [kv(base_kv + [('Jurisdiction of tax residence', i['country']), ('TIN', i['tin']), ('CRS status', i['crs']), ('Controlling persons', i['bo']),
                                 ('Certification date', dmy(S['first_close'] - timedelta(days=14)))])]), feeds + ['fatca_crs'], 'Investor', 'KYC / AML / FATCA')
            o.pdf(f"{P}/FATCA_W8BENE_summary.pdf", doc('fme', MANAGER['name'], 'Summary of Form W-8BEN-E held on file', 'FATCA - W-8BEN-E SUMMARY',
                  [kv(base_kv + [('Chapter 4 (FATCA) status', i['fatca']), ('GIIN', i['giin'] or 'Not applicable'), ('Form date', dmy(S['first_close'] - timedelta(days=14))),
                                 ('Valid until', '31-Dec-2028')])]), feeds + ['fatca_crs'], 'FME compliance', 'KYC / AML / FATCA')
        else:
            o.pdf(f"{P}/CKYC_record.pdf", doc('govt', 'CENTRAL KYC RECORDS REGISTRY - SPECIMEN', 'Legal entity KYC record download (synthetic)', 'CKYC RECORD',
                  [kv(base_kv + [('CKYC reference', i['ckyc']), ('PAN', i['tin']), ('Constitution', i['type']), ('Record status', 'Active'), ('Downloaded on', dmy(S['first_close'] - timedelta(days=12)))])]),
                  feeds, 'CKYC registry', 'KYC / AML / FATCA')
            o.pdf(f"{F}/FATCA_CRS_SelfCert_{i['slug']}.pdf", doc('vendor', i['name'], 'FATCA / CRS self-certification', 'FATCA / CRS SELF-CERTIFICATION',
                  [kv(base_kv + [('PAN', i['tin']), ('FATCA status', i['fatca']), ('CRS status', i['crs']), ('Reportable', 'No'), ('Certification date', dmy(S['first_close'] - timedelta(days=14)))])]),
                  feeds + ['fatca_crs'], 'Investor', 'KYC / AML / FATCA')
            if i['id'] == 'LP-B3':
                o.pdf(f"{P}/NetWorth_Certificate.pdf", doc('vendor', 'Bhatawdekar Sule & Co', 'Chartered Accountants · FRN 999999W', 'NET-WORTH CERTIFICATE',
                      [kv(base_kv + [('Certificate date', dmy(S['first_close'] - timedelta(days=20))), ('Net worth certified (INR cr)', '412.60'), ('Purpose', 'Eligibility for commitment to a Category II AIF')]),
                       sign('Ojas Bhatawdekar', 'Partner, M. No. 999999', 'Bhatawdekar Sule & Co')]), feeds, 'Chartered accountant', 'KYC / AML / FATCA')
    if A:
        o.pdf(f"{F}/FINGate_Registration_Evidence.pdf", doc('govt', 'FINANCIAL INTELLIGENCE UNIT - SPECIMEN', 'FINGate 2.0 reporting entity registration (synthetic)', 'REGISTRATION CONFIRMATION',
              [kv([('Reporting entity', MANAGER['name']), ('Category', 'Fund Management Entity (IFSC)'), ('FIU registration no', 'FIUREID/IFSC/9999999'), ('Principal Officer', MANAGER['aml_po']),
                   ('Designated Director', MANAGER['aml_dd']), ('Registration date', '18-Sep-2025'), ('Status', 'Active')])]), ['evidence'], 'FIU-IND portal', 'KYC / AML / FATCA')
        o.pdf(f"{F}/AML_Policy_Extract.pdf", doc('fme', MANAGER['name'], 'AML / CFT policy - extract approved by the board', 'AML / CFT POLICY - EXTRACT',
              [kv([('Policy version', '2.1'), ('Approved on', '12-Sep-2025'), ('Owner', MANAGER['aml_po'])]),
               table(['Risk rating', 'Refresh cycle', 'Due diligence'], [['High', '1 year', 'Enhanced, senior management approval'], ['Medium', '2 years (PEP-linked: annual)', 'Enhanced where PEP-linked'], ['Low', '3 years', 'Standard / simplified where permitted']]),
               p('Capital-call gate: no drawdown notice is issued to an investor whose KYC status is not Complete, unless a refresh is merely falling due after the call date.'),
               p('Suspicious transaction reports are raised by the Principal Officer and filed through FINGate within the prescribed time; tipping-off is prohibited.')]),
              ['evidence'], 'FME compliance', 'KYC / AML / FATCA')


def r_cal(o, B):
    S, A, F, mf, base, cur = ctx(B); d = S['dist']; vd = S['val_dates']
    ack = lambda name, title, pairs: (o.pdf(f"{F}/Evidence/{name}.pdf", doc('govt', 'FILING ACKNOWLEDGEMENT - SPECIMEN', 'System-generated acknowledgement (synthetic)', title, [kv(pairs)]),
                                            ['evidence'], 'Regulator portal / mailbox', 'Calendar'), f"Evidence/{name}.pdf")[1]
    sch = [('Scheme', S['name']), ('Filed by', MANAGER['co'])]
    if A:
        e1 = ack('IFSCA_Q2FY27_Submission_Ack', 'IFSCA QUARTERLY REPORT - SUBMISSION ACKNOWLEDGEMENT', sch + [('Period', 'Q2 FY27'), ('Submitted on', '20-Oct-2026'), ('Reference', 'IFSCA/QR/2026-27/Q2/9999')])
        e2 = ack('Valuation_Dispatch_Confirmation_30Sep26', 'VALUATION REPORT - DISPATCH TO INVESTORS', sch + [('Report received', dmy(vd['received'])), ('Dispatched on', dmy(vd['dispatched'])), ('Recipients', 4)])
        e3 = ack('Annual_Report_FY26_Filing_Ack', 'ANNUAL REPORT FY26 - FILING ACKNOWLEDGEMENT', sch + [('Filed on', '26-Sep-2026')])
        e4 = ack('Compliance_Report_FY26_Filing_Ack', 'COMPLIANCE REPORT FY26 WITH NET-WORTH CERTIFICATE - ACKNOWLEDGEMENT', sch + [('Filed on', '26-Sep-2026')])
        e5 = ack('Form61B_CY2025_Filing_Ack', 'FORM 61B (FATCA/CRS) CY2025 - ACKNOWLEDGEMENT', sch + [('Filed on', '28-May-2026')])
        e6 = ack('ICSI_Certification_Completion', 'ICSI CERTIFICATION - COMPLETION RECORD', [('Officer', MANAGER['co']), ('Completed on', '30-Sep-2026')])
        ob = [('IFSCA', 'IFSCA quarterly report', 'Q2 FY27', date(2026, 10, 21), 'Filed', date(2026, 10, 20), 'CO', 'IFSCA circular on reporting by FMEs', e1, 'verify'),
              ('IFSCA', 'Quarterly portfolio disclosure to investors', 'Q2 FY27', date(2026, 10, 31), 'Open', None, 'IR', 'PPM / FM Regulations', '', 'verify'),
              ('IFSCA', 'Half-yearly NAV disclosure (30-Sep)', 'H1 FY27', date(2026, 11, 14), 'Open', None, 'FIN_CHECKER', 'FM Regulations', '', 'verify'),
              ('IFSCA', 'Valuation report to investors within 15 days of receipt', '30-Sep-2026', vd['received'] + timedelta(days=15), 'Done', vd['dispatched'], 'IR', 'FM Regulations', e2, ''),
              ('RBI', 'FC-GPR I-A1 tranche 2', 'Allotment 05-Aug-2026', date(2026, 9, 4), 'Filed', date(2026, 8, 28), 'INV_TEAM', 'FEMA (Non-debt Instruments) reporting', 'FCGPR_Acknowledgement_I-A1_T2.pdf', ''),
              ('CBDT', 'WHT deposit DA-1', 'Sep-2026', d['deposit'], 'Filed', d['deposit'], 'FIN_MAKER', 'Income-tax Act', 'WHT_Deposit_Challan_DA1.pdf', ''),
              ('internal', 'Trustee related-party review pack', 'H1 FY27', date(2026, 11, 15), 'Open', None, 'CO', 'Trust deed', '', ''),
              ('IFSCA', 'Half-yearly AML/CFT sheet', 'H1 FY27', date(2026, 10, 31), 'Open', None, 'AML_PO', 'IFSCA AML/CFT/KYC Guidelines', '', 'verify'),
              ('internal', 'KYC refresh LP-A3', '2026', date(2026, 11, 20), 'Open', None, 'AML_PO', 'AML policy (PEP-linked: annual)', '', ''),
              ('IFSCA', 'FME website requirement', '2026', date(2026, 12, 1), 'Open', None, 'CO', 'IFSCA circular', '', 'verify'),
              ('IFSCA', 'Annual report FY26', 'FY26', date(2026, 9, 30), 'Filed', date(2026, 9, 26), 'CO', 'FM Regulations', e3, 'verify'),
              ('IFSCA', 'Compliance report FY26 with net-worth certificate', 'FY26', date(2026, 9, 30), 'Filed', date(2026, 9, 26), 'CO', 'FM Regulations', e4, 'verify'),
              ('CBDT', 'FATCA/CRS Form 61B', 'CY2025', date(2026, 5, 31), 'Filed', date(2026, 5, 28), 'CO', 'Rule 114G', e5, ''),
              ('internal', 'SEZ Annual Performance Report', 'FY26', date(2026, 11, 30), 'Open', None, 'CO', 'SEZ Rules', '', 'verify'),
              ('IFSCA', 'ICSI certification for compliance officer', '2026', date(2026, 9, 30), 'Done', date(2026, 9, 30), 'CO', 'IFSCA circular', e6, 'verify')]
    else:
        e1 = ack('SEBI_QAR_Q2FY27_Submission_Ack', 'SEBI QUARTERLY ACTIVITY REPORT - SUBMISSION ACKNOWLEDGEMENT', sch + [('Period', 'Q2 FY27'), ('Submitted on', '14-Oct-2026'), ('Reference', 'SI/AIF/QAR/2026-27/Q2/9998')])
        e2 = ack('Valuation_Dispatch_Confirmation_30Sep26', 'VALUATION DISCLOSURE - DISPATCH TO INVESTORS', sch + [('Report received', dmy(vd['received'])), ('Dispatched on', dmy(vd['dispatched'])), ('Recipients', 4)])
        e3 = ack('PPM_Audit_FY26_Filing_Ack', 'PPM AUDIT REPORT FY26 - FILING ACKNOWLEDGEMENT', sch + [('Filed on', '24-Sep-2026')])
        e4 = ack('Form64C_64D_FY26_Filing_Ack', 'FORM 64D / 64C FY26 - ACKNOWLEDGEMENT', sch + [('Form 64D filed on', '12-Jun-2026'), ('Form 64C issued on', '26-Jun-2026')])
        ob = [('SEBI', 'Quarterly activity report (SEBI intermediary portal)', 'Q2 FY27', date(2026, 10, 15), 'Filed', date(2026, 10, 14), 'CO', 'SEBI AIF reporting circular', e1, 'verify'),
              ('SEBI', 'NAV computation and upload to depositories', '30-Sep-2026', date(2026, 11, 14), 'Open', None, 'FIN_CHECKER', 'SEBI circular on dematerialisation / NAV', '', 'verify'),
              ('SEBI', 'Valuation disclosure to investors', '30-Sep-2026', vd['received'] + timedelta(days=15), 'Done', vd['dispatched'], 'IR', 'AIF Regulations / PPM', e2, 'verify'),
              ('SEBI', 'PPM audit report', 'FY26', date(2026, 9, 30), 'Filed', date(2026, 9, 24), 'CO', 'AIF Regulations', e3, 'verify'),
              ('SEBI', 'Compliance Test Report', 'FY26', date(2026, 4, 30), 'Filed', date(2026, 4, 28), 'CO', 'SEBI master circular for AIFs', 'CTR_FY26_extract.pdf', 'verify'),
              ('CBDT', 'Form 64D to the department / Form 64C to investors', 'FY26', date(2026, 6, 30), 'Filed', date(2026, 6, 26), 'FIN_CHECKER', 'Rule 12CB', e4, ''),
              ('CBDT', 'Form 64C to investors (draft in progress)', 'FY27', date(2027, 6, 30), 'Open', None, 'FIN_MAKER', 'Rule 12CB', '', ''),
              ('CBDT', 'TDS u/s 194LBB deposit DB-1', 'Sep-2026', d['deposit'], 'Filed', d['deposit'], 'FIN_MAKER', 'Income-tax Act', 'TDS_194LBB_Challan_DB1.pdf', ''),
              ('CBDT', 'Form 16A for DB-1', 'Q2 FY27', date(2026, 11, 15), 'Done', d['cert_date'], 'FIN_MAKER', 'Rule 31', f"Form16A_{S['investors'][0]['slug']}.pdf", ''),
              ('SEBI', 'Investor grievance / complaints status', 'Q2 FY27', date(2026, 10, 15), 'Filed', date(2026, 10, 14), 'CO', 'SCORES / quarterly report', e1, 'verify'),
              ('internal', 'Covenant breach notice to investors (SPV-B2)', '30-Sep-2026', date(2026, 10, 14), 'Open', None, 'IR', 'Side letter LP-B1: 10 business days from test date', '', 'verify'),
              ('internal', 'KYC refresh LP-B3', '2026', date(2026, 12, 15), 'Open', None, 'AML_PO', 'AML policy (medium risk: 2 years; accelerated)', '', '')]
    wb = openpyxl.Workbook()
    sheet(wb, 'Calendar', [f"{S['name']} - {S['regulator']} compliance calendar (Q2 FY27 and follow-through)", 'Rows flagged "verify" carry dates reconstructed from circulars and not yet verified against the current text'],
          ['Ref', 'Regulator', 'Obligation', 'Period', 'Due date', 'Status', 'Completed / filed date', 'Owner role', 'Basis', 'Evidence file', 'Verify'],
          [[f"{S['id']}-OB-{k:02d}", *r] for k, r in enumerate(ob, 1)], {3: 52, 9: 44, 10: 46}, first=True)
    o.xlsx(f"{F}/{S['regulator']}_Compliance_Calendar_{S['short']}.xlsx", wb, ['obligation', 'evidence'], 'FME compliance', 'Calendar / Exceptions')
    B.obligations = ob
    # Q1 FY27 report "as filed" (reconstructed layout)
    banner = 'LAYOUT RECONSTRUCTED FROM THE CIRCULAR - to be replaced with the regulator\'s current format workbook when obtained. Not an official format.'
    e = B.expected; ot = B.open_tb; inv_rows = []
    for x in S['instruments']:
        t1 = [t for t in x['tranches'] if t['date'] <= OPEN_DT]
        pr = sum(t['inr'] for t in t1) + (D('1.8241') if x['pik'] else 0)
        inv_rows.append([x['id'], x['spv_name'], x['kind_long'], x['city'], 'Residential real estate', pr, sum(t['fn'] for t in t1) + (D('1.8241') if x['pik'] else 0)])
    pairs = [('PART A - SCHEME PARTICULARS', None), ('Name of scheme', S['name']), ('Registration no', S['reg_no']), ('Category', S['category']), ('Manager', MANAGER['name']),
             ('Reporting period', 'Q1 FY27 (01-Apr-2026 to 30-Jun-2026)'), ('Reporting currency', S['unit']),
             ('PART B - CAPITAL', None), ('Target corpus', S['target']), ('Total commitments', S['committed']), ('Cumulative drawn', -ot[3100]), ('Undrawn commitments', S['committed'] + ot[3100]),
             ('Cumulative distributions', D('0.0000')), ('Number of investors', len(S['investors'])),
             ('PART C - ASSETS AND LIABILITIES', None), ('Cash and bank', ot[1100]), ('Investments at cost', ot[1200]), ('Fair-value adjustment', ot[1210])] + \
            ([('FX translation', ot[1220])] if A else []) + [('Liabilities', -(ot[2100] + ot[2200])), ('Net asset value', B.nav_open), ('Borrowings / leverage', D('0.0000')),
             ('PART D - FILING', None), ('Filed on', '20-Jul-2026' if A else '14-Jul-2026'), ('Filed by', MANAGER['co'])]
    wb = openpyxl.Workbook(); kvsheet(wb, 'Report', [f"{'IFSCA quarterly report' if A else 'SEBI quarterly activity report'} - Q1 FY27 - AS FILED", banner], pairs, first=True)
    sheet(wb, 'Investments', ['Portfolio at 30-Jun-2026', banner], ['Instrument', 'Investee', 'Type', 'City', 'Sector', 'Principal (INR cr)', f'Cost ({S["unit"]})'], inv_rows, {2: 40})
    sheet(wb, 'Investors', ['Investor profile at 30-Jun-2026', banner], ['Investor ID', 'Type', 'Country', 'Class', f'Commitment ({S["unit"]})', f'Drawn ({S["unit"]})'],
          [[i['id'], i['type'], i['country'], i['cls'], i['commit'], i['commit'] * sum(p_ for _, _, p_ in S['hist_calls'])] for i in S['investors']], {2: 44})
    nm = 'IFSCA_Quarterly_Report_Q1FY27_as_filed.xlsx' if A else 'SEBI_Quarterly_Activity_Report_Q1FY27_as_filed.xlsx'
    o.xlsx(f"{F}/{nm}", wb, ['report_run'], 'FME compliance (prior filing)', 'Report centre')
    if A:
        o.pdf(f"{F}/IFSCA_Q1FY27_Submission_Email.pdf", doc('vendor', 'Email - printed copy', 'From: compliance@rcm.example · To: reporting mailbox (regulator) · Sent: 20-Jul-2026 16:42 IST',
              'Subject: Quarterly report Q1 FY27 - Residential Credit Scheme I',
              [p('Dear Sir/Madam,'), p(f"Please find attached the quarterly report for the quarter ended 30 June 2026 for {S['name']} ({S['reg_no']}), submitted by {MANAGER['name']} ({MANAGER['ifsca']})."),
               kv([('Attachment', nm), ('Period', 'Q1 FY27'), ('Submitted on', '20-Jul-2026')]), p('Regards,'), p(f"{MANAGER['co']}, Compliance Officer")]), ['evidence'], 'FME compliance mailbox', 'Calendar')
    else:
        o.pdf(f"{F}/CTR_FY26_extract.pdf", doc('fme', MANAGER['name'], 'Compliance Test Report FY 2025-26 - extract submitted to the trustee and sponsor', 'COMPLIANCE TEST REPORT FY26 - EXTRACT',
              [kv([('Scheme', S['name']), ('Period', 'FY 2025-26'), ('Submitted on', '28-Apr-2026'), ('Prepared by', MANAGER['co'])]),
               table(['Area', 'Requirement tested', 'Result'], [['PPM', 'Investments within stated strategy', 'Complied'], ['Corpus', 'Minimum corpus maintained', 'Complied'],
                     ['Concentration', 'Single-investee limit', 'Complied'], ['Valuation', 'Half-yearly valuation by independent valuer', 'Complied'], ['Reporting', 'Quarterly reports filed', 'Complied']])]),
              ['evidence'], 'FME compliance', 'Calendar')


def r_inv(o, B):
    S, A, F, mf, base, cur = ctx(B); V = f"{F}/Vendor_Invoices_Q2FY27"
    fee, gst = S['fee_q'], S['fee_gst']
    for ql, dtt, st in (('Q1FY27', date(2026, 6, 30), f"Paid {dmy(S['fee_dates']['q1_paid'])}"), ('Q2FY27', date(2026, 9, 30), 'Unpaid at 30-Sep-2026 - accrued')):
        o.pdf(f"{F}/{'FME' if A else 'IM'}_Fee_Invoice_{ql}.pdf", doc('fme', MANAGER['name'], (MANAGER['addr_ifsc'] + ' · ' + MANAGER['ifsca']) if A else (MANAGER['addr_in'] + ' · GSTIN 27AAAFR9999Z1Z9'),
              'TAX INVOICE - MANAGEMENT FEE' if not A else 'INVOICE - MANAGEMENT FEE',
              [kv([('Invoice No', f"RCM/{S['id']}/FY27/{ql[:2]}"), ('Invoice date', dmy(dtt)), ('Bill to', f"{S['providers']['trustee']} A/c {S['name']}"), ('Period', f"{ql[:2]} FY27"),
                   ('Fee rate', f"{S['fee_rate'] * 100:.2f}% per annum"), (f'Fee base - capital commitments ({cur})', mf(base(S['committed']))), ('Computation', 'Fee base x rate x 1/4 (quarterly in arrears)'),
                   (f'Management fee ({cur})', mf(base(fee))), (f'GST ({cur})', mf(base(gst))), ('GST treatment', 'Supply by an IFSC unit to an IFSC scheme - no GST charged (treatment to be confirmed)' if A else 'CGST 9% + SGST 9%'),
                   (f'Invoice total ({cur})', mf(base(fee + gst))), ('Status', st)])]), ['journal'], 'FME / investment manager', 'Quarter close & NAV')
    for v in S['invoices']:
        nm = f"{v['role'].capitalize()}_{v['period'].replace(' ', '')}_{'AccrualNote' if v.get('note') else 'Invoice'}.pdf"
        o.pdf(f"{V}/{nm}", doc('trustee' if v['role'] == 'trustee' else 'vendor', v['vendor'] if not v.get('note') else S['name'],
              'Accrual note prepared by fund accounting (no invoice received)' if v.get('note') else 'Tax invoice', 'ACCRUAL NOTE' if v.get('note') else 'INVOICE',
              [kv([('Invoice No', v['no']), ('Invoice date', dmy(v['date'])), ('Vendor', v['vendor']), ('Service', v['role']), ('Bill to', f"{S['providers']['trustee']} A/c {S['name']}"),
                   ('Period', v['period']), (f'Invoice total ({cur})', mf(base(v['amt']))), ('Tax', 'Inclusive of GST where applicable' if not A else 'IFSC supply - no GST charged (treatment to be confirmed)'),
                   ('Status', f"Paid {dmy(v['paid'])}" if v['paid'] else 'Unpaid at 30-Sep-2026 - accrued')])]), ['journal'], 'Service provider' if not v.get('note') else 'Fund accounting', 'Quarter close & NAV')


def r_reg(o, B):
    S, A, F, mf, base, cur = ctx(B); c = S['call']; hist = sum(p_ for _, _, p_ in S['hist_calls'])
    wb = openpyxl.Workbook()
    sheet(wb, 'Investors', [f"{S['name']} - register of investors as at 30-Sep-2026"],
          ['Investor ID', 'Legal name', 'Type', 'Country', 'Tax residency', 'Treaty country', 'Unit class', f'Commitment ({cur})', 'Signed date', 'Admitted at close', 'Equalisation interest paid',
           f'{S["tax_name"]} rate', 'Accreditation basis', 'FME or sponsor', f'Called to date ({cur})', f'Unfunded ({cur})'],
          [[i['id'], i['name'], i['type'], i['country'], i['country'].replace(' (IFSC)', ''), i['country'] if A and i['cls'] == 'A' else 'n/a', i['cls'], base(i['commit']), S['first_close'] - timedelta(days=4), 1, D('0.00'),
            float(i['wht']), 'Institutional' if 'HNI' not in i['type'] else 'Net-worth certificate', 'Yes' if i['cls'] == 'B' else 'No', base(i['commit'] * (hist + c['pct'])), base(i['commit'] * (1 - hist - c['pct']))]
           for i in S['investors']], {2: 46, 3: 40}, first=True)
    sheet(wb, 'Classes', ['Unit classes'], ['Class', 'Description', 'Fee applies', 'Carry applies', 'Par value'],
          [['A', 'External investors', 'Yes', 'Yes', S['par']], ['B', 'FME contribution' if A else 'Sponsor commitment', 'No', 'No', S['par']]], {2: 30})
    sheet(wb, 'Closes', ['Closings'], ['Close', 'Date', 'Commitments admitted'], [[1, S['first_close'], base(S['committed'])]])
    sl = [[k, cl, v, m] for k, cl, v, m in S['side_letters']]
    if not A: sheet(wb, 'Side Letters', ['Side-letter terms'], ['Investor ID', 'Clause type', 'Value', 'MFN status'], sl, {3: 60})
    o.xlsx(f"{F}/Investor_Register_{S['short']}.xlsx", wb, ['investor', 'commitment', 'unit_class'] + ([] if A else ['side_letter_term']), 'Fund administrator / RTA', 'Investors & commitments')
    if A:
        wb = openpyxl.Workbook(); sheet(wb, 'Side Letters', [f"{S['name']} - side-letter summary"], ['Investor ID', 'Clause type', 'Value', 'MFN status'], sl, {3: 60}, first=True)
        o.xlsx(f"{F}/Side_Letter_Summary_{S['short']}.xlsx", wb, ['side_letter_term'], 'Fund counsel / IR', 'Investors & commitments')
    terms = [('Scheme', S['name']), ('Structure', f"{S['category']}; close-ended; trust"), ('Regulator', S['regulator']), ('Functional currency', cur), (f'Target corpus ({S["unit"]})', f2(S['target'])),
             (f'Total commitments ({S["unit"]})', f2(S['committed'])), ('First close', dmy(S['first_close'])), ('Investment period', '3 years from first close'), ('Term', '7 years + 1 + 1'),
             ('Management fee rate (% p.a.)', f2(S['fee_rate'] * 100)), ('Management fee basis', 'Capital commitments; charged to Class A units only; quarterly in arrears, payable within 10 days of quarter-end'),
             ('Hurdle rate (% p.a.)', f2(S['hurdle'] * 100)), ('Carried interest (%)', f2(S['carry'] * 100)), ('Distribution waterfall', 'European (whole-fund), 100% catch-up, clawback'),
             ('Late-payment interest (% p.a.)', f2(S['late_rate'] * 100)), ('Single-investee limit (% of investable funds)', f2(S['single_limit'] * 100)), ('Leverage limit', 'Nil at scheme level'),
             (f'Minimum corpus ({S["unit"]})', f2(S['min_corpus'])), (f'Unit par value ({cur})', f2(S['par'])), (f'{S["tax_name"]} on distributions (default %)', '10.00'), ('NAV frequency', 'Half-yearly (30-Sep, 31-Mar)'),
             ('Valuation', 'Each NAV date by an IBBI registered valuer'), ('Recycling', 'Permitted during the investment period'),
             ('Unit policy', 'Units issued at par on each contribution; income distributions do not change units; return-of-capital distributions redeem units at par'), ('PPM version', 'v1.2 dated 15-Sep-2025' if A else 'v1.1 dated 14-Aug-2025')]
    o.pdf(f"{F}/PPM_Term_Sheet_{S['short']}.pdf", doc('scheme', *lh(S), 'SUMMARY OF PRINCIPAL TERMS (extract of the Private Placement Memorandum)', [kv(terms)], 'Extract for operational use - the PPM prevails'),
          ['scheme', 'scheme_term'], 'FME / fund counsel', 'Investors & commitments')
    wb = openpyxl.Workbook(); run = {}; rows = []
    for u in sorted(B.units, key=lambda u: (u['date'], u['investor'])):
        run[u['investor']] = run.get(u['investor'], 0) + u['units']
        rows.append([u['date'], u['investor'], B.inv[u['investor']]['cls'], 'issue', u['units'], u['price'], D(u['units']) * u['price'], u['ref'], run[u['investor']]])
    pol = 'Policy: units are issued at par on each contribution; income distributions do not change units; return-of-capital distributions redeem units at par.'
    sheet(wb, 'Unit Ledger', [f"{S['name']} - unit register (par {cur} {S['par']})", pol], ['Event date', 'Investor ID', 'Class', 'Event type', 'Units', 'Price per unit', f'Amount ({cur})', 'Reference', 'Cumulative units'], rows, first=True)
    sheet(wb, 'Holdings', ['Unit holdings', pol], ['Investor ID', 'Class', 'Units at 30-Jun-2026', 'Units at 30-Sep-2026'],
          [[k, v['cls'], v['units_open'], v['units']] for k, v in B.ca.items()], total=['Total', '', sum(v['units_open'] for v in B.ca.values()), sum(v['units'] for v in B.ca.values())])
    o.xlsx(f"{F}/Unit_Register_{S['short']}.xlsx", wb, ['unit_ledger'], 'Fund administrator / RTA', 'Capital accounts')


def r_shared(o, BA, BB, fx):
    s = io.StringIO(); w = csv.writer(s, lineterminator='\n'); w.writerow(['Date', 'Currency Pair', 'Reference Rate', 'Source'])
    for d in sorted(fx): w.writerow([dmy(d), 'USD/INR', f"{fx[d]:.4f}", 'FBIL reference rate (synthetic)'])
    o.text('scheme_A_gift/FX_Rates_USDINR_Daily_Jul-Sep26.csv', s.getvalue(), ['fx_rate'], 'Rate feed (FBIL-style)', 'FX & translation')
    wb = openpyxl.Workbook(); first = True
    for B in (BA, BB):
        S = B.S; A = S['id'] == 'A'
        kvsheet(wb, f"{S['id']} Meta", [f"{S['name']} - opening balances as at 30-Jun-2026", 'AUDITED / LOCKED - loaded as the locked opening position'],
                [('Scheme', S['name']), ('As at', OPEN_DT), ('Unit', S['unit']), ('Status', 'Locked'), ('Closing rate USD/INR at 30-Jun-2026', D('89.00') if A else 'n/a'), ('Net asset value', B.nav_open),
                 ('Units in issue', sum(v['units_open'] for v in B.ca.values()))], first=first); first = False
        sheet(wb, f"{S['id']} TB", [f"Opening trial balance ({S['unit']}; debit positive)"], ['GL code', 'Account', 'Type', 'Balance'], [[g, GL[g][0], GL[g][1], a] for g, a in sorted(B.open_tb.items())], {2: 40})
        irows = []
        for x in S['instruments']:
            hj = B.j[:B.n_hist]
            cost = sum(l['amt'] for j in hj for l in j['lines'] if l['gl'] == 1200 and l.get('instrument') == x['id'])
            adj = sum(l['amt'] for j in hj for l in j['lines'] if l['gl'] == 1210 and l.get('instrument') == x['id'])
            pr = sum(t['inr'] for t in x['tranches'] if t['date'] <= OPEN_DT) + sum(a['interest_pik'] for a in B.accr if a['instrument'] == x['id'] and a['end'] <= OPEN_DT)
            irows.append([x['id'], x['isin'], pr, cost, adj, x['val']['adj_open'], B.custody[x['isin']]['open']])
        sheet(wb, f"{S['id']} Instruments", ['Instrument positions at 30-Jun-2026'], ['Instrument ID', 'ISIN', 'Principal (INR cr)', f'Cost ({S["unit"]})', f'FV adjustment ({S["unit"]})', 'FV adjustment (INR cr)', 'Quantity'], irows)
        sheet(wb, f"{S['id']} Capital", ['Capital accounts at 30-Jun-2026'], ['Investor ID', 'Class', 'Units', f'Opening capital ({S["unit"]})'], [[k, v['cls'], v['units_open'], v['opening']] for k, v in B.ca.items()])
        calls = [[f"C{'G' if A else 'B'}-{n}", d, S['committed'] * p_] for n, d, p_ in S['hist_calls']]
        sheet(wb, f"{S['id']} Calls", ['Prior capital calls (due dates) for performance measurement'], ['Call', 'Due date', f'Amount ({S["unit"]})'], calls)
    o.xlsx('shared/Opening_Balances_30Jun26_locked.xlsx', wb, ['period', 'journal', 'journal_line', 'capital_account'], 'Fund administrator (audited prior period)', 'Ledger & TB')

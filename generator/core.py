"""Core model: masters, event script (brief Section 6), books, golden totals.
Money is Decimal in the scheme's reporting unit (USD m for A, INR cr for B)."""
from decimal import Decimal as D, ROUND_HALF_UP
from datetime import date, timedelta
import random, uuid

MEMO = D('89.40')
Q_START, Q_END, OPEN_DT = date(2026, 7, 1), date(2026, 9, 30), date(2026, 6, 30)
MAKER, CHECKER = 'Pallav Bhowmick', 'Renuka Thirumalai'


def q(x, p=4):
    return D(x).quantize(D(1).scaleb(-p), ROUND_HALF_UP)


def dmy(d):
    return d.strftime('%d-%b-%Y')


def prorate(total, weights, p=6):
    tw = sum(weights.values())
    out = {k: q(total * w / tw, p) for k, w in weights.items()}
    k = max(weights, key=lambda z: (weights[z], z))
    out[k] += q(total, p) - sum(out.values())
    return out


def xirr(flows):
    t0 = min(d for d, _ in flows)
    f = lambda r: sum(float(a) / (1 + r) ** ((d - t0).days / 365.0) for d, a in flows)
    lo, hi = -0.99, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0: hi = mid
        else: lo = mid
    return round((lo + hi) / 2, 6)


def waterfall(distributable, calls, dists, as_of, hurdle, carry, catchup=D(1)):
    """European whole-fund waterfall on a hypothetical liquidation at `distributable`."""
    h = float(hurdle)
    grow = lambda d, a: float(a) * (1 + h) ** ((as_of - d).days / 365.0)
    paid = sum(a for _, a in calls)
    pref_bal = D(str(round(sum(grow(d, a) for d, a in calls) - sum(grow(d, a) for d, a in dists), 6)))
    hurdle_amt = max(pref_bal - (paid - sum(a for _, a in dists)), D(0))
    roc_due = paid - sum(a for _, a in dists)
    rem = D(distributable)
    t1 = min(rem, max(roc_due, D(0))); rem -= t1
    t2 = min(rem, hurdle_amt); rem -= t2
    cu_full = hurdle_amt * carry / (1 - carry) if catchup == 1 else D(0)
    t3 = min(rem, q(cu_full, 6)); rem -= t3
    gp = q(rem * carry, 6)
    return dict(return_of_capital=q(t1, 6), hurdle=q(t2, 6), catch_up=q(t3, 6), split_lp=q(rem - gp, 6),
                split_gp=gp, carry=q(t3 + gp, 6), lp_total=q(t1 + t2 + rem - gp, 6))


GL = {1100: ('Cash at bank', 'asset'), 1200: ('Investments at cost', 'asset'), 1210: ('Fair-value adjustment', 'asset'),
      1220: ('FX translation on INR assets', 'asset'), 1300: ('Accrued interest receivable', 'asset'),
      1400: ('Capital call receivable', 'asset'), 2100: ('Management fee payable', 'liability'),
      2200: ('Accrued expenses', 'liability'), 2300: ('Distribution payable', 'liability'),
      2500: ('Withholding tax payable', 'liability'), 3100: ('Contributed capital', 'equity'),
      3200: ('Distributions to investors', 'equity'), 3900: ('Accumulated result', 'equity'),
      4100: ('Interest income - cash coupon', 'income'), 4110: ('Interest income - PIK', 'income'),
      4200: ('Bank deposit interest', 'income'), 4500: ('Late-payment interest', 'income'),
      4600: ('Unrealised fair-value gain/(loss)', 'income'), 4700: ('FX translation gain/(loss)', 'income'),
      5100: ('Management fee', 'expense'), 5200: ('Fund expenses', 'expense'), 5210: ('Valuation fees', 'expense'),
      5300: ('Bank charges', 'expense'), 5900: ('Organisation expenses', 'expense')}
CAT = {4100: 'income', 4110: 'income', 4200: 'income', 4500: 'income', 4600: 'fv', 4700: 'fx',
       5100: 'fee', 5200: 'expense', 5210: 'expense', 5300: 'expense', 5900: 'expense'}

MANAGER = dict(name='Residential Capital Managers', ifsca='IFSCA/FME/III/2025-26/9999', sebi='IN/AIF2/25-26/9999',
               po='Ishaan Wadekar', co='Meenal Kothandaraman', aml_po='Farhan Qureshi-Menon',
               aml_dd='Sharvari Deodhar', ir='Devika Sabnis', cro='Jaideep Almeida-Rao',
               addr_ifsc='Unit 1499, Tower Z, Block 99, GIFT SEZ, Gandhinagar 382355',
               addr_in='Level 99, Fictional Towers, Lower Parel, Mumbai 400013')


def scheme_A():
    return dict(
        id='A', folder='scheme_A_gift', name='Residential Credit Scheme I', short='SchemeA', regulator='IFSCA',
        category='Restricted Scheme (Non-Retail), Category II-type', domicile='GIFT IFSC', ccy='USD', unit='USD m',
        scale=D(1000000), reg_no='IFSCA/AIF/RS/2025-26/9999', par=D(100), target=D(150), committed=D(120),
        first_close=date(2025, 10, 1), fee_rate=D('0.0175'), hurdle=D('0.10'), carry=D('0.20'), late_rate=D('0.10'),
        single_limit=D('0.25'), min_corpus=D(3), tax_name='WHT', tax_section='As per PPM cl. 14 (default 10%)',
        bank=dict(name='First Gulf-India Bank', branch='IFSC Banking Unit, GIFT City', swift='FGIBINGGXXX',
                  acct='9990012600017', ifsc='', ledger='First Gulf-India Bank IBU - USD A/c'),
        dp=dict(name='Giftline Custody Services IFSC Ltd', dp_id='IN309999', client='10009999',
                depository='NSDL (IFSC DP)'),
        providers=dict(trustee='Sabarmati Trusteeship Services Pvt Ltd', administrator='Northlight Fund Services (IFSC) Pvt Ltd',
                       custodian='Giftline Custody Services IFSC Ltd', valuer='Meridian Valuation Advisors LLP',
                       valuer_reg='IBBI/RV-E/99/2025/999', auditor='Tripathi Menon & Associates LLP',
                       legal='Lexwell Partners LLP', bank='First Gulf-India Bank, IBU GIFT City'),
        investors=[
            dict(id='LP-A1', name='Sakura Residential Holdings K.K.', slug='Sakura_Residential_Holdings', type='Listed real-estate developer (anchor)',
                 country='Japan', cls='A', commit=D(60), wht=D('0.10'), bank='Bank of Musashino, Tokyo', swift='MUSAJPJTXXX',
                 risk='Low', pep='No', refresh=date(2028, 10, 1), tin='JP-9990-01-999991', giin='', fatca='Active NFFE', crs='Active NFE - listed',
                 bo='Listed on a recognised exchange; no natural-person BO above 10%'),
            dict(id='LP-A2', name='Nishi-Tokyo Trust Bank, Ltd.', slug='Nishi-Tokyo_Trust_Bank', type='Trust bank', country='Japan', cls='A',
                 commit=D(36), wht=D('0.10'), bank='Nishi-Tokyo Trust Bank, Tokyo', swift='NTTBJPJTXXX', risk='Low', pep='No',
                 refresh=date(2028, 10, 1), tin='JP-9990-01-999992', giin='99ZZ9A.99999.ME.392', fatca='Reporting Model 2 FFI',
                 crs='Financial Institution - Depository', bo='Regulated financial institution; SDD applied'),
            dict(id='LP-A3', name='Al Nahda Sovereign Holdings LLC', slug='Al_Nahda_Sovereign_Holdings', type='State-linked institution (PEP-linked, EDD)',
                 country='UAE', cls='A', commit=D(18), wht=D('0.10'), bank='Emirates Crescent Bank, Abu Dhabi', swift='ECRBAEADXXX',
                 risk='Medium', pep='Yes - PEP-linked (state entity)', refresh=date(2026, 11, 20), tin='AE-999000999900003', giin='',
                 fatca='Exempt beneficial owner (foreign government entity)', crs='Governmental Entity', bo='Wholly owned by a state holding authority; two board members are PEPs'),
            dict(id='LP-A4', name='Residential Capital Managers (FME contribution)', slug='FME_Contribution', type='FME', country='India (IFSC)',
                 cls='B', commit=D(6), wht=D('0.10'), bank='First Gulf-India Bank, IBU GIFT City', swift='FGIBINGGXXX', risk='Low', pep='No',
                 refresh=date(2027, 10, 1), tin='IN-AAAFR9999Z', giin='', fatca='Active NFFE', crs='Active NFE', bo='FME - see FME KYC file'),
        ],
        side_letters=[('LP-A1', 'reporting', 'Quarterly ESG/EDGE page; quarterly report within 30 days', 'n/a'),
                      ('LP-A1', 'excuse', 'None', 'not triggered'),
                      ('LP-A2', 'reporting', 'INR and USD views in every report', 'offered to all'),
                      ('LP-A2', 'sub-processor', 'Prior notice of any change of data sub-processor', 'n/a'),
                      ('LP-A3', 'excuse', 'Exclusion list (alcohol, gaming) - excuse right', 'not triggered'),
                      ('LP-A3', 'reporting', 'Enhanced sanctions reporting (quarterly attestation)', 'n/a')],
        instruments=[
            dict(id='I-A1', spv='SPV-A1', spv_name='Kalpavriksha Homes Thane Pvt Ltd', developer='Kalpavriksha Realty', city='Mumbai MMR',
                 micro='Thane', kind='NCD', kind_long='Secured NCD', fv=100000, isin='INE0A1A07019', cash=D('0.14'), pik=D(0), tenor=48,
                 security='First-ranking mortgage on project land, charge on receivables, RERA escrow', chg='CHG-9/SRN ZZ99990001',
                 rera='P51700099999', homes=1200, escrow='Deccan Union Bank Ltd',
                 tranches=[dict(no=1, date=date(2026, 1, 15), inr=D(200), rate=D('88.10'), units=20000),
                           dict(no=2, date=date(2026, 8, 5), inr=D(100), rate=D('89.15'), units=10000)],
                 val=dict(adj_open=D('2.2'), adj=D('3.0'), method='DCF of contractual cash flows at market yield', level=3,
                          y='13.40%', y_prior='13.55%', note='Yield tightened 15 bp on sales momentum'),
                 mis=dict(layout=1, cum=310, sold=[22, 25, 27], price=D('0.85'), coll=[D('21.5'), D('24.0'), D('26.5')], cons=[38, 41, 44],
                          escrow=[D('14.2'), D('15.8'), D('17.1')], cost_total=D(780), cost=[D(296), D(310), D(325)]),
                 cov=dict(vel_min=45, cover_min=D('1.25'), ds=D(36))),
            dict(id='I-A2', spv='SPV-A2', spv_name='Hinjewadi Greenfield Developers Pvt Ltd', developer='Greenfield Estates', city='Pune',
                 micro='Hinjewadi', kind='CCD', kind_long='Compulsorily convertible debenture', fv=10000, isin='INE0A2A08017', cash=D(0), pik=D(0),
                 tenor=60, security='Unsecured; shareholder rights and project-profit participation', chg='n/a (unsecured CCD)',
                 rera='P52100099998', homes=900, escrow='Deccan Union Bank Ltd',
                 tranches=[dict(no=1, date=date(2026, 3, 10), inr=D(60), rate=D('88.50'), units=60000)],
                 val=dict(adj_open=D(0), adj=D('6.0'), method='Project DCF (residual profit share)', level=3, y='18.00%', y_prior='18.00%',
                          note='First uplift: launch phase sold ahead of plan'),
                 mis=dict(layout=2, cum=140, sold=[15, 17, 19], price=D('0.62'), coll=[D('9.2'), D('10.1'), D('11.3')], cons=[24, 27, 30],
                          escrow=[D('6.4'), D('7.0'), D('7.9')], cost_total=D(520), cost=[D(125), D(140), D(156)]),
                 cov=dict(vel_min=30, cover_min=D('1.25'), ds=D(18))),
        ],
        fee_q=D('0.525'), fee_gst=D(0), booked={('I-A1', 'Q1FY27'): D('0.7843')},  # brief s.6.1 states 0.7843 (6.9808 cr @ 89.00 rounds to 0.7844)
        invoices=[
            dict(no='STS/IFSC/26-27/0114', role='trustee', vendor='Sabarmati Trusteeship Services Pvt Ltd', period='Q1 FY27', date=date(2026, 6, 30), amt=D('0.030'), paid=date(2026, 7, 10), led='Trusteeship Fees', gl=5200),
            dict(no='NFS/IFSC/26-27/0087', role='administrator', vendor='Northlight Fund Services (IFSC) Pvt Ltd', period='Q1 FY27', date=date(2026, 6, 30), amt=D('0.020'), paid=date(2026, 7, 10), led='Fund Administration Fees', gl=5200),
            dict(no='LWP/26-27/0311', role='legal', vendor='Lexwell Partners LLP', period='Q1 FY27', date=date(2026, 6, 28), amt=D('0.010'), paid=date(2026, 7, 10), led='Legal & Professional Fees', gl=5200),
            dict(no='STS/IFSC/26-27/0171', role='trustee', vendor='Sabarmati Trusteeship Services Pvt Ltd', period='Q2 FY27', date=date(2026, 9, 30), amt=D('0.030'), paid=None, led='Trusteeship Fees', gl=5200),
            dict(no='NFS/IFSC/26-27/0139', role='administrator', vendor='Northlight Fund Services (IFSC) Pvt Ltd', period='Q2 FY27', date=date(2026, 9, 30), amt=D('0.020'), paid=None, led='Fund Administration Fees', gl=5200),
            dict(no='ACCRUAL/AUD/FY27/H1', role='audit', vendor='Tripathi Menon & Associates LLP', period='Q2 FY27', date=date(2026, 9, 30), amt=D('0.015'), paid=None, led='Audit Fees', gl=5200, note=True),
            dict(no='MVA/26-27/0452', role='valuer', vendor='Meridian Valuation Advisors LLP', period='Q2 FY27', date=date(2026, 9, 30), amt=D('0.040'), paid=None, led='Valuation Fees', gl=5210),
        ],
        call=dict(code='CG3', label='CG-3', no=3, notice=date(2026, 7, 15), due=date(2026, 7, 30), pct=D('0.15'),
                  purpose='I-A1 tranche 2 and expenses', receipts={'LP-A1': date(2026, 7, 30), 'LP-A2': date(2026, 7, 30),
                                                                   'LP-A4': date(2026, 7, 30), 'LP-A3': date(2026, 8, 4)},
                  inv_part=D('11.2170') / D(18), lpi_date=date(2026, 8, 12)),
        dist=dict(code='DA1', label='DA-1', no=1, decl=date(2026, 9, 10), pay=date(2026, 9, 15), gross=D('1.200'),
                  source='Coupons received on I-A1 (Q4 FY26 and Q1 FY27)', deposit=date(2026, 10, 7), challan='WHT/IFSC/2026-27/000999',
                  cert_date=date(2026, 10, 15)),
        hist_calls=[(1, date(2025, 10, 10), D('0.20')), (2, date(2026, 1, 5), D('0.20'))],
        val_dates=dict(report=date(2026, 10, 15), received=date(2026, 10, 20), dispatched=date(2026, 10, 29)),
        fee_dates=dict(q1_paid=date(2026, 7, 7)), bank_int=D('0.012'), bank_chg=D('0.004'),
    )


def scheme_B():
    return dict(
        id='B', folder='scheme_B_onshore', name='Residential Growth Fund II', short='SchemeB', regulator='SEBI',
        category='Category II Alternative Investment Fund', domicile='India', ccy='INR', unit='INR cr', scale=D(10000000),
        reg_no='IN/AIF2/25-26/9998', par=D(100), target=D(600), committed=D(500), first_close=date(2025, 9, 1),
        fee_rate=D('0.02'), hurdle=D('0.12'), carry=D('0.20'), late_rate=D('0.12'), single_limit=D('0.25'), min_corpus=D(20),
        tax_name='TDS', tax_section='194LBB',
        bank=dict(name='Deccan Union Bank Ltd', branch='Corporate Banking Branch, Nariman Point, Mumbai', swift='', acct='999902600025',
                  ifsc='DUBL0009999', ledger='Deccan Union Bank - Current A/c'),
        dp=dict(name='Deccan Securities DP Ltd', dp_id='IN309998', client='20009998', depository='NSDL'),
        providers=dict(trustee='Sabarmati Trusteeship Services Pvt Ltd', administrator='Cauvery Registry Services Pvt Ltd (RTA)',
                       custodian='Deccan Custodial Services Ltd', valuer='Meridian Valuation Advisors LLP', valuer_reg='IBBI/RV-E/99/2025/999',
                       auditor='Tripathi Menon & Associates LLP', legal='Lexwell Partners LLP', bank='Deccan Union Bank Ltd'),
        investors=[
            dict(id='LP-B1', name='Vindhya Life Insurance Co. Ltd', slug='Vindhya_Life_Insurance', type='Insurance company', country='India', cls='A',
                 commit=D(250), wht=D('0.10'), bank='Deccan Union Bank Ltd', swift='DUBL0000101', risk='Low', pep='No', refresh=date(2028, 9, 1),
                 tin='AAACV9999Z', giin='', fatca='Not a US person; Indian FI', crs='Financial Institution - non-reportable', bo='IRDAI-regulated; listed parent',
                 ckyc='CKYC-LE-99990000000001'),
            dict(id='LP-B2', name='Sahyadri Cooperative Bank', slug='Sahyadri_Cooperative_Bank', type='Co-operative bank', country='India', cls='A',
                 commit=D(150), wht=D('0.10'), bank='Sahyadri Cooperative Bank', swift='SAHC0000001', risk='Low', pep='No', refresh=date(2028, 9, 1),
                 tin='AAAAS9998Y', giin='', fatca='Not a US person; Indian FI', crs='Financial Institution - non-reportable', bo='RBI-regulated co-operative bank',
                 ckyc='CKYC-LE-99990000000002'),
            dict(id='LP-B3', name='Rao Family Office', slug='Rao_Family_Office', type='HNI family office (net-worth certificate)', country='India', cls='A',
                 commit=D(75), wht=D('0.10'), bank='Deccan Union Bank Ltd', swift='DUBL0000455', risk='Medium', pep='No', refresh=date(2026, 12, 15),
                 tin='AAATR9997X', giin='', fatca='Not a US person', crs='Passive NFE - controlling persons resident in India', bo='Two family members hold 60% / 40%',
                 ckyc='CKYC-LE-99990000000003'),
            dict(id='LP-B4', name='Residential Capital Managers (Sponsor commitment)', slug='Sponsor_Commitment', type='Sponsor', country='India', cls='B',
                 commit=D(25), wht=D('0.10'), bank='Deccan Union Bank Ltd', swift='DUBL0009999', risk='Low', pep='No', refresh=date(2027, 9, 1),
                 tin='AAAFR9999Z', giin='', fatca='Not a US person', crs='Active NFE', bo='Sponsor - see manager KYC file', ckyc='CKYC-LE-99990000000004'),
        ],
        side_letters=[('LP-B1', 'breach_notice_days', '10 business days from covenant test date', 'offered to all'),
                      ('LP-B1', 'reporting', 'IRDAI investment-return format, half-yearly', 'n/a'),
                      ('LP-B2', 'reporting', 'RBI exposure statement, quarterly', 'n/a'),
                      ('LP-B3', 'excuse', 'None', 'not triggered')],
        instruments=[
            dict(id='I-B1', spv='SPV-B1', spv_name='Whitefield Urban Homes Pvt Ltd', developer='Urban Homes Group', city='Bengaluru', micro='Whitefield',
                 kind='NCD', kind_long='Secured NCD', fv=100000, isin='INE0B1B07015', cash=D('0.135'), pik=D(0), tenor=48,
                 security='First-ranking mortgage on project land, charge on receivables, RERA escrow', chg='CHG-9/SRN ZZ99990002',
                 rera='PRM/KA/RERA/9999/001', homes=800, escrow='Deccan Union Bank Ltd',
                 tranches=[dict(no=1, date=date(2025, 11, 20), inr=D(120), rate=D(1), units=12000),
                           dict(no=2, date=date(2026, 9, 8), inr=D(30), rate=D(1), units=3000)],
                 val=dict(adj_open=D('1.0'), adj=D('1.5'), method='DCF of contractual cash flows at market yield', level=3, y='13.10%', y_prior='13.20%',
                          note='Performing; yield tightened 10 bp'),
                 mis=dict(layout=1, cum=260, sold=[16, 18, 21], price=D('1.10'), coll=[D('19.0'), D('20.5'), D('23.0')], cons=[46, 49, 52],
                          escrow=[D('11.6'), D('12.4'), D('13.9')], cost_total=D(640), cost=[D(294), D(313), D(333)]),
                 cov=dict(vel_min=40, cover_min=D('1.25'), ds=D(30))),
            dict(id='I-B2', spv='SPV-B2', spv_name='Kokapet Skyline Projects Pvt Ltd', developer='Skyline Projects', city='Hyderabad', micro='Kokapet',
                 kind='NCD', kind_long='Secured NCD (cash + PIK)', fv=100000, isin='INE0B2B07013', cash=D('0.10'), pik=D('0.06'), tenor=54,
                 security='First-ranking mortgage on project land, charge on receivables, RERA escrow', chg='CHG-9/SRN ZZ99990003',
                 rera='P02400099997', homes=650, escrow='Deccan Union Bank Ltd',
                 tranches=[dict(no=1, date=date(2026, 2, 12), inr=D(80), rate=D(1), units=8000)],
                 val=dict(adj_open=D(0), adj=D(0), method='DCF of contractual cash flows at market yield', level=3, y='16.00%', y_prior='16.00%',
                          note='WATCH: sales-velocity and collection-cover covenants breached at 30-Sep-2026; carried at principal pending cure plan; impairment review next cycle'),
                 mis=dict(layout=2, cum=95, sold=[7, 6, 5], price=D('1.45'), coll=[D('6.4'), D('6.1'), D('5.5')], cons=[31, 32, D('32.5')],
                          escrow=[D('3.1'), D('2.6'), D('2.0')], cost_total=D(710), cost=[D(220), D(227), D(231)]),
                 cov=dict(vel_min=40, cover_min=D('1.25'), ds=D(20))),
        ],
        fee_q=D('2.50'), fee_gst=D('0.45'),
        invoices=[
            dict(no='STS/26-27/0209', role='trustee', vendor='Sabarmati Trusteeship Services Pvt Ltd', period='Q1 FY27', date=date(2026, 6, 30), amt=D('0.12'), paid=date(2026, 7, 10), led='Trusteeship Fees', gl=5200),
            dict(no='CRS/26-27/0933', role='rta', vendor='Cauvery Registry Services Pvt Ltd', period='Q1 FY27', date=date(2026, 6, 30), amt=D('0.10'), paid=date(2026, 7, 10), led='RTA Fees', gl=5200),
            dict(no='LWP/26-27/0312', role='legal', vendor='Lexwell Partners LLP', period='Q1 FY27', date=date(2026, 6, 28), amt=D('0.20'), paid=date(2026, 7, 10), led='Legal & Professional Fees', gl=5200),
            dict(no='STS/26-27/0298', role='trustee', vendor='Sabarmati Trusteeship Services Pvt Ltd', period='Q2 FY27', date=date(2026, 9, 30), amt=D('0.12'), paid=None, led='Trusteeship Fees', gl=5200),
            dict(no='CRS/26-27/1377', role='rta', vendor='Cauvery Registry Services Pvt Ltd', period='Q2 FY27', date=date(2026, 9, 30), amt=D('0.10'), paid=None, led='RTA Fees', gl=5200),
            dict(no='ACCRUAL/AUD/FY27/H1-B', role='audit', vendor='Tripathi Menon & Associates LLP', period='Q2 FY27', date=date(2026, 9, 30), amt=D('0.16'), paid=None, led='Audit Fees', gl=5200, note=True),
            dict(no='MVA/26-27/0453', role='valuer', vendor='Meridian Valuation Advisors LLP', period='Q2 FY27', date=date(2026, 9, 30), amt=D('0.30'), paid=None, led='Valuation Fees', gl=5210),
        ],
        call=dict(code='CB3', label='CB-3', no=3, notice=date(2026, 8, 20), due=date(2026, 9, 3), pct=D('0.10'),
                  purpose='I-B1 tranche 2, fees and expenses', receipts={k: date(2026, 9, 3) for k in ('LP-B1', 'LP-B2', 'LP-B3', 'LP-B4')},
                  inv_part=D(30) / D(50), lpi_date=None),
        dist=dict(code='DB1', label='DB-1', no=1, decl=date(2026, 9, 20), pay=date(2026, 9, 25), gross=D('10.00'),
                  source='Coupons received on I-B1 and I-B2', deposit=date(2026, 10, 7), challan='ITNS281/DUBL/071026/99999',
                  cert_date=date(2026, 10, 15)),
        hist_calls=[(1, date(2025, 9, 15), D('0.20')), (2, date(2025, 11, 10), D('0.30'))],
        val_dates=dict(report=date(2026, 10, 14), received=date(2026, 10, 19), dispatched=date(2026, 10, 28)),
        fee_dates=dict(q1_paid=date(2026, 7, 5)), bank_int=D('0.06'), bank_chg=D('0.01'),
    )


class Books:
    def __init__(s, S, seed):
        s.S, s.seed = S, seed
        s.j, s.bank, s.tv, s.units, s.cust, s.accr = [], [], [], [], [], []
        s.inv = {i['id']: i for i in S['investors']}
        s.w = {i['id']: i['commit'] for i in S['investors']}
        s.bseq = 0

    def led(s, gl, m):
        S = s.S
        if m.get('led'): return m['led']
        if gl == 1100: return S['bank']['ledger']
        ins = m.get('instrument')
        if gl == 1200: return f"Investment in {next(i['kind'] for i in S['instruments'] if i['id'] == ins)} - {ins}"
        if gl == 4100: return f"Interest on NCD - {ins}"
        if gl == 4110: return f"PIK Interest on NCD - {ins}"
        if gl == 3100: return f"Unit Capital - {m['investor']}"
        return {1210: 'Fair Value Adjustment on Investments', 1300: 'Interest Accrued on Investments', 1400: 'Call Money Receivable',
                2100: 'Management Fee Payable', 2200: 'Expenses Payable', 2300: 'Distribution Payable',
                2500: 'WHT Payable on Distributions' if S['id'] == 'A' else 'TDS Payable - 194LBB', 3200: 'Distribution to Unitholders',
                4200: 'Interest on Bank Deposits', 4500: 'Late Payment Interest from Contributors', 4600: 'Unrealised Gain on Fair Valuation',
                5100: 'Management Fees', 5210: 'Valuation Fees', 5300: 'Bank Charges', 5900: 'Organisation Expenses'}[gl]

    def post(s, dt, desc, kind, ref, lines, tally='mirror', narr=None):
        """lines: (gl, amount [+Dr / -Cr], meta). tally: 'mirror' | None | [(ledger, amount)]"""
        lines = [(g, D(a), m) for g, a, m in lines]
        assert sum(a for _, a, _ in lines) == 0, (desc, lines)
        jid = len(s.j) + 1
        s.j.append(dict(id=jid, jv_no=f"{s.S['id']}-JV-{jid:04d}", date=dt, desc=desc, kind=kind, ref=ref,
                        lines=[dict(gl=g, amt=a, **{k: v for k, v in m.items() if k != 'led'}) for g, a, m in lines]))
        if tally is not None:
            tl = [(s.led(g, m), a) for g, a, m in lines] if tally == 'mirror' else [(l, D(a)) for l, a in tally]
            assert sum(a for _, a in tl) == 0
            cash = [a for l, a in tl if l == s.S['bank']['ledger']]
            vt = 'Journal' if not cash else ('Receipt' if cash[0] > 0 else 'Payment')
            n = len(s.tv) + 1
            mult = s.S['scale'] * (MEMO if s.S['id'] == 'A' else 1)
            tot = sum(a for _, a in tl if a > 0)
            nar = narr or desc
            if s.S['id'] == 'A': nar += f" (USD {tot * s.S['scale']:,.2f} @ {MEMO})"
            s.tv.append(dict(n=n, guid=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{s.seed}-{s.S['id']}-{n}")) + f"-{n:08x}", date=dt, vtype=vt,
                             narration=nar, lines=[(l, q(a * mult, 2)) for l, a in tl], jid=jid, alterid=1000 + n))
        return jid

    def cashline(s, dt, amt, narr, tcode):
        if dt < Q_START: return
        s.bseq += 1
        pre = 'FGIB' if s.S['id'] == 'A' else 'DUBL'
        s.bank.append(dict(date=dt, value_date=dt, narration=narr, ref=f"{pre}{dt:%y%m%d}{s.bseq:04d}", amt=D(amt), tcode=tcode))

    def unit(s, iid, dt, amt, ref):
        s.units.append(dict(investor=iid, date=dt, type='issue', units=int(amt * s.S['scale'] / s.S['par']), price=s.S['par'], ref=ref))


def fn(S, inr, rate):
    return q(inr * 10 / rate) if S['id'] == 'A' else D(inr)


def days_in(a, b):
    """days from the day after `a` to `b` inclusive"""
    return (b - a).days


def build(S, seed, fx):
    B = Books(S, seed); A = S['id'] == 'A'; inv = S['investors']; bk = S['bank']
    sw = lambda i: f"SWIFT {i['swift']}" if A else i['swift']
    # ---------- pre-quarter history (condensed) ----------
    for no, dt, pct in S['hist_calls']:
        for i in inv:
            amt = i['commit'] * pct
            B.post(dt, f"C{S['id']}-{no} contribution received - {i['name']}", 'CALL_RCPT', f"C{S['id']}{no}/{i['id']}",
                   [(1100, amt, {}), (3100, -amt, {'investor': i['id']})])
            B.unit(i['id'], dt, amt, f"C{'G' if A else 'B'}-{no}")
    org = D('0.600') if A else D('1.20')
    B.post(S['hist_calls'][0][1] + timedelta(days=5), 'Organisation expenses paid', 'EXP_PAY', 'ORG', [(5900, org, {}), (1100, -org, {})])
    feeq = S['fee_q'] + S['fee_gst']; vq = sum(v['amt'] for v in S['invoices'] if v['paid'])
    hist_pay = [date(2026, 1, 7), date(2026, 4, 7)]
    for k, dt in enumerate(hist_pay):
        B.post(dt, f"Management fee Q{3 + k} FY26 paid", 'FEE_PAY', f"MF/Q{3 + k}FY26", [(5100, feeq, {}), (1100, -feeq, {})])
        B.post(dt + timedelta(days=3), f"Vendor invoices Q{3 + k} FY26 paid", 'EXP_PAY', f"VEND/Q{3 + k}FY26",
               [(5200, vq, {'led': 'Trusteeship Fees'}), (1100, -vq, {})])
    if A:
        B.post(date(2025, 10, 15), 'Set-up period trustee and legal fees paid', 'EXP_PAY', 'VEND/SETUP',
               [(5200, vq, {'led': 'Legal & Professional Fees'}), (1100, -vq, {})])
    for ins in S['instruments']:
        ins['principal'] = D(0); ins['cost_fn'] = D(0); ins['qty'] = 0
    sched = []  # (date, kind, ins, ...)
    for ins in S['instruments']:
        for t in ins['tranches']:
            sched.append((t['date'], 0, 'DISB', ins, t))
    qends = [date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)]
    for qe in qends:
        for ins in S['instruments']:
            sched.append((qe, 1, 'CPN', ins, None))
    sched.sort(key=lambda z: (z[0], z[1], z[3]['id']))
    qlabel = {qends[0]: 'Q3FY26', qends[1]: 'Q4FY26', qends[2]: 'Q1FY27', qends[3]: 'Q2FY27'}
    qstart = {qends[0]: date(2025, 9, 30), qends[1]: date(2025, 12, 31), qends[2]: date(2026, 3, 31), qends[3]: date(2026, 6, 30)}
    fxr = lambda d: fx.get(d, {date(2026, 3, 31): D('88.50'), date(2026, 6, 30): D('89.00')}.get(d))
    deferred = []  # Q2 events queued so that quarter journals are posted in date order

    def do_disb(dt, ins, t):
        amt = fn(S, t['inr'], t['rate']); t['fn'] = amt
        m = {'instrument': ins['id']}
        if A: m.update(txn_ccy='INR', txn_amt=t['inr'], rate=t['rate'])
        B.post(dt, f"Disbursement {ins['id']} tranche {t['no']} - {ins['spv_name']}", 'DISB', f"DISB/{ins['id']}/T{t['no']}",
               [(1200, amt, m), (1100, -amt, {})])
        nar = (f"OUTW REM SWIFT {bk['swift']} /BNF/ {ins['spv_name'].upper()} /RFB/ DISB {ins['id']} T{t['no']} PROJECT {ins['spv']} "
               f"{ins['kind']} SUBSCRIPTION /INR/ {t['inr'] * 10000000:,.2f} @ {t['rate']}") if A else \
              f"RTGS DR/DUBLR5{dt:%Y%m%d}00{t['units']}/{ins['spv_name'].upper()}/DISB {ins['id']} T{t['no']}/NCD SUBSCRIPTION"
        B.cashline(dt, -amt, nar, 'NTRF')
        ins['principal'] += t['inr']; ins['cost_fn'] += amt; ins['qty'] += t['units']
        B.cust.append(dict(date=dt, isin=ins['isin'], instrument=ins['id'], type='credit', qty=t['units'],
                           ref=f"CORP ACTION ALLOT/{ins['id']}/T{t['no']}", tranche=t['no']))

    def do_cpn(qe, ins):
        if ins['cash'] == 0 and ins['pik'] == 0: return
        op = ins['principal'] - sum(t['inr'] for t in ins['tranches'] if qstart[qe] < t['date'] <= qe)
        segs = []
        if op > 0: segs.append((f"Opening principal", op, days_in(qstart[qe], qe)))
        for t in ins['tranches']:
            if qstart[qe] < t['date'] <= qe: segs.append((f"Tranche {t['no']} from {dmy(t['date'])}", t['inr'], days_in(t['date'], qe)))
        if not segs: return
        cash = q(sum(p * ins['cash'] * dd / 365 for _, p, dd in segs)); pik = q(sum(p * ins['pik'] * dd / 365 for _, p, dd in segs))
        rate = fxr(qe) if A else D(1)
        cfn = S.get('booked', {}).get((ins['id'], qlabel[qe]), fn(S, cash, rate)); m = {'instrument': ins['id']}
        if A: m.update(txn_ccy='INR', txn_amt=cash, rate=rate)
        ql = qlabel[qe]
        B.post(qe, f"Coupon accrued {ins['id']} {ql}", 'ACCR_INT', f"ACCR/{ins['id']}/{ql}", [(1300, cfn, m), (4100, -cfn, m)],
               tally=None if A else 'mirror')
        B.post(qe, f"Coupon received {ins['id']} {ql} - {ins['spv_name']}", 'CPN_RCPT', f"CPN/{ins['id']}/{ql}", [(1100, cfn, {}), (1300, -cfn, m)],
               tally=[(bk['ledger'], cfn), (f"Interest on NCD - {ins['id']}", -cfn)] if A else 'mirror')
        nar = (f"INW REM SWIFT /ORD/ {ins['spv_name'].upper()} /RFB/ CPN {ins['id']} {ql} /INR/ {cash * 10000000:,.2f} @ {rate}") if A else \
              f"RTGS CR/ZZDBR5{qe:%Y%m%d}77{ins['qty']}/{ins['spv_name'].upper()}/{ins['spv']} COUPON/CPN {ins['id']} {ql}"
        B.cashline(qe, cfn, nar, 'NTRF')
        if pik:
            B.post(qe, f"PIK interest accrued {ins['id']} {ql}", 'ACCR_PIK', f"PIK/{ins['id']}/{ql}", [(1300, pik, m), (4110, -pik, m)])
            B.post(qe, f"PIK capitalised into principal {ins['id']} {ql}", 'PIK_CAP', f"PIKCAP/{ins['id']}/{ql}", [(1200, pik, m), (1300, -pik, m)])
        B.accr.append(dict(instrument=ins['id'], period=ql, start=qstart[qe] + timedelta(days=1), end=qe, opening_principal=op,
                           segments=[(n, p, dd) for n, p, dd in segs], days=max(dd for _, _, dd in segs), interest_cash=cash, interest_pik=pik,
                           cash_received=cash, pik_capitalised=pik, closing_principal=ins['principal'] + pik, accrued_unpaid=D(0),
                           rate=rate, inc_fn=cfn + pik))
        ins['principal'] += pik; ins['cost_fn'] += pik

    c, dd_ = S['call'], S['dist']

    def quarter_events_before(dt_limit, done=[0]):
        """post Q2 non-instrument events dated <= dt_limit, in order"""
        for ev in q2:
            if ev[0] <= dt_limit and not ev[2]:
                ev[2] = True; ev[1]()

    q2 = []
    ev = lambda dt, f: q2.append([dt, f, False])
    # E1 fee
    def e_fee():
        dt = S['fee_dates']['q1_paid']
        B.post(dt, 'Management fee Q1 FY27 paid', 'FEE_PAY', 'MF/Q1FY27', [(2100, feeq, {}), (1100, -feeq, {})],
               tally=[('Management Fees', feeq), (bk['ledger'], -feeq)] if A else 'mirror')
        B.cashline(dt, -feeq, (f"OUTW REM SWIFT {bk['swift']} /BNF/ RESIDENTIAL CAPITAL MANAGERS /RFB/ MF Q1FY27 INV RCM/{S['id']}/FY27/Q1" if A else
                               f"NEFT DR/DUBLN{dt:%y%m%d}99001/RESIDENTIAL CAPITAL MANAGERS/MF Q1FY27/INV RCM/B/FY27/Q1 INCL GST"), 'NTRF')
    ev(S['fee_dates']['q1_paid'], e_fee)
    def e_vend():
        for v in [v for v in S['invoices'] if v['paid']]:
            B.post(v['paid'], f"{v['vendor']} invoice {v['no']} paid", 'EXP_PAY', f"INV/{v['no']}", [(2200, v['amt'], {}), (1100, -v['amt'], {})],
                   tally=[(v['led'], v['amt']), (bk['ledger'], -v['amt'])] if A else 'mirror')
            B.cashline(v['paid'], -v['amt'], (f"OUTW REM SWIFT {bk['swift']} /BNF/ {v['vendor'].upper()} /RFB/ INV {v['no']}" if A else
                                             f"NEFT DR/DUBLN{v['paid']:%y%m%d}99{len(B.bank):03d}/{v['vendor'].upper()}/INV {v['no']}"), 'NTRF')
    ev(date(2026, 7, 10), e_vend)
    def e_call():
        B.post(c['notice'], f"Capital call {c['label']} issued ({c['pct'] * 100:.0f}% of commitments)", 'CALL_ISSUE', f"{c['code']}/ISSUE",
               [(1400, sum(i['commit'] * c['pct'] for i in inv), {})] + [(3100, -i['commit'] * c['pct'], {'investor': i['id']}) for i in inv],
               tally=None if A else 'mirror')
    ev(c['notice'], e_call)
    for i in inv:
        def e_rc(i=i):
            dt = c['receipts'][i['id']]; amt = i['commit'] * c['pct']
            B.post(dt, f"{c['label']} receipt - {i['name']}", 'CALL_RCPT', f"{c['code']}/{i['id']}", [(1100, amt, {}), (1400, -amt, {'investor': i['id']})],
                   tally=[(bk['ledger'], amt), (f"Unit Capital - {i['id']}", -amt)] if A else 'mirror')
            B.cashline(dt, amt, (f"INW REM SWIFT {i['swift']} /ORD/ {i['name'].upper()} /BNF/ RESIDENTIAL CREDIT SCHEME I /RFB/ CALL {c['code']} {i['id']}" if A else
                                 f"{'RTGS' if amt >= D('0.02') else 'NEFT'} CR/{i['swift'][:4]}R5{dt:%Y%m%d}{int(amt * 100):06d}/{i['name'].upper()}/CALL {c['code']} {i['id']}"), 'NTRF')
            B.unit(i['id'], dt, amt, c['label'])
        ev(c['receipts'][i['id']], e_rc)
    if c['lpi_date']:
        def e_lpi():
            for i in inv:
                late = (c['receipts'][i['id']] - c['due']).days
                if late > 0:
                    amt = q(i['commit'] * c['pct'] * S['late_rate'] * late / 365)
                    B.post(c['lpi_date'], f"Late-payment interest {c['label']} - {i['name']} ({late} days)", 'LPI', f"LPI/{c['code']}/{i['id']}",
                           [(1100, amt, {}), (4500, -amt, {'investor': i['id']})])
                    B.cashline(c['lpi_date'], amt, f"INW REM SWIFT {i['swift']} /ORD/ {i['name'].upper()} /RFB/ LPI {c['code']} {i['id']} LATE PAYMENT INTEREST", 'NTRF')
        ev(c['lpi_date'], e_lpi)
    gross = prorate(dd_['gross'], B.w, 4)
    def e_decl():
        wht = {k: q(v * B.inv[k]['wht']) for k, v in gross.items()}
        B.dist_lines = [dict(investor=k, gross=gross[k], income=gross[k], roc=D(0), gain=D(0), wht_rate=B.inv[k]['wht'], wht=wht[k], net=gross[k] - wht[k]) for k in gross]
        B.post(dd_['decl'], f"Distribution {dd_['label']} declared (income)", 'DIST_DECL', f"{dd_['code']}/DECL",
               [(3200, gross[k], {'investor': k}) for k in gross] + [(2300, -(dd_['gross'] - sum(wht.values())), {}), (2500, -sum(wht.values()), {})])
    ev(dd_['decl'], e_decl)
    def e_pay():
        for L in B.dist_lines:
            i = B.inv[L['investor']]
            B.post(dd_['pay'], f"{dd_['label']} net paid - {i['name']}", 'DIST_PAY', f"{dd_['code']}/{i['id']}", [(2300, L['net'], {'investor': i['id']}), (1100, -L['net'], {})])
            B.cashline(dd_['pay'], -L['net'], (f"OUTW REM BULK {dd_['code']}/2026/001 /BNF/ {i['name'].upper()} /RFB/ DIST {dd_['code']} {i['id']} NET OF WHT" if A else
                                               f"RTGS DR/DUBLR5{dd_['pay']:%Y%m%d}88{int(L['net'] * 100):05d}/{i['name'].upper()}/DIST {dd_['code']} {i['id']} NET OF TDS"), 'NTRF')
    ev(dd_['pay'], e_pay)
    q2.sort(key=lambda z: z[0])
    for dt, _, kind, ins, t in sched:
        if dt >= Q_START: quarter_events_before(dt if kind == 'DISB' else dt - timedelta(days=1))
        if dt == OPEN_DT and kind == 'CPN' and not getattr(B, 'h_done', False): pass
        if kind == 'DISB': do_disb(dt, ins, t)
        else:
            do_cpn(dt, ins)
            if dt == date(2026, 3, 31) and ins is S['instruments'][-1]:
                pass
            if dt == OPEN_DT and ins is S['instruments'][-1]:
                # 30-Jun closing entries: accruals, cumulative valuation, FX translation (locked opening)
                B.post(OPEN_DT, 'Management fee Q1 FY27 accrued', 'ACCR_FEE', 'ACCR/MF/Q1FY27', [(5100, feeq, {}), (2100, -feeq, {})], tally=None if A else 'mirror')
                B.post(OPEN_DT, 'Vendor expenses Q1 FY27 accrued', 'ACCR_EXP', 'ACCR/VEND/Q1FY27', [(5200, vq, {'led': 'Trusteeship Fees'}), (2200, -vq, {})], tally=None if A else 'mirror')
                for x in S['instruments']:
                    a = fn(S, x['val']['adj_open'], D('89.00'))
                    if a: B.post(date(2026, 3, 31), f"Fair-value adjustment {x['id']} (31-Mar-2026 cycle, carried at 30-Jun-2026 rate)", 'VALUATION',
                                 f"VAL/{x['id']}/31MAR26", [(1210, a, {'instrument': x['id']}), (4600, -a, {'instrument': x['id']})])
                if A:
                    tr = sum(fn(S, x['principal'], D('89.00')) - x['cost_fn'] for x in S['instruments'])
                    B.post(OPEN_DT, 'FX translation of INR assets at 89.00', 'FX_TRANSL', 'FX/30JUN26', [(4700, -tr, {}), (1220, tr, {})], tally=None)
                B.n_hist = len(B.j); B.n_hist_tv = len(B.tv)
    quarter_events_before(Q_END)
    # ---------- 30-Sep closing entries ----------
    B.post(Q_END, 'Bank deposit interest credited', 'BANK_INT', 'BANK/INT', [(1100, S['bank_int'], {}), (4200, -S['bank_int'], {})])
    B.cashline(Q_END, S['bank_int'], 'INT CR ON CALL DEPOSIT 01-JUL-2026 TO 30-SEP-2026' if A else 'INT CR/SWEEP FD INTEREST/01-07-2026 TO 30-09-2026', 'NINT')
    B.post(Q_END, 'Bank charges', 'BANK_CHG', 'BANK/CHG', [(5300, S['bank_chg'], {}), (1100, -S['bank_chg'], {})])
    B.cashline(Q_END, -S['bank_chg'], 'SWIFT CHGS AND ACCOUNT MAINTENANCE Q/E SEP-2026' if A else 'BANK CHGS/RTGS-NEFT AND ACCOUNT MAINTENANCE Q/E SEP-2026 INCL GST', 'NCHG')
    B.post(Q_END, 'Management fee Q2 FY27 accrued', 'ACCR_FEE', 'ACCR/MF/Q2FY27', [(5100, feeq, {}), (2100, -feeq, {})], tally=None if A else 'mirror')
    for v in [v for v in S['invoices'] if not v['paid']]:
        B.post(Q_END, f"{v['vendor']} {v['period']} accrued ({v['no']})", 'ACCR_EXP', f"ACCR/{v['no']}", [(v['gl'], v['amt'], {'led': v['led']}), (2200, -v['amt'], {})],
               tally=None if A else 'mirror')
    rate = fx[Q_END] if A else D(1)
    if A:
        cum = sum(fn(S, x['principal'], rate) - x['cost_fn'] for x in S['instruments'])
        opening = sum(l['amt'] for j in B.j[:B.n_hist] for l in j['lines'] if l['gl'] == 1220)
        B.fx_work = [dict(instrument=x['id'], inr=x['principal'], rate=rate, translated=fn(S, x['principal'], rate), cost=x['cost_fn'],
                          cumulative=fn(S, x['principal'], rate) - x['cost_fn']) for x in S['instruments']]
        B.post(Q_END, f"FX translation of INR assets at {rate}", 'FX_TRANSL', 'FX/30SEP26', [(4700, -(cum - opening), {}), (1220, cum - opening, {})], tally=None)
    B.val_items = []
    for x in S['instruments']:
        v = x['val']; a_open = fn(S, v['adj_open'], D('89.00')); a = fn(S, v['adj'], rate); mv = a - a_open
        m = {'instrument': x['id']}
        if A: m.update(txn_ccy='INR', txn_amt=v['adj'], rate=rate)
        if mv: B.post(Q_END, f"Fair-value adjustment {x['id']} (30-Sep-2026 valuation)", 'VALUATION', f"VAL/{x['id']}/30SEP26", [(1210, mv, m), (4600, -mv, m)])
        B.val_items.append(dict(instrument=x['id'], principal_inr=x['principal'], accrued_inr=D(0), adj_inr=v['adj'], fv_inr=x['principal'] + v['adj'],
                                adj_fn=a, movement_fn=mv, prior_adj_inr=v['adj_open'], method=v['method'], level=v['level'], y=v['y'], y_prior=v['y_prior'], note=v['note']))
    # running bank balance
    return finish(B)


def tb(journals):
    t = {}
    for j in journals:
        for l in j['lines']: t[l['gl']] = t.get(l['gl'], D(0)) + l['amt']
    return t


def alloc(B, journals):
    S = B.S
    wa = {k: v for k, v in B.w.items() if B.inv[k]['cls'] == 'A'}
    tot = {}
    for j in journals:
        for l in j['lines']:
            if l['gl'] in CAT: tot[CAT[l['gl']]] = tot.get(CAT[l['gl']], D(0)) - l['amt']
    out = {k: {} for k in B.w}
    for cat in ('income', 'fee', 'expense', 'fv', 'fx'):
        pr = prorate(tot.get(cat, D(0)), wa if cat == 'fee' else B.w)
        for k in B.w: out[k][cat] = pr.get(k, D(0))
    for k in B.w:
        out[k]['contributions'] = -sum(l['amt'] for j in journals for l in j['lines'] if l['gl'] == 3100 and l.get('investor') == k)
        out[k]['distributions'] = -sum(l['amt'] for j in journals for l in j['lines'] if l['gl'] == 3200 and l.get('investor') == k)
    return out, tot


def finish(B):
    S = B.S; H, Q = B.j[:B.n_hist], B.j[B.n_hist:]
    # opening cash from history, bank running balance
    tbo = tb(H); bal = tbo[1100]; B.open_cash = bal
    B.bank.sort(key=lambda b: b['date'])
    for b in B.bank:
        bal += b['amt']; b['balance'] = bal
    tbc = tb(B.j)
    assert tbc[1100] == bal, (tbc[1100], bal)
    pl = lambda t: {g: a for g, a in t.items() if GL[g][1] in ('income', 'expense')}
    acc_open = sum(pl(tbo).values())
    open_tb = {g: a for g, a in tbo.items() if g not in pl(tbo)}; open_tb[3900] = acc_open
    for g in (1300, 1400, 2300, 2500, 3200):
        open_tb.setdefault(g, D(0))
    if S['id'] == 'A': open_tb.setdefault(1220, D(0))
    tq = tb(Q)
    close_tb = dict(open_tb)
    for g, a in tq.items(): close_tb[g] = close_tb.get(g, D(0)) + a
    assert sum(open_tb.values()) == 0 and sum(close_tb.values()) == 0
    ho, _ = alloc(B, H); qo, qt = alloc(B, Q)
    units = {k: sum(u['units'] for u in B.units if u['investor'] == k) for k in B.w}
    units_open = {k: sum(u['units'] for u in B.units if u['investor'] == k and u['date'] <= OPEN_DT) for k in B.w}
    ca = {}
    for k in B.w:
        o = ho[k]; opening = o['contributions'] + o['distributions'] + sum(o[c] for c in ('income', 'fee', 'expense', 'fv', 'fx'))
        x = qo[k]
        closing = opening + x['contributions'] + x['distributions'] + sum(x[c] for c in ('income', 'fee', 'expense', 'fv', 'fx'))
        ca[k] = dict(cls=B.inv[k]['cls'], opening=opening, contributions=x['contributions'], distributions_roc=D(0), distributions_income=x['distributions'],
                     income_alloc=x['income'], fee_alloc=x['fee'], expense_alloc=x['expense'], fv_alloc=x['fv'], fx_alloc=x['fx'], carry_alloc=D(0),
                     closing=closing, units=units[k], units_open=units_open[k], nav_per_unit=q(closing * S['scale'] / units[k], 4))
    nav = lambda t: sum(a for g, a in t.items() if GL[g][1] in ('asset', 'liability'))
    nav_open, nav_close = nav(open_tb), nav(close_tb)
    assert sum(c['opening'] for c in ca.values()) == nav_open and sum(c['closing'] for c in ca.values()) == nav_close, (nav_open, nav_close)
    cls = {}
    for c in ('A', 'B'):
        ks = [k for k in ca if ca[k]['cls'] == c]
        n = sum(ca[k]['closing'] for k in ks); u = sum(ca[k]['units'] for k in ks)
        cls[c] = dict(nav=n, units=u, nav_per_unit=q(n * S['scale'] / u, 4), units_open=sum(ca[k]['units_open'] for k in ks))
    # performance (fund level, call due dates, gross distributions)
    cd = S['call']; dd = S['dist']
    calls = [(dt, S['committed'] * p) for _, dt, p in S['hist_calls']] + [(cd['due'], S['committed'] * cd['pct'])]
    dists = [(dd['pay'], dd['gross'])]
    paid = sum(a for _, a in calls); dist = sum(a for _, a in dists)
    irr = xirr([(d, -a) for d, a in calls] + dists + [(Q_END, nav_close)])
    wf = waterfall(nav_close, calls, dists, Q_END, S['hurdle'], S['carry'])
    B.calls_perf, B.dists_perf = calls, dists
    B.open_tb, B.close_tb, B.ca, B.cls, B.nav_open, B.nav_close = open_tb, close_tb, ca, cls, nav_open, nav_close
    f = lambda x: str(x)
    cust = {}
    for x in S['instruments']:
        cust[x['isin']] = dict(instrument=x['id'], open=sum(c['qty'] for c in B.cust if c['isin'] == x['isin'] and c['date'] <= OPEN_DT),
                               close=sum(c['qty'] for c in B.cust if c['isin'] == x['isin']))
    B.custody = cust
    B.expected = dict(
        unit=S['unit'], name=S['name'],
        opening_tb={str(g): f(a) for g, a in sorted(open_tb.items())}, closing_tb={str(g): f(a) for g, a in sorted(close_tb.items())},
        closing_tb_note='closing_tb is pre-closing: 3900 holds the accumulated result at 30-Jun-2026; income/expense accounts hold the quarter',
        nav_open=f(nav_open), nav_close=f(nav_close), quarter={k: f(v) for k, v in qt.items()} | {'result': f(sum(qt.values()))},
        accumulated_result_close=f(-(open_tb[3900]) + sum(qt.values())),
        units_total=sum(units.values()), units_open_total=sum(units_open.values()),
        classes={c: {k: (f(v) if isinstance(v, D) else v) for k, v in d.items()} for c, d in cls.items()},
        nav_per_unit_fund=f(q(nav_close * S['scale'] / sum(units.values()), 4)),
        capital_accounts={k: {a: (f(b) if isinstance(b, D) else b) for a, b in v.items()} for k, v in ca.items()},
        bank=dict(opening=f(B.open_cash), closing=f(bal), lines=len(B.bank), closing_base=f(q(bal * S['scale'], 2))),
        custody=cust, wht_payable=f(-close_tb[2500]), carry_provision=f(wf['carry']),
        performance=dict(paid_in=f(paid), distributed=f(dist), nav=f(nav_close), irr=irr, tvpi=f(q((dist + nav_close) / paid, 6)),
                         dpi=f(q(dist / paid, 6)), rvpi=f(q(nav_close / paid, 6))),
        counts=dict(journals_q2=len(Q), tally_vouchers_q2=len(B.tv) - B.n_hist_tv, bank_lines=len(B.bank)),
        instruments={x['id']: dict(principal_inr_cr=f(x['principal']), cost=f(x['cost_fn']), quantity=x['qty']) for x in S['instruments']},
    )
    return B


def make_fx(seed):
    """Daily USD/INR reference rates Jul-Sep 2026 (business days), pinned on event dates."""
    rng = random.Random(seed)
    pins = {date(2026, 6, 30): 89.00, date(2026, 8, 5): 89.15, date(2026, 9, 30): 89.40}
    days = [OPEN_DT + timedelta(days=k) for k in range(0, 93)]
    days = [d for d in days if d.weekday() < 5 and d not in (date(2026, 8, 15),)]
    out = {}; keys = sorted(pins)
    for a, b in zip(keys, keys[1:]):
        seg = [d for d in days if a <= d <= b]; n = len(seg) - 1; w = [0.0]
        for _ in range(n): w.append(w[-1] + rng.gauss(0, 0.06))
        for k, d in enumerate(seg):
            out[d] = D(str(round(pins[a] + (pins[b] - pins[a]) * k / n + (w[k] - w[-1] * k / n), 4))).quantize(D('0.0001'))
    out.pop(OPEN_DT)
    return out

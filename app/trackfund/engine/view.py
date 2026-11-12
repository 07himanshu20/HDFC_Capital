"""Builds the dashboard view model (the `DATA` object the front end renders) from parsed files + books.

Every value here traces to a parsed file or to the engine, except the organisation profile (manager
details, provider display names, investor payment banks) which is master data kept in the database.
"""
import re
from decimal import Decimal as D
from datetime import date, timedelta

from ..parsing.util import num, dt, dt_or_none, col, col_or, q
from .coa import GL
from .regreport import model as regulator_report


def jsonable(o):
    if isinstance(o, D):
        return float(o)
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(x) for x in o]
    return o


def _f(x):
    return float(x) if x is not None else None


def _pct(x):
    return f"{num(x) * 100:.2f}%" if isinstance(x, (int, float)) else str(x)


def _prior_cycle(X):
    """date of the previous valuation cycle, from the 'FV adjustment at <date>' column of the valuer's workbook"""
    for r in X['valuation_inputs']['summary'].values():
        for h in r:
            m = re.match(r'FV adjustment at (\d{2}-\w{3}-\d{4})', str(h))
            if m:
                return dt(m.group(1))
    return None



def _cp_lists(X):
    """Conditions checklists per instrument, from CP_Checklist_<instrument>_T<n>.xlsx (or the title '... - <instrument> tranche <n>').
    Each condition keeps the date the file gives it; the list is in date order."""
    out = {}
    for c in X.get('cp_checklists', []):
        m = re.search(r'CP_Checklist_(.+?)_T(\d+)\.xlsx$', c['file']) or re.search(r'-\s*(\S+)\s+tranche\s+(\d+)', c.get('title', ''), re.I)
        if not m:
            continue
        rows = []
        for r in c['rows']:
            dm = re.search(r'\d{1,2}-[A-Za-z]{3}-\d{4}|\d{4}-\d{2}-\d{2}', r['detail'] or '')
            rows.append(dict(no=r['no'], condition=r['condition'], met=str(r['met'] or '').strip().lower() == 'yes', date=dt_or_none(dm.group(0)) if dm else None,
                             detail=r['detail'] or '', evidence=r['evidence'] or ''))
        rows.sort(key=lambda r: (r['date'] is None, r['date'] or date.min, r['no']))
        out.setdefault(m.group(1), []).append(dict(tranche=int(m.group(2)), title=c.get('title', ''), file=c['file'], rows=rows))
    return out


def _filings(X):
    """Statutory filings per instrument as the documents state them: ROC charge (CHG-9), FC-GPR, pricing certificate."""
    out = {}
    tr = lambda v: int(num(v)) or None
    for f in X.get('charge_filings', []):
        mod = dt_or_none(f.get('Date of modification') or f.get('Date of creation'))
        out.setdefault(f.get('Instrument ID'), []).append(dict(
            kind='charge', form=f"ROC charge ({f.get('Form') or 'CHG'})", ref=f.get('SRN', ''), tranche=None, event=mod,
            due=mod + timedelta(days=30) if mod else None, filed=dt_or_none(f.get('Filed date')), status=f.get('Status', ''), status_date=None, file=f['file']))
    for f in X.get('fcgpr', []):
        ack = dt_or_none(f.get('Acknowledgement date'))
        out.setdefault(f.get('Instrument ID'), []).append(dict(
            kind='fema', form=f.get('Form') or 'FC-GPR', ref=f.get('Acknowledgement No', ''), tranche=tr(f.get('Tranche no')), event=dt_or_none(f.get('Allotment date')),
            due=dt_or_none(f.get('Due date')), filed=dt_or_none(f.get('Filed date')), status='Acknowledged' if ack else (f.get('Status') or ''), status_date=ack, file=f['file']))
    for f in X.get('pricing_certs', []):
        out.setdefault(f.get('Instrument ID'), []).append(dict(
            kind='pricing', form='Pricing certificate', ref=f.get('Certificate No', ''), tranche=tr(f.get('Tranche no')), event=None, due=None,
            filed=dt_or_none(f.get('Certificate date')), status='On file', status_date=None, file=f['file']))
    return out


def _aml(X):
    """FIU-IND registration, the Form 61B filing (compliance calendar) and net-worth certificates, for the KYC page."""
    fg = X.get('fingate')
    ob = next((r for r in X['calendar'] if '61B' in str(r.get('Obligation', ''))), None)
    return dict(
        fiu=dict(entity=fg.get('Reporting entity', ''), reg_no=fg.get('FIU registration no', ''), po=fg.get('Principal Officer', ''), dd=fg.get('Designated Director', ''),
                 reg_date=dt_or_none(fg.get('Registration date')), status=fg.get('Status', ''), file=fg['file']) if fg else None,
        form61b=dict(name=str(ob.get('Obligation', '')), period=str(ob.get('Period') or ''), due=dt_or_none(ob.get('Due date')), filed=dt_or_none(ob.get('Completed / filed date')),
                     status=ob.get('Status') or '', evidence=ob.get('Evidence file') or '') if ob else None,
        networth=[dict(investor=f.get('Investor ID', ''), name=f.get('Investor', ''), date=dt_or_none(f.get('Certificate date')), amount=num(f.get('Net worth certified (INR cr)')),
                       file=f['file']) for f in X.get('networth', [])])


def scheme_view(X, Bk, profile=None):
    profile = profile or {}
    sid = X['scheme']['id']
    A = X['scheme']['fx']
    sc = X['scheme']['scale']
    ccy = X['scheme']['ccy']
    u = lambda v: num(v) / sc
    P = X['period']
    terms = X['ppm']['kv']
    unit_lbl = X['opening']['unit']
    pp = profile.get('schemes', {}).get(sid, {})

    # ---------------- meta ----------------
    bpdf = X['bank']['pdf']
    tled_groups = X['tally']['tb']['groups']
    bank_ledger = next((n for n, g in tled_groups.items() if g == 'Bank Accounts'), '')
    dh = X['demat_holding']
    vend = Bk['vend']
    by_role = {}
    for k in vend:
        by_role.setdefault(k.get('Service'), k['Vendor'])
    val_kv = X['valuation_report']['kv']
    valuer, _, valuer_reg = (val_kv.get('Registered valuer', '') + ', ').partition(', ')
    vrow = next((r for r in X['calendar'] if 'aluation' in r['Obligation']), None)
    cert_section = X['tax_certs'][0].get('Section') if X['tax_certs'] else None
    reg = X['ppm']['kv'].get('Regulator', '')
    fee_cur = X['fee_invoices'][P['qcode']]
    providers = dict(trustee=X['ppm']['trustee'], administrator=by_role.get('administrator') or (by_role.get('rta', '') + ' (RTA)' if by_role.get('rta') else ''),
                     custodian=dh['dp_name'], valuer=valuer.strip(), valuer_reg=valuer_reg.strip(', ').strip(), auditor=by_role.get('audit', ''), legal=by_role.get('legal', ''),
                     bank=bpdf['head']['name'])
    providers.update(pp.get('providers', {}))
    meta = dict(
        id=sid, name=terms.get('Scheme'), regulator=reg, category=terms.get('Structure', '').split(';')[0].strip(),
        domicile=pp.get('domicile') or ('GIFT IFSC' if reg == 'IFSCA' else 'India'), ccy=ccy, unit=unit_lbl, scale=sc, reg_no=X['ppm']['reg_no'],
        par=num(terms[f"Unit par value ({ccy})"]), target=num(terms[f"Target corpus ({unit_lbl})"]), committed=num(terms[f"Total commitments ({unit_lbl})"]),
        first_close=dt(terms['First close']), fee_rate=num(terms['Management fee rate (% p.a.)']) / 100, hurdle=num(terms['Hurdle rate (% p.a.)']) / 100,
        carry=num(terms['Carried interest (%)']) / 100, late_rate=num(terms['Late-payment interest (% p.a.)']) / 100,
        single_limit=num(terms['Single-investee limit (% of investable funds)']) / 100, min_corpus=num(terms[f"Minimum corpus ({unit_lbl})"]),
        tax_name=X['ppm']['tax_name'], tax_section=cert_section or X['challan'].get('Section', ''),
        bank=dict(name=bpdf['head']['name'], branch=bpdf['kv'].get('Branch', ''), swift=bpdf['kv'].get('SWIFT', ''), acct=bpdf['kv'].get('Account number', ''),
                  ifsc=bpdf['kv'].get('IFSC', ''), ledger=bank_ledger),
        dp=dict(name=dh['dp_name'], dp_id=dh['kv'].get('DP ID', ''), client=dh['kv'].get('Client ID', ''), depository=dh['depository']),
        providers=providers,
        fee_q=u(fee_cur[f"Management fee ({ccy})"]), fee_gst=u(fee_cur.get(f"GST ({ccy})", 0)),
        val_dates=dict(report=dt(val_kv['Report date']), received=dt(X['valuation_inputs']['cover']['Received by FME']),
                       dispatched=dt_or_none(vrow.get('Completed / filed date')) if vrow else None, prior=_prior_cycle(X)),
        period=dict(code=P['qcode'], label=P['label'], start=P['q_start'], end=P['q_end'], open=P['open_dt'], prev_code=P['prev_qcode'], prev_label=P['prev_label']),
    )

    # ---------------- investors ----------------
    kreg = {r['Investor ID']: r for r in X['kyc']['register']}
    fat = {r['Investor ID']: r for r in X['kyc']['fatca']}
    banks = pp.get('investor_banks', {})
    # KYC register sheets: documents held and screening runs per investor (dates, lists, outcome, who verified)
    kdocs, kscreen = {}, {}
    for d_ in X['kyc']['documents']:
        kdocs.setdefault(d_['Investor ID'], []).append(dict(type=d_.get('Document type', ''), file=d_.get('File') or '', received=dt_or_none(d_.get('Received date')),
                                                            refresh=dt_or_none(d_.get('Expiry / refresh date')), verified_by=d_.get('Verified by') or ''))
    for s_ in X['kyc']['screening']:
        kscreen.setdefault(s_['Investor ID'], []).append(dict(date=dt_or_none(s_.get('Run date')), lists=s_.get('Lists') or '', hits=int(num(s_.get('Hits'))),
                                                              outcome=s_.get('Disposition') or '', reviewer=s_.get('Reviewer') or ''))
    investors = []
    for r in X['investor_register']['investors']:
        i = r['Investor ID']
        k = kreg.get(i, {})
        fc = fat.get(i, {})
        c = Bk['capital'][i]
        investors.append(dict(
            id=i, name=r['Legal name'], type=r['Type'], country=r['Country'], cls=r['Unit class'], commit=u(col(r, 'Commitment')), wht=num(col(r, 'rate')),
            risk=k.get('Risk rating', ''), pep=k.get('PEP flag', ''), refresh=dt_or_none(k.get('Next refresh date')), fatca=fc.get('FATCA status', ''), crs=fc.get('CRS status', ''),
            bo=k.get('Beneficial ownership summary', ''), tin=fc.get('TIN / PAN', '') or '', giin=fc.get('GIIN') or '', bank=banks.get(i, ''),
            screened=dt_or_none(k.get('Last screening date')), reportable=str(fc.get('Reportable') or '').strip().lower() == 'yes',
            selfcert=fc.get('Self-certification file') or '', kyc_docs=kdocs.get(i, []), screening=kscreen.get(i, []),
            ca=dict(cls=c['cls'], opening=c['opening'], contributions=c['contributions'], distributions_roc=c['distributions_roc'], distributions_income=c['distributions_income'],
                    income_alloc=c['income_alloc'], fee_alloc=c['fee_alloc'], expense_alloc=c['expense_alloc'], fv_alloc=c['fv_alloc'], fx_alloc=c['fx_alloc'],
                    carry_alloc=c['carry_alloc'], closing=c['closing'], units=c['units'], units_open=c['units_open'], nav_per_unit=c['nav_per_unit'])))
    side_letters = [[r['Investor ID'], r['Clause type'], r['Value'], r['MFN status']] for r in X['side_letters']]

    # ---------------- instruments ----------------
    instruments = []
    cps, filings = _cp_lists(X), _filings(X)
    summ = X['instrument_summaries']
    vin = X['valuation_inputs']
    prior_hdr = next((h for h in (next(iter(vin['summary'].values()), {}) or {}) if h.startswith('FV adjustment at')), None)
    for r in X['deal']['instruments']:
        k = r['Instrument ID']
        x = Bk['ins'][k]
        spv = r['Project SPV']
        trs = [t for t in Bk['tranches'] if t['ins'] == k]
        vs = vin['summary'].get(k, {})
        vi = vin['inputs'].get(k, {})
        vit = Bk['val_items'].get(k, {})
        mis_files = X['mis'].get(spv, {})
        mis_rows = []
        layout = 1
        for mth in Bk['months']:
            mf = mis_files.get(mth)
            if not mf:
                continue
            layout = mf['layout']
            fl = mf['fields']
            g = lambda f: fl[f]['vals'][-1][1] if f in fl else None
            mis_rows.append(dict(label=str(fl['sold']['vals'][-1][0]), sold=g('sold'), cum=g('cum'), value=g('value'), coll=g('coll'), esc=g('esc'), cons=g('cons'), cost=g('cost'), ctc=g('ctc')))
        mb = Bk['mis_by_ins'][k]
        cert = X['covenant_certs'][spv]
        tests = [dict(name=t[0], min=t[1], actual=t[2], ok=t[3] == 'PASS') for t in cert['tests']]
        lvl = re.search(r'(\d+)', str(vs.get('Hierarchy', '')))
        instruments.append(dict(
            id=k, spv=spv, spv_name=r['SPV legal name'], developer=r['Developer'], city=r['City'], micro=r['Micro-market'], kind=r['Kind'],
            kind_long=summ.get(k, {}).get('Instrument', r['Kind']), isin=r['ISIN'], fv=r['Face value (INR)'], cash=x['cash'], pik=x['pik'], tenor=r['Tenor (months)'],
            security=r['Security'], chg=r.get('Charge filing ref'), rera=r.get('RERA No'), homes=r.get('Homes planned'),
            principal=Bk['principal'][k], cost=Bk['cost'][k], qty=Bk['qty'][k], qty_open=int(X['opening']['instruments'][k]['Quantity']),
            tranches=[dict(no=t['no'], date=t['date'], inr=t['inr'], rate=t['rate'], fn=t['fn'], units=t['units']) for t in trs],
            val=dict(instrument=k, principal_inr=num(vs.get('Principal (INR cr)')), accrued_inr=num(vs.get('Accrued interest (INR cr)')), adj_inr=num(vs.get('FV adjustment (INR cr)')),
                     fv_inr=num(vs.get('Fair value (INR cr)')), adj_fn=vit.get('adj_fn'), movement_fn=vit.get('movement_fn'), prior_adj_inr=num(vs.get(prior_hdr)) if prior_hdr else D(0),
                     method=vs.get('Method'), level=int(lvl.group(1)) if lvl else None, y=_pct(vi.get('Yield / discount rate', '')), y_prior=_pct(vi.get('Prior-cycle rate', '')),
                     note=vi.get('Valuer note', '')),
            mis=mis_rows, mis_layout=layout, cum_open=(mis_rows[0]['cum'] - mis_rows[0]['sold']) if mis_rows else None,
            cost_total=(num(mis_rows[0]['cost']) + num(mis_rows[0]['ctc'])) if mis_rows else None,
            cov=dict(vel=mb['sold'], coll=mb['coll'], cover=mb['cover'], ds=mb['ds'], tests=tests),
            accr=[dict(a) for a in Bk['accr_hist'].get(k, [])],
            cp=cps.get(k, []), filings=filings.get(k, []),
        ))

    # ---------------- journals and bank ----------------
    bank_jv = {}
    journals = []
    for j in Bk['journals']:
        bloc = Bk['bank'][j['bank']]['loc'] if j['bank'] is not None else None
        if j['bank'] is not None:
            bank_jv[j['bank']] = j['no']
        journals.append(dict(no=j['no'], date=j['date'], desc=j['desc'], kind=j['kind'], ref=j['ref'], src=j['src'], bank=bloc, tally=j.get('tally'),
                             lines=[{kk: vv for kk, vv in l.items()} for l in j['lines']]))
    bank = [dict(date=b['date'], narr=b.get('narr_full', b['narr']), ref=b['ref'], amt=b['amt'] / sc, bal=b['bal'] / sc, jv=bank_jv.get(i)) for i, b in enumerate(Bk['bank'])]

    # ---------------- call / distribution / invoices ----------------
    c = Bk['call']
    rows = []
    for r in c['rows']:
        i = r['Investor ID']
        rc = c['receipts'].get(i, {})
        rows.append(dict(id=i, amt=u(r['Amount called']), inv=u(r['Investment component']), fee=u(r['Fee component']), exp=u(r['Expense component']),
                         cum=u(col(r, 'Cumulative called')), unf=u(col(r, 'Unfunded')), rc=rc.get('date'), late=rc.get('late', 0)))
    lpi_dates = [j['date'] for j in Bk['journals'] if j['kind'] == 'LPI']
    call = dict(code=c['code'], label=c['label'], notice=c['notice'], due=c['due'], pct=c['pct'], purpose=c['kv'].get('Purpose', ''), lpi_date=lpi_dates[0] if lpi_dates else None, rows=rows)
    d_ = Bk['dist']
    dn = X['dist']['notices']
    dist = dict(code=d_['code'], label=d_['label'], decl=d_['decl'], pay=d_['pay'], gross=d_['gross'], source=(dn[0].get('Source', '') if dn else ''),
                deposit=dt(X['challan']['Deposit date']), challan=X['challan'].get('Challan No', ''),
                cert_date=dt(X['tax_certs'][0]['Certificate date']) if X['tax_certs'] else None,
                rows=[dict(investor=k, gross=v['gross'], income=v['income'], roc=v['roc'], gain=v['gain'], wht_rate=v['rate'], wht=v['wht'], net=v['net']) for k, v in d_['lines'].items()])
    invoices = []
    for k in vend:
        m = re.search(r'Paid (\d{2}-\w{3}-\d{4})', k.get('Status', ''))
        invoices.append(dict(no=k['Invoice No'], role=k.get('Service'), vendor=k['Vendor'], period=k.get('Period'), date=dt(k['Invoice date']), amt=u(k[f"Invoice total ({ccy})"]),
                             paid=dt(m.group(1)) if m else None))

    # ---------------- Tally ----------------
    tb = X['tally']['tb']
    tally = dict(
        vouchers=[dict(no=v['no'], date=v['date'], type=v['vt'], narr=v['narr'], lines=[[l, a] for l, a, _ in v['lines']], guid=v['guid']) for v in X['tally']['vouchers']],
        tb=[dict(name=n, group=tb['groups'].get(n), open=v[0] - v[1], dr=v[2], cr=v[3], close=v[4] - v[5]) for n, v in tb['ledgers'].items()],
        bridge=Bk['bridge'])

    # ---------------- compliance ----------------
    obligations = [dict(ref=r['Ref'], reg=r['Regulator'], title=r['Obligation'], period=str(r['Period']), due=dt(r['Due date']), status=r['Status'],
                        done=dt_or_none(r.get('Completed / filed date')), owner=r.get('Owner role'), basis=r.get('Basis'), evidence=r.get('Evidence file') or '',
                        verify=r.get('Verify') or '') for r in X['calendar']]
    files = [dict(file=r['rel'], format=r['format'], sha=r['sha256'][:16], feeds=r['feeds'], who=r['who'], page=r['page']) for r in X['register'] if r.get('doc')]

    perf = Bk['performance']
    pl = Bk['pl']
    expected = dict(quarter={k: str(v) for k, v in pl.items()} | {'result': str(sum(pl.values()))},
                    performance=dict(paid_in=str(perf['paid_in']), distributed=str(perf['distributed']), nav=str(perf['nav']), irr=perf['irr'], tvpi=str(perf['tvpi']),
                                     dpi=str(perf['dpi']), rvpi=str(perf['rvpi'])),
                    carry_provision=str(Bk['carry']), units_total=Bk['units_total'], units_open_total=Bk['units_open_total'],
                    nav_per_unit_fund=str(q(Bk['nav_close'] * sc / Bk['units_total'], 4)))

    # rates as the files give them, for the captions of the FX, quarter-close and Tally pages
    fx_dates = sorted(X['fx'])
    fx_info = dict(pair=X['fx_info']['pair'], first=fx_dates[0] if fx_dates else None, last=fx_dates[-1] if fx_dates else None,
                   close_date=P['q_end'] if A else None, close_rate=X['fx'].get(P['q_end']) if A else None, memo_rate=Bk['memo'],
                   sources=[X['fx_info']['source'].get(d_, '') for d_ in fx_dates])

    out = dict(
        meta=meta, investors=investors, side_letters=side_letters, instruments=instruments, journals=journals, bank=bank, open_cash=Bk['open_bank'] / sc,
        open_tb=Bk['open_tb'], close_tb=Bk['close_tb'], nav_open=Bk['nav_open'], nav_close=Bk['nav_close'], classes=Bk['classes'], expected=expected,
        calls_perf=[[d_, a] for d_, a in Bk['calls_perf']], dists_perf=[[d_, a] for d_, a in Bk['dists_perf']], fx=[[k, v] for k, v in sorted(X['fx'].items())],
        fx_work=Bk['fx_work'], fx_info=fx_info, aml=_aml(X), call=call, dist=dist, invoices=invoices, tally=tally, obligations=obligations, rules=list(Bk['rules']), files=files,
        reg_report=regulator_report(X, Bk, meta, investors, instruments),
    )
    return jsonable(out)


def dashboard_data(scheme_views, manager, global_rules):
    for v in scheme_views.values():
        v['rules'] = v['rules'] + global_rules
    return dict(gl={str(g): list(v) for g, v in GL.items()}, manager=manager, schemes=scheme_views)

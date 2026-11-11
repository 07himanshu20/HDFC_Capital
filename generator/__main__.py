import argparse, json, os, shutil, sys
from .core import scheme_A, scheme_B, build, make_fx
from .base import Out, sha
from . import files1 as f1, files2 as f2


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--seed', type=int, default=20260930); ap.add_argument('--out', default='dataset/Q2FY27'); a = ap.parse_args()
    if os.path.isdir(a.out): shutil.rmtree(a.out)
    fx = make_fx(a.seed); o = Out(a.out); Bs = []
    for mk in (scheme_A, scheme_B):
        B = build(mk(), a.seed, fx); Bs.append(B)
        for fn in (f1.r_bank, f1.r_demat, f1.r_tally, f1.r_call, f1.r_dist, f2.r_val, f2.r_deal, f2.r_mis, f2.r_kyc, f2.r_cal, f2.r_inv, f2.r_reg): fn(o, B)
    f2.r_shared(o, Bs[0], Bs[1], fx)
    o.flush()
    exp = dict(meta=dict(period='Q2 FY27', start='2026-07-01', end='2026-09-30', seed=a.seed, tolerance='0.0005 in scheme unit',
                         note='Golden totals written by the generator from its event engine; validation/run.py re-derives them from the source files only.'),
               A=Bs[0].expected, B=Bs[1].expected)
    for B in Bs:
        exp[B.S['id']]['covenants'] = {c['instrument']: dict(units_sold=c['vel'], collections=str(c['coll']), cover=str(c['cover']), breached=[t[0] for t in c['tests'] if not t[3]]) for c in B.cov}
        exp[B.S['id']]['obligations'] = dict(total=len(B.obligations), filed_or_done=sum(1 for r in B.obligations if r[4] in ('Filed', 'Done')))
    with open(os.path.join(a.out, 'expected_results.json'), 'w') as f: json.dump(exp, f, indent=1, sort_keys=True)
    man = [dict(file=rel, format=rel.rsplit('.', 1)[1], sha256=sha(os.path.join(a.out, rel)), feeds=v['feeds'], produced_by=v['who'], consumed_by=v['page']) for rel, v in sorted(o.reg.items())]
    with open(os.path.join(a.out, 'manifest.json'), 'w') as f: json.dump(dict(seed=a.seed, period='Q2 FY27', files=man), f, indent=1)
    rd = ['# Q2 FY27 synthetic dataset', '', 'Two independent schemes, one quarter (1 Jul - 30 Sep 2026). All names, registration numbers and people are fictional. The feeder sleeve is not in this dataset.', '',
          f'Generated with `python -m generator --seed {a.seed}`. {len(man)} source files.', '', '| File | Normally produced by | Consumed by (UI page) | Feeds tables |', '|---|---|---|---|']
    rd += [f"| `{m['file']}` | {m['produced_by']} | {m['consumed_by']} | {', '.join(m['feeds'])} |" for m in man]
    with open(os.path.join(a.out, 'README_dataset.md'), 'w') as f: f.write('\n'.join(rd) + '\n')
    print(f"{len(man)} files written to {a.out}")


main()

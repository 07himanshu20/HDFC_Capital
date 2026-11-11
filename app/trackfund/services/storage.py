"""Upload handling: safe zip extraction and building the file workspace a run reads from.

Workspace layout (one per ingestion run, never modified after the run):
    <STORAGE_DIR>/runs/<run_id>/dataset/scheme_<X>_<name>/...   scheme files
                                       /shared/Opening_Balances_*.xlsx
                                       /manifest.json, expected_results.json   (optional, acceptance testing)

Two upload modes:
  replace  the upload is a complete quarter (zip with scheme folders): the workspace is exactly the upload
  merge    the upload adds or corrects files: the previous run's workspace is copied, then the uploaded files
           are laid over it (a single-instance document such as a bank statement replaces the old one even if
           its file name changed)
"""
import os
import re
import shutil
import zipfile
from pathlib import Path

from ..catalog import classify
from ..config import STORAGE_DIR, MAX_UPLOAD_MB, MAX_FILES_PER_UPLOAD
from ..pipeline import SCHEME_DIR, layout_from_dir

# document types of which a scheme has exactly one per quarter
SINGLE = {'opening_balances', 'ppm_term_sheet', 'investor_register', 'side_letters', 'kyc_register', 'deal_master', 'unit_register', 'bank_mt940', 'bank_csv',
          'bank_xls', 'bank_pdf', 'fx_rates', 'demat_holding', 'demat_txn', 'call_allocation', 'dist_schedule', 'dist_payment_file', 'tax_challan', 'valuation_inputs',
          'valuation_report', 'tally_daybook', 'tally_ledgers', 'tally_tb', 'calendar', 'prior_report'}
IGNORED_DIRS = {'__MACOSX', 'generator', 'validation', 'docs', '.git'}


class UploadError(Exception):
    pass


def safe_extract(zip_path, dest):
    dest = Path(dest).resolve()
    total = 0
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace('\\', '/')
            parts = [p for p in name.split('/') if p not in ('', '.')]
            if any(p == '..' for p in parts) or name.startswith('/') or any(p in IGNORED_DIRS for p in parts) or parts[-1].startswith('.'):
                continue
            n += 1
            total += info.file_size
            if n > MAX_FILES_PER_UPLOAD:
                raise UploadError(f"Too many files in archive (limit {MAX_FILES_PER_UPLOAD})")
            if total > MAX_UPLOAD_MB * 1024 * 1024 * 3:
                raise UploadError('Archive expands beyond the size limit')
            target = (dest / '/'.join(parts)).resolve()
            if not str(target).startswith(str(dest)):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out)
    return n


def run_dir(run_id):
    return STORAGE_DIR / 'runs' / str(run_id) / 'dataset'


def staging_dir(upload_id):
    return STORAGE_DIR / 'uploads' / str(upload_id)


def _scheme_folder_for(code, existing):
    for f in existing:
        m = SCHEME_DIR.match(f)
        if m and m.group(1) == code:
            return f
    return f"scheme_{code}_files"


def build_workspace(staged: Path, target: Path, mode: str, previous: Path | None, scheme_hint: str | None):
    """Lay out the uploaded files into `target` (the run workspace). Returns list of (scheme, rel) that came from this upload."""
    target.mkdir(parents=True, exist_ok=True)
    if mode == 'merge' and previous and previous.exists():
        shutil.copytree(previous, target, dirs_exist_ok=True)
    existing = [e for e in os.listdir(target)] if target.exists() else []
    placed = []
    lay = layout_from_dir(staged) if any(SCHEME_DIR.match(d) for _, ds, _ in os.walk(staged) for d in ds) else None
    if lay and lay['schemes']:
        for code, s in lay['schemes'].items():
            folder = _scheme_folder_for(code, existing) if mode == 'merge' else s['folder']
            for rel, p in s['files'].items():
                _place(target / folder, rel, p, mode)
                placed.append((code, rel))
        extras = [lay.get('opening'), lay.get('manifest'), lay.get('expected')]
        for p in extras:
            if p:
                sub = 'shared' if os.path.basename(p).startswith('Opening_Balances_') else ''
                (target / sub).mkdir(parents=True, exist_ok=True)
                if sub:
                    for old in (target / 'shared').glob('Opening_Balances_*.xlsx'):
                        old.unlink()
                shutil.copy2(p, target / sub / os.path.basename(p))
                placed.append(('shared', os.path.basename(p)))
    else:
        # loose files: they belong to the scheme the user picked (opening balances go to shared/)
        for dp, _, fns in os.walk(staged):
            for fn in fns:
                if fn.startswith('.'):
                    continue
                p = Path(dp) / fn
                rel = str(p.relative_to(staged)).replace(os.sep, '/')
                if re.match(r'^Opening_Balances_.*\.xlsx$', fn):
                    (target / 'shared').mkdir(parents=True, exist_ok=True)
                    for old in (target / 'shared').glob('Opening_Balances_*.xlsx'):
                        old.unlink()
                    shutil.copy2(p, target / 'shared' / fn)
                    placed.append(('shared', fn))
                    continue
                if fn in ('manifest.json', 'expected_results.json'):
                    shutil.copy2(p, target / fn)
                    placed.append(('shared', fn))
                    continue
                if not scheme_hint:
                    raise UploadError(f"Choose the scheme these files belong to ({fn})")
                folder = _scheme_folder_for(scheme_hint, existing)
                _place(target / folder, rel, p, 'merge')
                placed.append((scheme_hint, rel))
    if mode == 'merge':
        # files changed, so a manifest from an earlier upload no longer describes the set
        m = target / 'manifest.json'
        if m.exists() and not any(r == 'manifest.json' for _, r in placed):
            m.unlink()
    return placed


def _place(scheme_dir: Path, rel: str, src, mode):
    d, _ = classify(rel)
    if d is None:
        d2, _ = classify(os.path.basename(rel))
        if d2 is not None and d2.key in SINGLE:
            rel = os.path.basename(rel)
            d = d2
    if mode == 'merge' and d is not None and d.key in SINGLE and scheme_dir.exists():
        for old in scheme_dir.rglob('*'):
            if old.is_file():
                od, _ = classify(str(old.relative_to(scheme_dir)).replace(os.sep, '/'))
                if od is not None and od.key == d.key and str(old.relative_to(scheme_dir)) != rel:
                    old.unlink()
    dest = scheme_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)

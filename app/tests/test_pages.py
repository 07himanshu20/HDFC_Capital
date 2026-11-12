"""The dashboard page holds no fixed dates or quarter labels: every date it shows comes from the data
(meta.period, the parsed files), so the same page is right for any quarter that is uploaded."""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / 'trackfund' / 'static' / 'index.html'
MON = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec'
FIXED = re.compile(rf"\b\d{{1,2}}[ -]({MON})\b|\b({MON})[ -]\d{{1,2}}\b|\b20\d\d-\d\d-\d\d\b|\bQ[1-4]\b|\b[CF]Y ?\d\d(\d\d)?\b|\b20[12]\d\b")


def test_page_has_no_fixed_dates():
    hits = [f"line {n}: {m.group(0)!r} in …{line[max(0, m.start() - 50):m.end() + 30]}…"
            for n, line in enumerate(PAGE.read_text().split('\n'), 1) for m in FIXED.finditer(line)]
    assert not hits, '\n'.join(hits[:20])


def test_page_script_parses():
    """The page's inline scripts parse as one program (a syntax error or a name declared twice blanks the whole dashboard)."""
    import shutil
    import subprocess
    import pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    s = PAGE.read_text()
    js = '\n;\n'.join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", s, re.S))
    r = subprocess.run([node, '--check', '-'], input=js, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:1000]

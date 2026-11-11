# Q2 FY27 reconciled demo dataset — phase 1

```
python -m generator --seed 20260930 --out dataset/Q2FY27     # writes 160 source files + manifest + expected_results
python validation/run.py dataset/Q2FY27                      # rebuilds the books from the files; writes validation/validation_report.html/.json
```

Requires Python 3.11+, openpyxl, xlwt, xlrd, pdfplumber, mt-940, playwright with Chrome at /usr/bin/google-chrome (path in generator/base.py).

- `generator/core.py` — masters, the Section 6 event script, books, golden totals
- `generator/files1.py`, `files2.py` — native-format renderers
- `validation/run.py` — independent posting rules and rules R1–R20
- `docs/known_limitations.md` — decisions needed, differences from the brief, what is not built

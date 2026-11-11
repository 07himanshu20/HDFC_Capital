"""Chart of accounts used by the posting rules.  Codes 1xxx assets, 2xxx liabilities, 3xxx equity, 4xxx income, 5xxx expense."""
GL = {
    1100: ('Cash at bank', 'asset'), 1200: ('Investments at cost', 'asset'), 1210: ('Fair-value adjustment', 'asset'),
    1220: ('FX translation on INR assets', 'asset'), 1300: ('Accrued interest receivable', 'asset'), 1400: ('Capital call receivable', 'asset'),
    2100: ('Management fee payable', 'liability'), 2200: ('Accrued expenses', 'liability'), 2300: ('Distribution payable', 'liability'),
    2500: ('Withholding tax payable', 'liability'), 3100: ('Contributed capital', 'equity'), 3200: ('Distributions to investors', 'equity'),
    3900: ('Accumulated result', 'equity'), 4100: ('Interest income - cash coupon', 'income'), 4110: ('Interest income - PIK', 'income'),
    4200: ('Bank deposit interest', 'income'), 4500: ('Late-payment interest', 'income'), 4600: ('Unrealised fair-value gain/(loss)', 'income'),
    4700: ('FX translation gain/(loss)', 'income'), 5100: ('Management fee', 'expense'), 5200: ('Fund expenses', 'expense'),
    5210: ('Valuation fees', 'expense'), 5300: ('Bank charges', 'expense'), 5900: ('Organisation expenses', 'expense'),
}
TYPE = {1100: 'a', 1200: 'a', 1210: 'a', 1220: 'a', 1300: 'a', 1400: 'a', 2100: 'l', 2200: 'l', 2300: 'l', 2500: 'l', 3100: 'e', 3200: 'e', 3900: 'e'}
CAT = {4100: 'income', 4110: 'income', 4200: 'income', 4500: 'income', 4600: 'fv', 4700: 'fx', 5100: 'fee', 5200: 'expense', 5210: 'expense', 5300: 'expense'}

# Tally ledger name -> GL code.  In the product this is the mapping a user accepts at ingestion (see mapping table).
LEDGER_MAP = (('Interest on Bank', 4200), ('Bank Charges', 5300), ('Investment in', 1200), ('Fair Value Adjustment', 1210), ('Interest Accrued', 1300),
              ('Call Money', 1400), ('Management Fee Payable', 2100), ('Expenses Payable', 2200), ('Distribution Payable', 2300), ('WHT Payable', 2500),
              ('TDS Payable', 2500), ('Unit Capital', 3100), ('Distribution to Unitholders', 3200), ('Profit & Loss', 3900), ('PIK Interest', 4110),
              ('Interest on NCD', 4100), ('Late Payment Interest', 4500), ('Unrealised Gain', 4600), ('Management Fees', 5100), ('Valuation Fees', 5210),
              ('Trusteeship', 5200), ('Administration', 5200), ('RTA Fees', 5200), ('Legal', 5200), ('Audit', 5200), ('Organisation', 5200))


def led2gl(n):
    for k, g in LEDGER_MAP:
        if k in n:
            return g
    if 'Bank' in n and 'A/c' in n:
        return 1100
    raise KeyError(n)

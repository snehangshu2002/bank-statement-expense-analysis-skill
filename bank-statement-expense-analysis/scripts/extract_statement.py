#!/usr/bin/env python3
"""Extract transactions from bank statements (PDF, CSV, XLSX) of any bank.

Usage:
  python3 extract_statement.py STATEMENT [STATEMENT ...] -o transactions.json
      [--password PW] [--monthfirst] [--account-label FILE=LABEL ...]

How it works (bank-agnostic):
  1. Collect every table row (PDF tables via pdfplumber, falling back to text
     lines; CSV/XLSX rows directly).
  2. A transaction row is a row with a date cell and at least one money cell.
  3. Columns are identified by header keywords where a header exists, and by
     content otherwise (date column, money columns, longest-text column).
  4. Debit/credit direction is taken from the running balance: if the balance
     went down by the row's amount it is a debit, if up it is a credit. This
     works for separate Debit/Credit columns, a single Amount column with a
     DR/CR flag, and signed amounts alike.
  5. Every row is checked: previous balance - debit + credit == balance.

Exit code 0 = all accounts verified. 2 = at least one account has rows that
could not be verified (see "mismatch_rows" in the output). Do not analyse
unverified data without telling the user.
"""
import argparse, csv, datetime as dt, json, os, re, sys
from collections import Counter, defaultdict

MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
DATE_RES = [
    (re.compile(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b'), 'ymd'),
    (re.compile(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b'), 'dmy'),
    (re.compile(r'\b(\d{1,2})[-/. ]([A-Za-z]{3})[A-Za-z]*[-/., ]+(\d{4})\b'), 'dMy'),
    (re.compile(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2})\b'), 'dmy2'),
    (re.compile(r'\b(\d{1,2})[-/. ]([A-Za-z]{3})[A-Za-z]*[-/., ]+(\d{2})\b'), 'dMy2'),
    (re.compile(r'\b([A-Za-z]{3})[A-Za-z]*\.? (\d{1,2}),? (\d{4})\b'), 'Mdy'),
]
HEAD = {
    'date': ['txn date', 'transaction date', 'tran date', 'post date', 'posting date', 'value date', 'date'],
    'desc': ['description', 'narration', 'particulars', 'remarks', 'details', 'transaction details',
             'transaction remarks', 'transaction particulars'],
    'debit': ['debit', 'withdrawal', 'withdrawals', 'dr amount', 'paid out', 'money out', 'dr'],
    'credit': ['credit', 'deposit', 'deposits', 'cr amount', 'paid in', 'money in', 'cr'],
    'balance': ['balance', 'closing balance', 'running balance', 'available balance', 'bal'],
    'amount': ['amount', 'transaction amount', 'amount(inr)', 'amount (inr)', 'txn amount'],
    'type': ['type', 'dr/cr', 'cr/dr', 'dr / cr', 'debit/credit', 'txn type'],
}


def parse_date(s, monthfirst=False):
    if s is None:
        return None
    s = str(s).strip()
    if isinstance(s, str) and len(s) > 60:
        s = s[:60]
    for rx, kind in DATE_RES:
        m = rx.search(s)
        if not m:
            continue
        try:
            a, b, c = m.groups()
            if kind == 'ymd':
                y, mo, d = int(a), int(b), int(c)
            elif kind in ('dmy', 'dmy2'):
                d, mo, y = int(a), int(b), int(c)
                if monthfirst:
                    d, mo = mo, d
                if kind == 'dmy2':
                    y += 2000
            elif kind in ('dMy', 'dMy2'):
                d, mo, y = int(a), MONTHS.get(b.lower()[:3]), int(c)
                if kind == 'dMy2':
                    y += 2000
            else:
                mo, d, y = MONTHS.get(a.lower()[:3]), int(b), int(c)
            if not mo:
                continue
            return dt.date(y, mo, d)
        except (ValueError, TypeError):
            continue
    return None


MONEY_RE = re.compile(r'^\(?[-+]?\s*(?:rs\.?|inr|₹|\$|€|£)?\s*[-+]?\d[\d,]*(?:\.\d{1,2})?\)?\s*(cr|dr|c|d)?\.?$', re.I)


def parse_money(s):
    """Return (value, flag) or None. flag is 'CR', 'DR' or ''. Value is >= 0
    unless written with a minus sign or brackets."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return (float(s), '')
    t = str(s).replace('\n', ' ').strip()
    if not t or t in ('-', '--', 'NA', 'N/A'):
        return None
    if not MONEY_RE.match(t):
        return None
    flag = ''
    m = re.search(r'(cr|dr|c|d)\.?$', t, re.I)
    if m:
        flag = 'CR' if m.group(1).lower().startswith('c') else 'DR'
        t = t[:m.start()]
    neg = t.startswith('(') or '-' in t
    digits = re.sub(r'[^\d.]', '', t)
    if not digits or digits == '.':
        return None
    core = digits.replace('.', '')
    if '.' not in digits and len(core) >= 10:   # reference / account numbers
        return None
    v = float(digits)
    return (-v if neg else v, flag)


def clean(c):
    return '' if c is None else ' '.join(str(c).split())


def header_roles(row):
    roles = {}
    for i, c in enumerate(row):
        t = re.sub(r'[^a-z/() ]', ' ', clean(c).lower()).strip()
        t = re.sub(r'\s+', ' ', t)
        t = re.sub(r'\s*\(.*?\)\s*', ' ', t).strip() or t
        if not t:
            continue
        for role, keys in HEAD.items():
            if t in keys or any(t.startswith(k + ' ') or t.endswith(' ' + k) for k in keys if len(k) > 3):
                if role == 'date' and 'date' in roles.values():
                    continue  # keep the first date column (txn date)
                if role not in roles.values():
                    roles[i] = role
                break
    return roles if len(roles) >= 2 or 'balance' in roles.values() else {}


def read_rows(path, password=None):
    """Return (rows, full_text). rows = list of lists of cell strings."""
    ext = os.path.splitext(path)[1].lower()
    rows, text = [], ''
    if ext == '.pdf':
        import pdfplumber
        with pdfplumber.open(path, password=password) as pdf:
            for p in pdf.pages:
                t = p.extract_text() or ''
                text += t + '\n'
                got = False
                for tb in p.extract_tables():
                    for r in tb:
                        if r and any(c for c in r):
                            rows.append([clean(c) for c in r]); got = True
                if not got:
                    rows.extend(text_rows(t))
    elif ext in ('.csv', '.tsv', '.txt'):
        raw = open(path, 'r', encoding='utf-8-sig', errors='replace').read()
        text = raw[:5000]
        try:
            dialect = csv.Sniffer().sniff(raw[:4000], delimiters=',;\t|')
        except csv.Error:
            dialect = csv.excel
        for r in csv.reader(raw.splitlines(), dialect):
            if any(c.strip() for c in r):
                rows.append([clean(c) for c in r])
    elif ext in ('.xlsx', '.xlsm', '.xls'):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        for ws in wb.worksheets:
            for r in ws.iter_rows(values_only=True):
                if any(c is not None and str(c).strip() for c in r):
                    rows.append([c.strftime('%d/%m/%Y') if isinstance(c, (dt.date, dt.datetime)) else clean(c) for c in r])
        text = '\n'.join(' '.join(r) for r in rows[:40])
    else:
        sys.exit(f'Unsupported file type: {path}')
    return rows, text


def text_rows(page_text):
    """Fallback for PDFs without ruled tables: a line starting with a date opens
    a row; trailing money tokens are amounts/balance; other lines continue the
    description of the previous row."""
    out, cur = [], None
    for line in page_text.split('\n'):
        line = line.strip()
        if not line:
            continue
        head = line[:14]
        if parse_date(head) and re.match(r'^\d', line):
            toks = line.split()
            nums = []
            while toks and parse_money(toks[-1]) is not None and len(nums) < 3:
                nums.insert(0, toks.pop())
            if nums:
                cur = [toks[0], ' '.join(toks[1:])] + nums
                out.append(cur)
                continue
        if cur is not None and not re.search(r'page \d+|statement|balance|opening|closing', line, re.I):
            cur[1] = (cur[1] + ' ' + line).strip()
    return out


def account_id(text, path):
    m = re.search(r'(?:account|a/c|acct)\s*(?:no\.?|number|num)?\s*[:.\-]?\s*([Xx*\d][Xx*\d \-]{5,24}\d)', text, re.I)
    if m:
        d = re.sub(r'[^\dXx*]', '', m.group(1))
        return d[-4:]
    m = re.search(r'(\d{4})\D*$', os.path.splitext(os.path.basename(path))[0])
    return m.group(1) if m else os.path.splitext(os.path.basename(path))[0][:12]


IFSC = {'SBIN': 'SBI', 'PUNB': 'PNB', 'HDFC': 'HDFC', 'ICIC': 'ICICI', 'UTIB': 'Axis', 'KKBK': 'Kotak', 'BARB': 'BoB',
        'CNRB': 'Canara', 'UBIN': 'Union', 'INDB': 'IndusInd', 'YESB': 'Yes', 'IDFB': 'IDFC First', 'FDRL': 'Federal',
        'BKID': 'BoI', 'IDIB': 'Indian Bank', 'UCBA': 'UCO', 'IOBA': 'IOB', 'CBIN': 'Central Bank', 'MAHB': 'BoM',
        'PYTM': 'Paytm', 'AIRP': 'Airtel', 'AUBL': 'AU', 'RATN': 'RBL', 'IBKL': 'IDBI', 'SCBL': 'StanChart',
        'CITI': 'Citi', 'HSBC': 'HSBC', 'DBSS': 'DBS', 'BDBL': 'Bandhan', 'KARB': 'Karnataka', 'SIBL': 'South Indian'}


def bank_name(text):
    """Bank label for the account. Uses the branch IFSC code when printed
    (most reliable), then a bank name in the statement header."""
    m = re.search(r'IFSC[^\n]{0,20}?\b([A-Z]{4})0[A-Z0-9]{6}\b', text[:8000])
    if m:
        return IFSC.get(m.group(1), m.group(1))
    head = text[:1200]
    for pat, name in [('state bank of india', 'SBI'), ('punjab national', 'PNB'), ('hdfc bank', 'HDFC'),
                      ('icici bank', 'ICICI'), ('axis bank', 'Axis'), ('kotak', 'Kotak'), ('bank of baroda', 'BoB'),
                      ('canara bank', 'Canara'), ('union bank', 'Union'), ('indusind', 'IndusInd'), ('yes bank', 'Yes'),
                      ('idfc', 'IDFC First'), ('federal bank', 'Federal'), ('bank of india', 'BoI'),
                      ('indian bank', 'Indian Bank'), ('uco bank', 'UCO')]:
        if re.search(pat, head, re.I):
            return name
    return 'Bank'


def statement_period(text, monthfirst=False):
    """Period printed on the statement ("From 01-07-2026 to 30-09-2026"), if any.
    The last transaction date is not the end of the period when the final days had no activity."""
    for line in text[:12000].split('\n'):
        if not re.search(r'period|from|statement', line, re.I) or not re.search(r'\bto\b|-', line, re.I):
            continue
        m = re.search(r'(\d{1,2}[-/. ](?:\d{1,2}|[A-Za-z]{3,9})[-/., ]+\d{2,4})\s*(?:to|-|–|till|until)\s*(\d{1,2}[-/. ](?:\d{1,2}|[A-Za-z]{3,9})[-/., ]+\d{2,4})', line, re.I)
        if m:
            a, b = parse_date(m.group(1), monthfirst), parse_date(m.group(2), monthfirst)
            if a and b and a <= b:
                return a.isoformat(), b.isoformat()
    return None


def extract_file(path, password=None, monthfirst=False):
    rows, text = read_rows(path, password)
    roles_by_width, cand = {}, []
    for r in rows:
        hr = header_roles(r)
        if hr and not any(parse_date(c, monthfirst) and parse_money(x) for c in r[:2] for x in r[2:]):
            old = roles_by_width.get(len(r), {})
            if len(hr) >= len(old):
                roles_by_width[len(r)] = hr
            continue
        di = next((i for i, c in enumerate(r[:4]) if c and len(c) <= 40 and parse_date(c, monthfirst)), None)
        if di is None:
            continue
        monies = {i: parse_money(c) for i, c in enumerate(r) if i != di}
        monies = {i: v for i, v in monies.items() if v is not None and not parse_date(r[i], monthfirst)}
        if not monies:
            continue
        cand.append((r, di, monies))
    if not cand:
        return None, text
    width = Counter(len(c[0]) for c in cand).most_common(1)[0][0]
    cand = [c for c in cand if len(c[0]) == width]
    roles = roles_by_width.get(width, {})
    inv = {v: k for k, v in roles.items()}
    n = len(cand)
    money_cols = [i for i in range(width) if sum(1 for c in cand if i in c[2]) >= max(1, 0.15 * n)]
    type_col = inv.get('type')
    if type_col is None:
        for i in range(width):
            vals = [c[0][i].upper().strip('. ') for c in cand if c[0][i]]
            if vals and sum(v in ('DR', 'CR', 'D', 'C', 'DEBIT', 'CREDIT') for v in vals) >= 0.8 * len(vals) and len(vals) >= 0.5 * n:
                type_col = i
    bal_col = inv.get('balance')
    if bal_col is None and money_cols:
        full = [i for i in money_cols if sum(1 for c in cand if i in c[2]) >= 0.9 * n]
        bal_col = full[-1] if full and len(money_cols) > 1 else None
    amt_cols = [i for i in money_cols if i != bal_col]
    desc_col = inv.get('desc')
    if desc_col is None:
        lens = {i: sum(len(c[0][i]) for c in cand) for i in range(width)
                if i not in money_cols and i != type_col and i != cand[0][1]}
        desc_col = max(lens, key=lens.get) if lens else None

    recs = []
    for r, di, monies in cand:
        amts = [(i, monies[i]) for i in amt_cols if i in monies and abs(monies[i][0]) > 0]
        bal = None
        if bal_col is not None and bal_col in monies:
            v, f = monies[bal_col]
            bal = -abs(v) if f == 'DR' else v
        t = r[type_col].upper()[:1] if type_col is not None and r[type_col] else ''
        desc = r[desc_col] if desc_col is not None else ' '.join(
            x for i, x in enumerate(r) if i not in money_cols and i != di and i != type_col)
        recs.append(dict(date=parse_date(r[di], monthfirst), description=desc, amts=amts, balance=bal, flag=t))

    def match_rate(seq):
        ok = tot = 0
        for a, b in zip(seq, seq[1:]):
            if a['balance'] is None or b['balance'] is None:
                continue
            tot += 1
            d = round(b['balance'] - a['balance'], 2)
            if any(abs(abs(d) - abs(v[0])) < 0.011 for _, v in b['amts']):
                ok += 1
        return ok / tot if tot else 0

    has_bal = sum(1 for x in recs if x['balance'] is not None) >= 0.9 * len(recs)
    if has_bal and match_rate(recs[::-1]) > match_rate(recs) + 0.2:
        recs = recs[::-1]
    elif not has_bal and len(recs) > 1 and recs[0]['date'] > recs[-1]['date']:
        recs = recs[::-1]

    # learn which column means debit / credit from rows the balance explains
    votes = defaultdict(Counter)
    for a, b in zip(recs, recs[1:]):
        if a['balance'] is None or b['balance'] is None:
            continue
        d = round(b['balance'] - a['balance'], 2)
        for i, v in b['amts']:
            if abs(abs(d) - abs(v[0])) < 0.011:
                votes[i]['debit' if d < 0 else 'credit'] += 1
    col_dir = {}
    for i in amt_cols:
        if roles.get(i) in ('debit', 'credit'):
            col_dir[i] = roles[i]
        elif votes[i] and votes[i].most_common(1)[0][1] >= 0.9 * sum(votes[i].values()) and len(amt_cols) > 1:
            col_dir[i] = votes[i].most_common(1)[0][0]

    signed = len(amt_cols) == 1 and any(v[0] < 0 for x in recs for _, v in x['amts'])

    def by_rule(x):
        """Direction without using the balance."""
        if not x['amts']:
            return None
        i, (v, f) = x['amts'][0]
        if x['flag'] in ('D', 'C'):
            return (abs(v), 0.0) if x['flag'] == 'D' else (0.0, abs(v))
        if f:
            return (abs(v), 0.0) if f == 'DR' else (0.0, abs(v))
        if i in col_dir:
            return (abs(v), 0.0) if col_dir[i] == 'debit' else (0.0, abs(v))
        if signed:   # one Amount column where money out is written with a minus sign
            return (abs(v), 0.0) if v < 0 else (0.0, abs(v))
        return None

    out, mism, prev = [], [], None
    for k, x in enumerate(recs):
        deb = cred = None
        if prev is not None and x['balance'] is not None:
            d = round(x['balance'] - prev, 2)
            hit = [v for _, v in x['amts'] if abs(abs(d) - abs(v[0])) < 0.011]
            if hit:
                deb, cred = (abs(d), 0.0) if d < 0 else (0.0, abs(d))
        verified = deb is not None
        if deb is None:
            g = by_rule(x)
            if g:
                deb, cred = g
                if prev is not None and x['balance'] is not None:
                    mism.append(k)
            elif x['amts']:
                deb, cred = abs(x['amts'][0][1][0]), 0.0
                mism.append(k)
            else:
                continue
        out.append(dict(date=x['date'].isoformat(), description=x['description'], debit=round(deb, 2),
                        credit=round(cred, 2), balance=x['balance'], verified=verified or prev is None))
        if x['balance'] is not None:
            prev = x['balance']
    info = dict(bank=bank_name(text), id=account_id(text, path), period=statement_period(text, monthfirst), has_balance=has_bal,
                mismatch_rows=len(mism), rows=len(out), source=os.path.basename(path),
                columns=dict(date='auto', description=desc_col, amounts=amt_cols, balance=bal_col, type=type_col,
                             header_roles={str(k): v for k, v in roles.items()}))
    return dict(info=info, tx=out, mism=[out[i] if i < len(out) else None for i in mism[:10]]), text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='+')
    ap.add_argument('-o', '--out', default='transactions.json')
    ap.add_argument('--password')
    ap.add_argument('--monthfirst', action='store_true', help='read 03/07/2026 as March 7 (US style)')
    ap.add_argument('--account-label', action='append', default=[], metavar='FILE=LABEL',
                    help='force the account label for a file, e.g. stmt.pdf="HDFC 1234"')
    a = ap.parse_args()
    forced = dict(x.split('=', 1) for x in a.account_label)
    accounts, problems = {}, False
    for f in a.files:
        res, _ = extract_file(f, a.password, a.monthfirst)
        if not res:
            print(f'!! {f}: no transaction rows found. If it is a scanned image, OCR it first; '
                  f'if it is password protected pass --password.')
            problems = True
            continue
        label = forced.get(os.path.basename(f)) or forced.get(f) or f"{res['info']['bank']} ··{res['info']['id']}"
        acc = accounts.setdefault(label, dict(label=label, sources=[], tx=[], mismatch_rows=0, has_balance=True))
        acc['sources'].append(res['info'])
        acc['mismatch_rows'] += res['info']['mismatch_rows']
        acc['has_balance'] &= res['info']['has_balance']
        acc['tx'].append(res['tx'])
        if res['info']['mismatch_rows']:
            print(f"!! {f}: {res['info']['mismatch_rows']} row(s) not explained by the running balance, e.g.")
            for m in res['mism'][:5]:
                print('    ', m)
    out_accounts, out_tx = [], []
    for label, acc in accounts.items():
        # merge several statements of one account; drop rows repeated in overlapping date ranges
        parts = sorted(acc['tx'], key=lambda t: (t[0]['date'], -len(t)))
        merged = []
        for part in parts:
            if not merged:
                merged = list(part); continue
            last = merged[-1]['date']
            first_new = part[0]['date']
            if first_new > last:
                merged += part; continue
            seen = Counter((t['date'], t['description'], t['debit'], t['credit'], t['balance']) for t in merged)
            for t in part:
                k = (t['date'], t['description'], t['debit'], t['credit'], t['balance'])
                if seen[k] > 0:
                    seen[k] -= 1
                else:
                    merged.append(t)
            merged.sort(key=lambda t: t['date'])  # stable: keeps statement order within a day
        # final balance walk on the merged account
        bad, prev = 0, None
        for t in merged:
            if prev is not None and t['balance'] is not None and abs(round(prev - t['debit'] + t['credit'] - t['balance'], 2)) > 0.011:
                bad += 1
            if t['balance'] is not None:
                prev = t['balance']
        first = merged[0]
        opening = None if first['balance'] is None else round(first['balance'] + first['debit'] - first['credit'], 2)
        closing = next((t['balance'] for t in reversed(merged) if t['balance'] is not None), None)
        verified = acc['has_balance'] and bad == 0 and acc['mismatch_rows'] == 0
        problems |= not verified
        pers = [x['period'] for x in acc['sources'] if x.get('period')]
        p_start = min([merged[0]['date']] + [p[0] for p in pers])
        p_end = max([merged[-1]['date']] + [p[1] for p in pers])
        out_accounts.append(dict(label=label, start=p_start, end=p_end, first_txn=merged[0]['date'],
                                 last_txn=merged[-1]['date'], opening=opening,
                                 closing=closing, rows=len(merged), debits=round(sum(t['debit'] for t in merged), 2),
                                 credits=round(sum(t['credit'] for t in merged), 2),
                                 debit_count=sum(1 for t in merged if t['debit']), credit_count=sum(1 for t in merged if t['credit']),
                                 verified=verified, balance_breaks=bad, sources=acc['sources']))
        for i, t in enumerate(merged):
            out_tx.append(dict(account=label, seq=i, **{k: t[k] for k in ('date', 'description', 'debit', 'credit', 'balance')}))
    json.dump(dict(accounts=out_accounts, transactions=out_tx), open(a.out, 'w'), ensure_ascii=False, indent=1)
    print(f'\nWrote {a.out}')
    for x in out_accounts:
        print(f"  {x['label']}: {x['start']} to {x['end']} | {x['rows']} rows | opening {x['opening']} | "
              f"debits {x['debits']} ({x['debit_count']}) | credits {x['credits']} ({x['credit_count']}) | "
              f"closing {x['closing']} | " + ('VERIFIED' if x['verified'] else
              'NOT VERIFIED (no running balance column: totals cannot be proven)' if x['closing'] is None else 'NOT VERIFIED'))
    print('\nCompare the counts and totals above with the summary printed on each statement, if it has one.')
    sys.exit(2 if problems else 0)


if __name__ == '__main__':
    main()

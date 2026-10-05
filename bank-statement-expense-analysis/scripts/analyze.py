#!/usr/bin/env python3
"""Draft-classify extracted transactions and list what to ask the user.

Usage:
  python3 analyze.py transactions.json -o classified.json
      [--owner "FULL NAME" ...] [--overrides overrides.json]
      [--periods month|income-cycle] [--max-questions 8]

Every transaction gets exactly one bucket:
  EXPENSE  money actually spent
  SELF     moved between the user's own accounts, cards, wallets, investments
  REVIEW   cannot be classified with confidence (never counted as expense)
  PASS     received and paid back / lent and returned / purchase fully refunded
  INCOME   earned income: salary, business receipts, professional fees, pension
  INFLOW   other money in: from individuals, interest, dividends, refunds

The draft is rule-based and deliberately cautious. Read the printed groups,
ask the user about the listed questions, put the answers in overrides.json and
run again. overrides.json is a list of rules applied in order (later wins):
  [{"match": "RAVI KUMAR", "bucket": "EXPENSE", "category": "Rent", "label": "Flat rent"},
   {"match": "ACME", "direction": "credit", "bucket": "INCOME", "category": "Business receipts"},
   {"match": "ATM CASH", "date": "2025-04-05", "amount": 10000, "bucket": "PASS", "category": "Cash for a friend"}]
Rule keys: match (case-insensitive text found in description, counterparty or
label) or regex; optional date (YYYY-MM-DD), amount, direction (debit|credit),
account; and what to set: bucket, category, label.
"""
import argparse, datetime as dt, json, re, sys
from collections import defaultdict, Counter

BUCKETS = ('EXPENSE', 'SELF', 'REVIEW', 'PASS', 'INCOME', 'INFLOW')

# (regex on UPPERCASE description with spaces removed, merchant label, category). First match wins.
MERCHANTS = [
    (r'SWIGGYINSTAMART|INSTAMART', 'Swiggy Instamart', 'Groceries'),
    (r'SWIGGY', 'Swiggy', 'Food & Dining'), (r'ZOMATO|ETERNAL', 'Zomato', 'Food & Dining'),
    (r'DOMINO|PIZZAHUT|MCDONALD|BURGERK|KFC|SUBWAY|STARBUCKS|HALDIRAM|WOWMOMO|BASKINROBBINS|CHAAYOS|BARBEQUE', 'Restaurant chain', 'Food & Dining'),
    (r'ZEPTO|COMMODUM', 'Zepto', 'Groceries'), (r'BLINKIT|GROFERS', 'Blinkit', 'Groceries'),
    (r'BIGBASKET|BBNOW|BBDAILY', 'BigBasket', 'Groceries'), (r'DMART|AVENUESUPERMART', 'DMart', 'Groceries'),
    (r'JIOMART|RELIANCEFRESH|RELIANCESMART|SMARTPO|SMARTBAZAAR|MOREREAIL|SPENCERS|LICIOUS|COUNTRYDELIGHT', 'Grocery store', 'Groceries'),
    (r'FLIPKART', 'Flipkart', 'Shopping'), (r'AMAZONPRIME|PRIMEVIDEO', 'Amazon Prime', 'Subscriptions'),
    (r'AMAZON|AMZN', 'Amazon', 'Shopping'), (r'MYNT', 'Myntra', 'Shopping'), (r'MEESHO', 'Meesho', 'Shopping'),
    (r'AJIO|NYKAA|TATACLIQ|SNAPDEAL|LENSKART|DECATHLON|IKEA|CROMA|RELIANCEDIGITAL|RELIANCETRENDS|PANTALOONS|WESTSIDE|ZUDIO|CAMPUSA|CAMPUSSHOE|BATA|SHOPPERSSTOP|FIRSTCRY|PEPPERFRY', 'Retail store', 'Shopping'),
    (r'NETFLIX', 'Netflix', 'Subscriptions'), (r'SPOTIFY', 'Spotify', 'Subscriptions'),
    (r'HOTSTAR', 'JioHotstar', 'Subscriptions'), (r'ZEE5|ZEEENTE', 'ZEE5', 'Subscriptions'),
    (r'SONYLIV|YOUTUBE|GOOGLEPLAY|PLAYSTORE|GOOGLEONE|APPLE\.COM|APPLEMEDIA|ITUNES|AUDIBLE|KINDLE|MICROSOFT|ADOBE|CANVA|NOTION|LINKEDIN|CHATGPT|OPENAI|ANTHROPIC|CLAUDE|GITHUB|DROPBOX|GAANA|JIOSAAVN', 'Digital subscription', 'Subscriptions'),
    (r'UBER', 'Uber', 'Transport'), (r'OLACABS|OLAMONEY|ANITECH|\bOLA\b', 'Ola', 'Transport'), (r'RAPIDO|ROPPEN', 'Rapido', 'Transport'),
    (r'IRCTC', 'IRCTC', 'Travel'), (r'INDIANR|UTSMOBILE|IRUTS|RAILWAY', 'Indian Railways', 'Transport'),
    (r'METRO|DMRC|BMRC|CMRL|AAMARKO', 'Metro', 'Transport'), (r'FASTAG|NETC|TOLL', 'FASTag / toll', 'Transport'),
    (r'REDBUS|MAKEMYTRIP|GOIBIBO|YATRA|CLEARTRIP|EASEMYTRIP|IXIGO|INDIGO|AIRINDIA|VISTARA|SPICEJET|AKASAAIR|OYO|AIRBNB|BOOKING\.COM|AGODA', 'Travel booking', 'Travel'),
    (r'HPCL|BPCL|IOCL|INDIANOIL|BHARATPETRO|HINDUSTANPETRO|PETROL|FUEL|SHELL|NAYARA', 'Fuel station', 'Fuel'),
    (r'AIRTEL|RELIANCEJIO|JIO@|JIOPREPAID|JIOFIBER|VODAFONE|\bVI\b|BSNL|RECHARGE|EURONET|ACTFIBER|HATHWAY|TATAPLAY|DISHTV|D2H', 'Mobile / internet / DTH', 'Bills & Utilities'),
    (r'ELECTRIC|BESCOM|MSEDCL|WBSEDCL|CESC|TORRENTPOWER|TATAPOWER|ADANIELEC|BSES|DISCOM|GASBILL|INDANE|HPGAS|BHARATGAS|MAHANAGARGAS|WATERBILL|BBPS|BILLPAY|UTILITY', 'Utility bill', 'Bills & Utilities'),
    (r'BOOKMYSHOW|PVR|INOX|CINEPOLIS|DISTRICT|ORBGEN|DREAM11|MPL|STEAMGAMES|PLAYSTATION', 'Entertainment', 'Entertainment'),
    (r'PHARM|APOLLO|MEDPLUS|NETMEDS|1MG|TATA1MG|PRACTO|HOSPITAL|CLINIC|DIAGNOSTIC|LALPATH|THYROCARE|MEDICAL|NIVAMED', 'Pharmacy / medical', 'Healthcare'),
    (r'UDEMY|COURSERA|UNACADEMY|BYJU|PHYSICSWALLAH|UPGRAD|SCALER|SCHOOL|COLLEGE|UNIVERSITY|TUITION|EXAMFEE', 'Education', 'Education'),
    (r'\bLIC\b|LICOFINDIA|HDFCLIFE|ICICIPRU|SBILIFE|MAXLIFE|STARHEALTH|NIVABUPA|ACKO|DIGITINSUR|INSURANCE|POLICYBAZAAR', 'Insurance', 'Insurance'),
]
GENERIC = {'Restaurant chain', 'Grocery store', 'Retail store', 'Digital subscription', 'Travel booking', 'Fuel station',
           'Mobile / internet / DTH', 'Utility bill', 'Entertainment', 'Pharmacy / medical', 'Education', 'Insurance'}
INVEST = r'ZERODHA|GROWW|UPSTOX|KUVERA|INDMONEY|SMALLCASE|ANGELONE|5PAISA|PAYTMMONEY|MUTUALFUND|\bSIP\b|BSELIMITED|BSESTAR|ICCL|NSECLEARING|\bNPS\b|\bPPF\b|SUKANYA|RDINSTAL|FIXEDDEPOSIT|TOFD|TORD|SWEEPTRF|SWEEPTO|CAMSPAY|KFINTECH|SGB'
CARD_PAY = r'CREDCLUB|\bCRED\b|CREDITCARD|CCPAYMENT|CCBILL|CARDPAYMENT|CARDBILL|SBICARD|HDFCCARD|ICICICARD|AXISCARD|AMEX|ONECARD|BILLDESK.*CARD'
WALLET = r'UPILITE|ADDMONEY|WALLETLOAD|PAYTMWALLET|AMAZONPAYBALANCE|MOBIKWIK|FREECHARGE'
EMI = r'\bEMI\b|LOAN|NACH|ACHDR|ACH-DR|\bECS\b|BAJAJFIN|HOMECREDIT|KREDITBEE|MONEYVIEW|NAVI|FINSERV|FINANCE|\bFIN\b|FINCORP|CAPITAL'
QR_VPA = re.compile(r'^(q\d|paytmqr|paytm[.\-]|bharatpe|vyapar|boism|getepay|ombk|gpay-\d|bqr|pinelabs|mswipe|razorpay|rzp|cashfree|payu|ccavenue|billdesk|sbipmopad|okbiz|eazypay|hdfcbankltd\.|yespay\.|ibkpos|pos\.)', re.I)
STOP = {'UPI', 'DR', 'CR', 'P2A', 'P2M', 'P2P', 'P2V', 'IMPS', 'NEFT', 'RTGS', 'MMT', 'INB', 'MB', 'MOB', 'TRANSFER', 'TFR', 'DEP',
        'WDL', 'PAYMENT', 'PAY', 'FROM', 'TO', 'BY', 'BATCHID', 'NA', 'NO', 'REMARKS', 'UPIINTENT', 'COLLECT', 'DEBIT', 'CREDIT',
        'ACHDR', 'ACHCR', 'CEMTEX', 'ECOM', 'POS', 'PUR', 'CHRG', 'PURCH', 'ATM', 'OTHPG', 'INF', 'INFT', 'BIL', 'ONL', 'IB', 'MBK',
        'SENT', 'USING', 'PAYTM', 'GPAY', 'PHONEPE', 'BHIM', 'OTHER', 'BANK', 'A/C', 'AC', 'REF', 'TXN', 'ID'}


def keyof(name):
    return re.sub(r'[^A-Z]', '', name.upper())[:24]


def parse_counterparty(desc):
    """Return dict(channel, name, key, vpa, ref, remark). Works on the common
    Indian narration styles; names may be truncated by the bank."""
    d = re.sub(r'^(DEP TFR|WDL TFR|TO TRANSFER|BY TRANSFER|TRANSFER TO|TRANSFER FROM)[ -]*', '', desc.strip(), flags=re.I)
    d = re.sub(r'\s\d{10,}\s+AT\s+\d+\s+[A-Z .]+$', '', d)
    U = d.upper()
    ch = ('UPI' if re.search(r'\bUPI\b|UPI[/-]|@', U) else 'IMPS' if 'IMPS' in U or 'MMT/' in U else 'NEFT' if 'NEFT' in U else
          'RTGS' if 'RTGS' in U else 'ACH' if re.search(r'ACH|NACH|\bECS\b|CEMTEX', U) else
          'ATM' if re.search(r'ATM (WDL|CASH)|ATM CASH|CASH WDL|NWD|AWB|ATW', U) else
          'CARD' if re.search(r'\bPOS\b|ECOM|\bPUR\b|PURCH|VISA|MASTERCARD|RUPAY|DEBIT CARD', U) else
          'CHEQUE' if re.search(r'CHQ|CHEQUE|CLG|CLEARING', U) else
          'CASHDEP' if re.search(r'CASH DEP|BY CASH|CDM|CASH DEPOSIT', U) else 'OTHER')
    ref = (re.search(r'(?<!\d)\d{12}(?!\d)', d) or [None])[0] if ch in ('UPI', 'IMPS') else None
    vpa = (re.search(r'[\w.\-]{2,}@[\w.]*', d) or [''])[0]
    name = remark = ''
    if ch == 'UPI' and d.count('/') >= 3:
        segs = [s.strip() for s in d.split('/')]
        i = next((k for k, s in enumerate(segs) if re.fullmatch(r'\d{9,}', s.replace(' ', ''))), None)
        rest = segs[i + 1:] if i is not None else [s for s in segs if s.upper() not in STOP]
        rest = [s for s in rest if s]
        if rest:
            name = rest[0]
            if len(rest) >= 3 and not vpa:
                vpa = rest[2].replace(' ', '')
            elif len(rest) >= 3 and '@' in rest[2]:
                vpa = rest[2].replace(' ', '')
            remark = rest[3] if len(rest) >= 4 else ''
            if '@' in name and len(rest) > 1:      # style: UPI/ref/remark/vpa/bank
                name, remark = name.split('@')[0], ''
    else:
        toks = [t.strip() for t in re.split(r'[/\-*|:]', d)]
        good = [t for t in toks if re.search(r'[A-Za-z]{3}', t) and '@' not in t and t.upper() not in STOP
                and not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}', t.upper().replace(' ', ''))
                and not re.search(r'\d{4,}', t)]
        if ch in ('CARD', 'ACH', 'OTHER', 'ATM', 'CHEQUE', 'CASHDEP') or not good:
            words = [w for w in re.split(r'[\s*/\\:]+', d) if re.search(r'[A-Za-z]{2}', w) and not re.search(r'\d{3,}', w)
                     and w.upper() not in STOP]
            name = ' '.join(words[:4])
        else:
            name = good[0]
            remark = good[-1] if len(good) > 1 else ''
    name = ' '.join(name.split())
    return dict(channel=ch, name=name, key=keyof(name), vpa=vpa, ref=ref, remark=remark)


def is_owner(key, owners):
    if len(key) < 5:
        return False
    for o in owners:
        joined, first = keyof(o), keyof(o.split()[0])
        if joined.startswith(key) or key.startswith(first) or (first.startswith(key) and len(key) >= 6):
            return True
    return False


def classify(t, owners):
    """Return (label, category, bucket, hint) for one transaction, ignoring pairing rules."""
    U = t['description'].upper()
    N = re.sub(r'\s+', '', U)
    out = t['debit'] > 0
    cp, ch = t['cp'], t['cp']['channel']
    name = cp['name'] or t['description'][:30]
    if is_owner(cp['key'], owners):
        return ('Own account', 'Self Transfer', 'SELF', 'counterparty carries the account holder name')
    if re.search(INVEST, N):
        return (name, 'Investments/Savings', 'SELF', 'money moved to/from own investment; confirm')
    if re.search(CARD_PAY, N) and out:
        return (name, 'Credit card bill', 'SELF', 'card bill payment: the spending is on the card statement, not here')
    if re.search(WALLET, N) and out:
        return (name, 'Wallet top-up', 'SELF', 'wallet load: spending from the wallet is not itemised')
    if not out:
        if re.search(r'SALARY|\bSAL\b|PAYROLL|STIPEND|WAGES', U):
            return (name, 'Salary', 'INCOME', '')
        if re.search(r'PENSION', U):
            return (name, 'Pension', 'INCOME', '')
        if re.search(r'INTEREST|\bINTT?\b|INT\.? ?PD|INT\.? ?CR', U):
            return ('Bank interest', 'Interest', 'INFLOW', '')
        if re.search(r'DIVIDEND|\bDIV\b', U) or (ch == 'ACH' and re.search(r'LTD|LIMITED', U) and t['credit'] < 5000):
            return (name, 'Dividend', 'INFLOW', '')
        if re.search(r'CASHBACK|CASHBA|REWARD|REFUND|REVERSAL|\bREV\b|RETURN', U):
            return (name, 'Refund / cashback', 'INFLOW', '')
        if re.search(r'TAX REFUND|ITDTAX|CPC', U):
            return ('Income tax refund', 'Tax refund', 'INFLOW', '')
        for rx, m, c in MERCHANTS:
            if re.search(rx, N):
                return (m, 'Refund / cashback', 'INFLOW', 'credit from a merchant')
        if ch == 'CASHDEP':
            return ('Cash deposit', 'Cash deposit', 'INFLOW', 'source of cash unknown; ask')
        if ch in ('NEFT', 'RTGS', 'ACH', 'CHEQUE', 'OTHER'):
            return (name, 'Bank transfer received', 'INFLOW', 'possible income; see income candidates')
        return (name, 'Received from individuals', 'INFLOW', '')
    if ch == 'ATM' or cp['key'] == 'ATM':
        return ('ATM cash withdrawal', 'Cash Withdrawal', 'EXPENSE', 'cash: what it bought is unknown')
    for rx, m, c in MERCHANTS:
        hit = re.search(rx, N)
        if hit:
            if m in GENERIC:      # generic group label: name the brand that actually matched
                m = hit.group(0).replace('\\', '').strip('.@').title()
            return (m, c, 'EXPENSE', '')
    if re.search(r'\bRENT\b', U):
        return (name, 'Rent', 'EXPENSE', 'remark says rent')
    if re.search(EMI, N) and ch in ('ACH', 'OTHER', 'NEFT'):
        return (name, 'Loan EMI', 'EXPENSE', 'auto-debit: confirm it is a loan and not insurance or a SIP')
    if re.search(r'CHARGES|CHRG|CHGS|\bAMC\b|SMS ALERT|\bGST\b|MIN BAL|\bFEE\b|PENALTY|CARD AMC', U) and ch != 'UPI':
        return ('Bank charges', 'Bank Charges', 'EXPENSE', '')
    if re.search(r'TDS|INCOME TAX|ADVANCE TAX|\bGST\b|CBDT|CHALLAN', U):
        return (name, 'Taxes', 'EXPENSE', '')
    if ch == 'CARD':
        return (name, 'Other', 'EXPENSE', 'card purchase, merchant not recognised')
    if ch == 'UPI' and cp['vpa'] and QR_VPA.match(cp['vpa']):
        return (name + ' (merchant QR)', 'Local shops (QR)', 'EXPENSE', 'shop QR code: what was bought is unknown')
    if ch == 'CHEQUE':
        return (name, 'Review Required', 'REVIEW', 'cheque: payee purpose unknown')
    return (name, 'Review Required', 'REVIEW', 'payment to an individual or unrecognised payee')


def apply_overrides(tx, rules):
    used = Counter()
    for n, r in enumerate(rules):
        if r.get('bucket') and r['bucket'] not in BUCKETS:
            sys.exit(f"overrides rule {n}: bucket must be one of {BUCKETS}")
        for t in tx:
            hay = ' | '.join([t['description'], t['cp']['name'], t['label']]).upper()
            if 'match' in r and r['match'].upper() not in hay:
                continue
            if 'regex' in r and not re.search(r['regex'], hay, re.I):
                continue
            if 'date' in r and t['date'] != r['date']:
                continue
            if 'amount' in r and abs((t['debit'] or t['credit']) - float(r['amount'])) > 0.011:
                continue
            if 'direction' in r and ((r['direction'] == 'debit') != (t['debit'] > 0)):
                continue
            if 'account' in r and r['account'].upper() not in t['account'].upper():
                continue
            for k in ('bucket', 'category', 'label'):
                if k in r:
                    t[k] = r[k]
            t['hint'] = 'set by user answer'
            used[n] += 1
    for n, r in enumerate(rules):
        if not used[n]:
            print(f'!! overrides rule {n} matched nothing: {r}')
    return used


def month_periods(start, end):
    out, d = [], dt.date(start.year, start.month, 1)
    while d <= end:
        nxt = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        s, e = max(d, start), min(nxt - dt.timedelta(days=1), end)
        partial = s != d or e != nxt - dt.timedelta(days=1)
        out.append(dict(name=d.strftime('%b %Y') + (' (partial)' if partial else ''), start=s.isoformat(), end=e.isoformat()))
        d = nxt
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('transactions')
    ap.add_argument('-o', '--out', default='classified.json')
    ap.add_argument('--owner', action='append', default=[], help='account holder name as printed on the statement (repeatable)')
    ap.add_argument('--overrides')
    ap.add_argument('--periods', choices=['month', 'income-cycle'], default='month')
    ap.add_argument('--max-questions', type=int, default=8)
    ap.add_argument('--currency', default='₹')
    ap.add_argument('--locale', default='en-IN')
    a = ap.parse_args()
    src = json.load(open(a.transactions))
    tx = src['transactions']
    for t in tx:
        t['cp'] = parse_counterparty(t['description'])
        t['label'], t['category'], t['bucket'], t['hint'] = classify(t, a.owner)
    D = lambda t: dt.date.fromisoformat(t['date'])
    amt = lambda t: t['debit'] or t['credit']

    # --- self transfers proven by a matching leg in another account -------------------------
    debits = [t for t in tx if t['debit'] > 0]
    credits = [t for t in tx if t['credit'] > 0]
    paired = set()
    for want_ref in (True, False):
        for d in debits:
            if id(d) in paired:
                continue
            for c in credits:
                if id(c) in paired or c['account'] == d['account'] or abs(c['credit'] - d['debit']) > 0.011:
                    continue
                same_ref = d['cp']['ref'] and d['cp']['ref'] == c['cp']['ref']
                near = abs((D(c) - D(d)).days) <= 1 and d['debit'] >= 100 and d['bucket'] in ('SELF', 'REVIEW') and c['bucket'] in ('SELF', 'INFLOW')
                if (want_ref and same_ref) or (not want_ref and near):
                    for x in (d, c):
                        x.update(label='Own account', category='Self Transfer', bucket='SELF',
                                 hint='matching leg found in ' + (c if x is d else d)['account'])
                        paired.add(id(x))
                    break
    self_unpaired = [t for t in tx if t['bucket'] == 'SELF' and t['category'] == 'Self Transfer' and id(t) not in paired]

    # --- pass-through: same counterparty, same amount, in and out within 10 days ---------------
    by_key = defaultdict(list)
    for t in tx:
        if t['bucket'] in ('REVIEW', 'INFLOW', 'EXPENSE') and t['cp']['key'] and amt(t) >= 500:
            by_key[t['cp']['key']].append(t)
    for key, rows in by_key.items():
        ins = [t for t in rows if t['credit'] > 0]
        outs = [t for t in rows if t['debit'] > 0]
        for c in ins:
            for d in outs:
                if d.get('_p') or c.get('_p') or abs(c['credit'] - d['debit']) > 0.011 or abs((D(c) - D(d)).days) > 10:
                    continue
                merchant = d['bucket'] == 'EXPENSE'
                if merchant and D(c) < D(d):
                    continue
                cat = 'Refunded purchase' if merchant else 'Pass-through (same amount in and out)'
                for x in (c, d):
                    x.update(category=cat, bucket='PASS', hint='same counterparty and amount in and out; confirm', _p=1)
    # cash drawn the day someone sent the identical amount
    for d in [t for t in tx if t['category'] == 'Cash Withdrawal']:
        for c in credits:
            if c['bucket'] == 'INFLOW' and c['date'] == d['date'] and abs(c['credit'] - d['debit']) < 0.011 and d['debit'] >= 500:
                for x in (c, d):
                    x.update(category='Review Required', bucket='REVIEW',
                             hint='cash withdrawn the same day an identical amount was received: cash for someone else?')
    for t in tx:
        t.pop('_p', None)

    # --- income candidates: any regular or large non-individual credit -------------------------
    inc = defaultdict(list)
    for t in credits:
        if t['bucket'] in ('INFLOW', 'INCOME') and t['category'] in ('Bank transfer received', 'Salary', 'Pension', 'Cash deposit'):
            inc[t['cp']['key'] or t['label']].append(t)
    cand = []
    for k, rows in inc.items():
        months = {t['date'][:7] for t in rows}
        tot = sum(t['credit'] for t in rows)
        cand.append((tot, k, rows, months))
    cand.sort(key=lambda x: -x[0])
    total_in = sum(t['credit'] for t in credits if t['bucket'] not in ('SELF', 'PASS')) or 1
    for tot, k, rows, months in cand:
        if any(t['bucket'] == 'INCOME' for t in rows):
            continue
        if len(months) >= 2 or tot >= 0.25 * total_in:
            big = max(t['credit'] for t in rows)
            for t in rows:
                if t['credit'] >= 0.5 * big:
                    t.update(bucket='INCOME', category='Income (type to confirm)', hint='regular or large bank credit: confirm what this is')
                else:
                    t.update(category='Same payer, smaller credit', hint='smaller credit from the income payer: allowance, reimbursement or part payment?')

    if a.overrides:
        apply_overrides(tx, json.load(open(a.overrides)))

    # --- duplicates -------------------------------------------------------------------------------
    dups, same = [], []
    seen = defaultdict(list)
    for t in tx:
        if t['cp']['ref']:
            seen[(t['account'], t['cp']['ref'], t['debit'] > 0)].append(t)
    for k, v in seen.items():
        if len(v) > 1:
            dups.append(f"{k[0]}: reference {k[1]} appears {len(v)} times ({v[0]['date']}, {v[0]['label']}, {amt(v[0]):.2f})")
    g = defaultdict(list)
    for t in debits:
        g[(t['account'], t['date'], t['cp']['key'], t['debit'])].append(t)
    for k, v in g.items():
        if len(v) > 1 and k[2]:
            same.append(f"{k[1]} {v[0]['label']}: {len(v)} payments of {k[3]:.2f} ({k[0]}), each with its own reference")

    # --- recurring debits that stopped ---------------------------------------------------------
    missing = []
    acc_end = {x['label']: x['end'] for x in src['accounts']}
    rec = defaultdict(list)
    for t in debits:
        if t['bucket'] != 'SELF' and t['debit'] >= 500 and t['cp']['key'] and t['category'] != 'Cash Withdrawal':
            rec[(t['account'], t['cp']['key'])].append(t)
    for (acc, key), rows in rec.items():
        months = sorted({t['date'][:7] for t in rows})
        if len(months) < 2:
            continue
        amts = [t['debit'] for t in rows]
        if max(amts) > 1.15 * min(amts):
            continue
        last = dt.date.fromisoformat(months[-1] + '-01')
        nxt = dt.date(last.year + (last.month == 12), last.month % 12 + 1, 1)
        day = max(D(t).day for t in rows)
        due = nxt + dt.timedelta(days=min(day, 28) + 4)
        if due.isoformat() <= acc_end[acc]:
            missing.append(f"{rows[0]['label']} ({acc}): about {amts[-1]:.2f} in {', '.join(months)}, nothing after. Stopped, moved, or missed?")

    # --- periods -------------------------------------------------------------------------------
    start, end = min(D(t) for t in tx), max(D(t) for t in tx)
    periods = month_periods(start, end)
    if a.periods == 'income-cycle':
        incs = [t for t in tx if t['bucket'] == 'INCOME']
        if incs:
            big = max(t['credit'] for t in incs)
            anchors = sorted({t['date'] for t in incs if t['credit'] >= 0.6 * big})
            if len(anchors) >= 2:
                periods = []
                if start.isoformat() < anchors[0]:
                    periods.append(dict(name='Before first income credit', start=start.isoformat(),
                                        end=(dt.date.fromisoformat(anchors[0]) - dt.timedelta(days=1)).isoformat()))
                for i, s in enumerate(anchors):
                    e = (dt.date.fromisoformat(anchors[i + 1]) - dt.timedelta(days=1)) if i + 1 < len(anchors) else end
                    sd = dt.date.fromisoformat(s)
                    periods.append(dict(name=f"Cycle from {sd.strftime('%d %b')}" + (' (open)' if i + 1 == len(anchors) else ''),
                                        start=s, end=e.isoformat()))
            else:
                print('!! fewer than two main income credits found: using calendar months instead of income cycles')

    coverage = []
    ends = {x['label']: (x['start'], x['end']) for x in src['accounts']}
    if len({v for v in ends.values()}) > 1:
        coverage.append('Statements cover different date ranges: ' + '; '.join(f'{k} {v[0]} to {v[1]}' for k, v in ends.items())
                        + '. Days covered by only some accounts are incomplete.')
    for x in src['accounts']:
        if not x['verified']:
            coverage.append(f"{x['label']}: rows could not be verified against a running balance.")
    for t in self_unpaired:
        coverage.append(f"Self transfer {t['date']} {amt(t):.2f} ({t['account']}) has no matching leg in the other statements: "
                        f"the other account is not supplied or does not cover that date.")

    out_tx = [dict(date=t['date'], account=t['account'], seq=t['seq'], description=t['description'], counterparty=t['cp']['name'],
                   label=t['label'], category=t['category'], bucket=t['bucket'], debit=t['debit'], credit=t['credit'],
                   balance=t['balance'], hint=t['hint']) for t in tx]
    json.dump(dict(meta=dict(currency=a.currency, locale=a.locale, owners=a.owner, period_mode=a.periods),
                   accounts=src['accounts'], periods=periods, transactions=out_tx,
                   auto=dict(duplicates=dups, same_day_repeats=same, missing_recurring=missing, coverage=coverage)),
              open(a.out, 'w'), ensure_ascii=False, indent=1)

    # --- console summary for the analyst -------------------------------------------------------
    f = lambda v: f'{v:,.2f}'
    print(f'Wrote {a.out}\n\nBUCKET TOTALS')
    for b in BUCKETS:
        rows = [t for t in tx if t['bucket'] == b]
        print(f"  {b:8} out {f(sum(t['debit'] for t in rows)):>14}  in {f(sum(t['credit'] for t in rows)):>14}  rows {len(rows)}")
    print('\nPERIODS')
    for p in periods:
        rows = [t for t in tx if p['start'] <= t['date'] <= p['end']]
        S = lambda b, k: sum(t[k] for t in rows if t['bucket'] == b)
        print(f"  {p['name']:28} {p['start']}..{p['end']}  income {f(S('INCOME','credit')):>12}  expense {f(S('EXPENSE','debit')):>12}  "
              f"review {f(S('REVIEW','debit')):>12}  self {f(S('SELF','debit')):>12}")
    print('\nINCOME (confirm type with the user unless the narration says salary/pension)')
    g = defaultdict(list)
    for t in tx:
        if t['bucket'] == 'INCOME':
            g[(t['label'], t['category'])].append(t)
    for k, v in g.items():
        print(f"  {k[0][:30]:30} {k[1]:26} {f(sum(t['credit'] for t in v)):>12}  {[t['date'][5:] + ':' + str(t['credit']) for t in v][:8]}")
    if not g:
        print('  none detected: ask the user what their income is and how it arrives')
    print('\nEXPENSE GROUPS (check labels look right; fix wrong ones with overrides)')
    g = defaultdict(list)
    for t in tx:
        if t['bucket'] == 'EXPENSE':
            g[(t['category'], t['label'])].append(t)
    for k, v in sorted(g.items(), key=lambda kv: -sum(t['debit'] for t in kv[1]))[:40]:
        print(f"  {k[0][:22]:22} {k[1][:34]:34} {f(sum(t['debit'] for t in v)):>12}  n={len(v)}")
    print(f'\nQUESTIONS TO ASK (top {a.max_questions} review groups by amount; ask these before the final report)')
    g = defaultdict(list)
    for t in tx:
        if t['bucket'] == 'REVIEW':
            g[t['cp']['key'] or t['label']].append(t)
    exp_total = sum(t['debit'] for t in tx if t['bucket'] == 'EXPENSE') or 1
    ranked = sorted(g.items(), key=lambda kv: -sum(t['debit'] + t['credit'] for t in kv[1]))
    for k, v in ranked[:a.max_questions]:
        days = sorted({D(t).day for t in v})
        rem = sorted({t['cp']['remark'] for t in v if t['cp']['remark'] and t['cp']['remark'].upper() not in STOP})
        print(f"  ? {v[0]['label'][:28]:28} out {f(sum(t['debit'] for t in v)):>12} in {f(sum(t['credit'] for t in v)):>10} n={len(v)} "
              f"months={sorted({t['date'][:7] for t in v})} days={days[:6]} remarks={rem[:4]} | {v[0]['hint']}")
    rest = ranked[a.max_questions:]
    if rest:
        print(f"  ... {len(rest)} smaller review groups totalling {f(sum(t['debit'] for _, v in rest for t in v))} stay in REVIEW")
    for t in tx:
        if t['bucket'] == 'EXPENSE' and t['category'] in ('Local shops (QR)', 'Other') and t['debit'] >= max(2000, 0.08 * exp_total):
            print(f"  ? Large unidentified merchant payment: {t['date']} {t['label']} {f(t['debit'])} - what was it for?")
    for t in tx:
        if t['bucket'] == 'PASS':
            print(f"  ? Pass-through to confirm: {t['date']} {t['label']} {'out' if t['debit'] else 'in'} {f(amt(t))} ({t['category']})")
    for m in missing:
        print('  ? Recurring debit stopped:', m)
    for k, title in (('coverage', 'COVERAGE WARNINGS'), ('duplicates', 'DUPLICATE REFERENCES'), ('same_day_repeats', 'SAME PAYEE, AMOUNT AND DAY')):
        rows = dict(coverage=coverage, duplicates=dups, same_day_repeats=same)[k]
        print(f'\n{title}: ' + ('none' if not rows else ''))
        for r in rows[:15]:
            print('  -', r)


if __name__ == '__main__':
    main()

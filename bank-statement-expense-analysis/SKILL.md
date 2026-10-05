---
name: bank-statement-expense-analysis
description: Use when the user shares bank statements (PDF/CSV/XLSX, any bank) and wants to know what came in, what went out and where it went, by month or income cycle, with clarifying questions and an HTML report.
license: MIT
compatibility: Needs a shell and Python 3 with pdfplumber and openpyxl. Works without network access when the scripts folder is installed with the skill.
---

# Bank statement expense analysis

Answer "what came in, what went out, where did it go?" from bank statements, for any bank and any kind of account (salaried, business, freelance, pension, student). Three scripts do all the arithmetic. Your job is to run them in order, read what they print, ask the user the questions they list, and copy numbers from their output. Never calculate or estimate a number yourself.

**Core rule: money leaving an account is not automatically an expense.** Each transaction gets one bucket:

| Bucket | Meaning |
|---|---|
| `EXPENSE` | actually spent |
| `SELF` | moved between the user's own accounts, cards, wallets, investments |
| `REVIEW` | unclear; never counted as spending |
| `PASS` | received and paid back, lent and returned, bought and refunded |
| `INCOME` | earned: salary, business receipts, fees, pension, rent received |
| `INFLOW` | other money in: from individuals, interest, refunds |

When unsure use `REVIEW`. A payment to a parent, spouse, landlord or flatmate is never `SELF`.

## Setup

Scripts are in `scripts/` beside this file. If that folder is missing:

```bash
git clone --depth 1 https://github.com/snehangshu2002/bank-statement-expense-analysis-skill /tmp/bsea
S=/tmp/bsea/bank-statement-expense-analysis/scripts      # otherwise S=<this folder>/scripts
pip install pdfplumber openpyxl
```

Work in a scratch folder; never edit the user's files. Each script has `--help`. `reference.md` (beside this file, or in the cloned folder) holds the classification rules and algorithms; open it only when a step points to it.

## Step 1: Extract

```bash
python3 $S/extract_statement.py FILE [FILE ...] -o transactions.json
```

Flags: `--password PW`, `--monthfirst` (US dates), `--account-label "file.pdf=HDFC 1234"`.

Each account must print `VERIFIED` (every row fits the running balance). Compare the printed counts and totals with the statement's own summary if it has one. Note each account's date range.

- `no transaction rows found`: scanned or locked PDF. OCR it (`ocrmypdf`), or ask for the password or a CSV/Excel export.
- `NOT VERIFIED (no running balance column)`: continue, and tell the user the totals are unproven.
- `NOT VERIFIED` with mismatch rows: rows were misread. Fix before going on (see `reference.md`).

## Step 2: Draft

Take the account holder's name from the statement (ask if it is not printed).

```bash
python3 $S/analyze.py transactions.json -o classified.json --owner "HOLDER NAME"
```

Flags: `--periods income-cycle` only if income arrives on a regular date and the user asks about "after salary"; default is calendar months. `--currency "$" --locale en-US` outside India.

Read everything it prints: bucket totals, periods, detected income, expense groups, lines starting `?`, coverage warnings, duplicates.

## Step 3: Ask the user (required)

Do not build the report before asking. Use a question tool if you have one, otherwise ask in text and wait. At most 8 questions, in this order:

1. **Income.** Do not assume salary. If the script says "type to confirm" or "none detected", ask how money arrives: salary / business takings / client fees / pension / rent / family support / not income.
2. **Each `?` review group**, largest first: rent or housing / family support / shared bill / loan given or repaid / business expense / personal spending / other.
3. **Other `?` lines:** large unidentified payments, pass-through pairs, recurring debits that stopped.

Put the date, amount and any remark in every question. Skip small one-off payments; they stay in `REVIEW`. If the user is unavailable, carry on and list the unanswered questions as `open_questions` in Step 5.

## Step 4: Record answers

Write `overrides.json`: rules applied in order, later ones win.

```json
[{"match": "ACME PVT", "direction": "credit", "bucket": "INCOME", "category": "Salary"},
 {"match": "RAVI KUMAR", "bucket": "EXPENSE", "category": "Rent", "label": "Flat rent"},
 {"match": "ATM CASH", "date": "2025-04-05", "amount": 10000, "bucket": "PASS", "category": "Cash for a friend"}]
```

`match` is text found in the description or payee (or use `regex`). Optional filters: `date`, `amount`, `direction`, `account`. Set any of `bucket`, `category`, `label`. For a business or freelance account, add one `INCOME` rule per customer or client. Also use overrides to fix a payee label that came out wrong.

Re-run Step 2 with `--overrides overrides.json`. Fix any rule reported as `matched nothing`.

## Step 5: Report

Write `narrative.json` (all keys optional, plain text, `**bold**` allowed):

```json
{"title": "Money Trail Apr-Jun 2025", "headline": "one-sentence answer",
 "headline_note": "the caveat that most changes it", "open_questions": [],
 "summary": ["what came in", "where it went", "what is excluded"],
 "unusual": [], "observations": [], "assumptions": []}
```

- `unusual`: largest payments, payees with many small payments (count and total), category jumps, subscriptions, recurring debits that stopped.
- `observations`: 5 to 10 facts about habits, and whether the balance is rising or falling. Facts only, no financial advice.
- Compare per-day figures when periods differ in length.

```bash
python3 $S/build_report.py classified.json -o report.html --narrative narrative.json
```

It stops with `NOT RECONCILED` if opening + credits − debits ≠ closing. Go back to Step 1; never bypass it. Publish `report.html` as an artifact if you can, otherwise send the file.

## Step 6: Reply

Short. From the printed `TOTALS` line: income, confirmed spending, amount still in review; a small per-period table; two or three things to check; open questions. Always state:

- accounts that are unverified or cover different dates
- self transfers with no matching leg (the other account is missing)
- that credit card bills, investments and wallet top-ups are `SELF`, so that spending is not itemised here

If answers arrive later, add overrides, re-run Steps 4 and 5, and say which numbers changed. Keep `overrides.json` to reuse next time.

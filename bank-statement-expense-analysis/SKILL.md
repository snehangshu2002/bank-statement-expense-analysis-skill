---
name: bank-statement-expense-analysis
description: Use when the user shares bank statements (PDF/CSV/XLSX, any bank) and wants to know what money came in, what went out and where it went, month by month or per income cycle, with clarifying questions and an HTML report. Works for salaried, self-employed, business, freelance, pension and student accounts.
---

# Bank statement expense analysis

Turn one or more bank statements into a proven, reconciled answer to "what came in, what went out, and where did it go?". Follow the steps in order. Do not skip a step, and do not estimate any number: every figure you tell the user must come from the scripts' output.

## The one rule that matters

**Money leaving an account is not automatically an expense.** Every transaction goes into exactly one of six buckets:

| Bucket | Meaning | Counts as spending? |
|---|---|---|
| `EXPENSE` | Money actually spent or consumed | Yes |
| `SELF` | Moved between the user's own accounts, cards, wallets, investments | No |
| `REVIEW` | Cannot be classified with confidence | No, shown separately |
| `PASS` | Received and paid back, lent and returned, or bought and fully refunded | No |
| `INCOME` | Earned income: salary, business receipts, professional fees, pension, rent received | It is money in |
| `INFLOW` | Other money in: from individuals, interest, dividends, refunds, cashback | It is money in |

When unsure, use `REVIEW`. Never guess.

## Step 0: Find the scripts

Three scripts do the work. Look for them in a `scripts/` folder next to this file:

- `extract_statement.py` reads statements and proves the rows are complete
- `analyze.py` drafts the classification and prints the questions to ask
- `build_report.py` checks the books balance and writes the HTML report

If the folder is missing, get it:

```bash
git clone --depth 1 https://github.com/snehangshu2002/bank-statement-expense-analysis-skill /tmp/bsea
SCRIPTS=/tmp/bsea/bank-statement-expense-analysis/scripts
```

If that also fails, write equivalent code yourself following "Technical reference" at the end of this file. Needs Python 3 with `pdfplumber` (PDF) and `openpyxl` (Excel): `pip install pdfplumber openpyxl`.

Work in a scratch folder. Never edit the user's original files.

## Step 1: Extract and verify

```bash
python3 $SCRIPTS/extract_statement.py statement1.pdf statement2.pdf -o transactions.json
```

Options: `--password PW` for locked PDFs, `--monthfirst` if dates are US style (03/07 = March 7), `--account-label "file.pdf=HDFC 1234"` to name an account yourself.

Read the output. For every account it prints the date range, row count, opening balance, total debits and credits, closing balance and `VERIFIED` or `NOT VERIFIED`.

Checklist before you continue:

1. **Every account says VERIFIED.** This means each row satisfied `previous balance - debit + credit = balance`. If an account says NOT VERIFIED, read "When extraction fails" below. Do not continue silently.
2. **Totals match the statement.** If the statement prints its own summary (debit count, credit count, total debits, total credits, closing balance), compare them with the script's numbers. They must be equal.
3. **Note the date range of each account.** If accounts cover different dates, the days covered by only some accounts are incomplete. You must tell the user this. If a statement's cover page shows a later balance than its last row, work out the gap and report it as unseen.
4. **Several files for one account are merged automatically** and overlapping rows are dropped. Check the merged row count looks sensible.

### When extraction fails

| Symptom | What to do |
|---|---|
| "no transaction rows found" | The PDF may be a scanned image. Run OCR first (`ocrmypdf in.pdf out.pdf`), or ask the user for a CSV/Excel download or a text-based PDF. Password-protected: ask for the password. |
| NOT VERIFIED, "no running balance column" | The file has no balance column, so totals cannot be proven. Continue, but tell the user the figures are unverified and ask for a statement that shows balances. |
| NOT VERIFIED with mismatch rows | Some rows were missed or misread. Open the PDF pages around the dates printed, find the cause (a row split across pages, a merged cell), and fix it. Do not report until the balance walk passes. |
| Dates look wrong (month and day swapped) | Re-run with `--monthfirst`, or without it. |
| Wrong bank name or account label | Use `--account-label`. |

## Step 2: Ask who the account holder is and what kind of account it is

You need two facts. Take them from the statement where printed; otherwise ask the user.

1. **Account holder name** exactly as printed on the statement. This is how transfers to their own other accounts are recognised.
2. **How money normally arrives.** Do not assume a salary. Ask if it is not obvious:
   - Salary from an employer
   - Business or shop takings (many credits from customers)
   - Freelance or professional fees (irregular credits from clients)
   - Pension, rent received, or family support
   - A mix, or no regular income (student, homemaker)

## Step 3: Draft the classification

```bash
python3 $SCRIPTS/analyze.py transactions.json -o classified.json --owner "NAME AS ON STATEMENT"
```

Options: `--periods month` (default, calendar months) or `--periods income-cycle` (from each main income credit to the day before the next; use only when income arrives on a regular date and the user asks about "after salary" or similar). `--currency "$" --locale en-US` for other countries. `--owner` can be repeated for joint holders.

Read all of the printed output. It contains:

- **BUCKET TOTALS** and **PERIODS**: a first picture.
- **INCOME**: what the script thinks is income. It marks a credit as income only if the narration says salary or pension, or if it is a regular or large bank transfer. Anything marked "type to confirm" must be confirmed with the user.
- **EXPENSE GROUPS**: check every label is sensible. A wrong label means the bank writes narrations in a style the parser did not expect. Fix with overrides (Step 5).
- **QUESTIONS TO ASK**: lines starting with `?`. These are your questions for Step 4.
- **COVERAGE WARNINGS**, **DUPLICATE REFERENCES**, **SAME PAYEE, AMOUNT AND DAY**: must be reported to the user.

### How the draft decides (so you can check it)

Applied in this order; the first rule that fits wins.

| # | If the transaction... | Bucket | Category |
|---|---|---|---|
| 1 | has the account holder's name as counterparty | SELF | Self Transfer |
| 2 | has the same payment reference as a transaction in another supplied account, or same amount in another account within 1 day | SELF | Self Transfer |
| 3 | goes to a broker, mutual fund, SIP, NPS, PPF, FD or RD | SELF | Investments/Savings |
| 4 | pays a credit card bill | SELF | Credit card bill |
| 5 | loads a wallet (UPI Lite, Paytm wallet) | SELF | Wallet top-up |
| 6 | is a credit whose narration says salary, payroll, stipend, pension | INCOME | Salary / Pension |
| 7 | is a credit for interest, dividend, cashback, refund, tax refund | INFLOW | as named |
| 8 | is a credit from a known merchant | INFLOW | Refund / cashback |
| 9 | is a regular (2+ months) or large NEFT/RTGS/ACH/cheque credit from one payer | INCOME | Income (type to confirm) |
| 10 | is any other credit | INFLOW | Received from individuals / Bank transfer received / Cash deposit |
| 11 | is an ATM cash withdrawal | EXPENSE | Cash Withdrawal |
| 12 | is a debit to a known merchant or brand | EXPENSE | Food, Groceries, Shopping, Subscriptions, Transport, Travel, Fuel, Bills, Entertainment, Healthcare, Education, Insurance |
| 13 | is an auto-debit (NACH/ACH/ECS) or says EMI or loan | EXPENSE | Loan EMI |
| 14 | is a bank fee, penalty, card annual charge | EXPENSE | Bank Charges |
| 15 | is a card purchase at an unknown merchant | EXPENSE | Other |
| 16 | is a UPI payment to a shop QR code (payee ID starts with `q`+digits, `paytmqr`, `bharatpe`, `vyapar`, `gpay-`+digits, and similar) | EXPENSE | Local shops (QR) |
| 17 | is anything else going out (payment to a person, cheque, unknown payee) | REVIEW | Review Required |

After these, two pairing rules run:

- **Pass-through:** same counterparty, same amount, one in and one out within 10 days becomes `PASS`. For a merchant this is a refunded purchase.
- **Cash for someone else:** an ATM withdrawal on the same day an identical amount arrived from a person becomes `REVIEW` on both sides.

### Things the draft gets wrong on purpose (it is cautious)

- A payment to a parent, spouse, landlord or flatmate is `REVIEW`, not `SELF`. It is someone else's account. Never mark it `SELF`.
- For a **business or freelance** user, customer payments arrive as "Received from individuals" (`INFLOW`). After the user confirms, move them to `INCOME` with an override (see Step 5 examples).
- A shop QR payment is `EXPENSE` but the category is only "Local shops (QR)". Do not guess what was bought from a shortened name.
- Credit card bill payments are `SELF`. The actual spending is on the card statement. Tell the user that card spending is not analysed unless they share the card statement.
- An auto-debit is assumed to be a loan EMI. It could be insurance or a SIP. Ask if the amount is significant.

## Step 4: Ask the user (required)

Do not write the final report before asking. Use the question tool if you have one; otherwise ask in plain text and wait.

Ask about, in this order, at most 8 questions in total:

1. **Income** marked "type to confirm": "You received [amount] from [payer] on [dates]. What is this?" Options: Salary / Business income / Client or freelance payment / Pension / Rent received / Family support / Loan or one-off, not income.
2. **Each `?` review group**, largest first: "You paid [payee] [total] in [n] payments ([dates], remark: [remark]). What was this for?" Options: Rent or housing / Family support / Shared bill or flatmate / Loan given or repaid / Business expense or supplier / Personal spending / Something else.
3. **Large unidentified merchant payments**: "What was the [amount] to [payee] on [date] for?"
4. **Pass-through pairs**: "You received [amount] from [person] and paid the same amount back. Should I leave both out of income and spending?"
5. **Recurring debits that stopped**: "[payee] took [amount] in [months] but not since. Is it finished, moved, or missed?"
6. **Smaller credits from the income payer**: allowance, reimbursement or part payment?

Rules for asking:

- Always include the date, amount and any remark in the question.
- Do not ask about small one-off payments. They stay in `REVIEW` and are shown as one total.
- If the user is not available, continue with those items in `REVIEW`, and list the unanswered questions at the top of the report under "open questions".

## Step 5: Record the answers and re-run

Write the answers into `overrides.json`. It is a list of rules, applied in order; a later rule wins over an earlier one.

```json
[
 {"match": "ACME PVT", "direction": "credit", "bucket": "INCOME", "category": "Salary", "label": "Employer (ACME)"},
 {"match": "RAVI KUMAR", "direction": "debit", "bucket": "EXPENSE", "category": "Rent", "label": "Flat rent"},
 {"match": "S SHARMA", "direction": "debit", "bucket": "EXPENSE", "category": "Family Support", "label": "Parents"},
 {"match": "ATM CASH", "date": "2025-04-05", "amount": 10000, "bucket": "PASS", "category": "Cash drawn for a friend"}
]
```

Rule keys:

- `match`: text to find, not case sensitive, searched in the original description, the parsed counterparty and the label. Or `regex` for a pattern.
- Optional filters: `date` (YYYY-MM-DD), `amount`, `direction` (`debit` or `credit`), `account`.
- What to set: `bucket` (one of the six), `category` (free text; reuse existing category names where possible), `label` (the display name).

Common overrides:

- **Business user, all customer receipts are income:** `{"regex": ".", "direction": "credit", "bucket": "INCOME", "category": "Business receipts"}` placed **first**, followed by rules that put back interest, refunds, own transfers and loans. Simpler and safer: write one rule per known customer or per payment channel.
- **Freelancer:** one rule per client.
- **Supplier or stock purchases:** `bucket: EXPENSE`, `category: Business expense`.
- **Loan given to a friend, not yet returned:** keep `REVIEW` and set `category: Loan given`.

Then re-run and check every rule matched:

```bash
python3 $SCRIPTS/analyze.py transactions.json -o classified.json --owner "NAME" --overrides overrides.json
```

A line starting `!! overrides rule N matched nothing` means the `match` text is wrong. Fix it and run again.

## Step 6: Write the narrative

Create `narrative.json`. Plain text only; `**bold**` is allowed. Every number you write must be copied from the output of `analyze.py` or `build_report.py`. Count things from the data, never from memory.

```json
{
 "title": "Money Trail Apr-Jun 2025",
 "headline": "One sentence that answers where the money went",
 "headline_note": "The single caveat that most changes the answer",
 "open_questions": ["Questions the user has not answered yet"],
 "summary": ["Paragraph 1: what came in.", "Paragraph 2: where the confirmed spending went, top categories with amounts.", "Paragraph 3: what is excluded and why."],
 "unusual": ["**Large payment.** What, when, how much.", "..."],
 "observations": ["5 to 10 practical observations about habits and where spending could be cut"],
 "assumptions": ["Each assumption you made, one per item"],
 "review_reasons": {"PAYEE LABEL": "Why this payee needs a look"}
}
```

What to look for when writing `unusual` and `observations`:

- The largest single payments, and any one payment that is a big share of a period
- Payees with very many small payments (give count and total)
- A category that jumped or dropped between periods (compare per-day figures when periods differ in length)
- Subscriptions: list them, give the monthly total, point out overlaps
- A recurring debit that stopped (a period looks cheaper than it really is)
- Money shuttling between own accounts
- Whether anything was saved or invested
- Spending against income: is the balance rising or falling?
- For business accounts: receipts against supplier payments, and personal spending mixed into the business account

Write facts and observations. Do not give financial advice or tell the user what they should buy, sell or invest in.

## Step 7: Build the report

```bash
python3 $SCRIPTS/build_report.py classified.json -o report.html --narrative narrative.json
```

The script prints a reconciliation for each account and stops with `NOT RECONCILED` if `opening + credits - debits` does not equal the closing balance. If that happens, go back to Step 1. Never use `--allow-unreconciled` to get past a real mismatch.

The report contains: headline and open questions, period cards, where money came from, expenses by category, top payees, period comparison, review table, unusual items, duplicate and coverage checks, reconciliation, summary, observations, assumptions, and a searchable ledger with every original description.

Deliver it:

- If you can publish an artifact or web page, publish `report.html` (it is written in the format artifact publishing expects: no `<html>` or `<body>` tags, light and dark themes).
- Otherwise send `report.html` as a file. It opens in any browser.

## Step 8: Reply to the user

Keep the chat reply short. Use the `TOTALS` line that `build_report.py` printed.

1. One sentence: total income, confirmed spending, amount still to classify.
2. A small table per period: income, confirmed expenses, review amount, self transfers.
3. Two or three things worth checking.
4. Any coverage gap (accounts ending on different dates, unverified accounts, card spending not included).
5. The questions still open.

If the user answers more questions later, add overrides, re-run Steps 5 to 7, and say which numbers changed. If you correct a number you gave earlier, say so plainly. Keep `overrides.json`: offer to reuse the confirmed payees next time so the user is not asked twice.

## Checklist before you send anything

- [ ] Every account VERIFIED, or the user has been told which is not and why
- [ ] Script totals equal the statement's printed summary, where one exists
- [ ] Account holder name passed with `--owner`
- [ ] Income type confirmed with the user, not assumed to be salary
- [ ] Questions asked for the top review groups
- [ ] No override rule "matched nothing"
- [ ] `build_report.py` printed a difference of 0.0 for every account
- [ ] Nothing paid to another person is marked `SELF`
- [ ] Every number in the narrative and the reply was copied from script output
- [ ] Coverage gaps and unpaired self transfers are mentioned
- [ ] No statement, report or personal detail was uploaded or committed anywhere public

## Technical reference

Use this to understand the scripts, to debug them, or to rebuild them if they are unavailable.

### Data files

`transactions.json` (from Step 1):

```json
{"accounts": [{"label": "HDFC ··1234", "start": "2025-04-01", "end": "2025-06-30", "opening": 10000.00,
               "closing": 18450.25, "rows": 212, "debits": 141549.75, "credits": 150000.00, "verified": true}],
 "transactions": [{"account": "HDFC ··1234", "seq": 0, "date": "2025-04-02", "description": "original text",
                   "debit": 0.0, "credit": 50000.0, "balance": 60000.0}]}
```

`classified.json` (from Step 3) adds to each transaction: `counterparty`, `label`, `category`, `bucket`, `hint`; and adds top-level `periods` (`name`, `start`, `end`), `meta` and `auto` (duplicates, same-day repeats, missing recurring debits, coverage warnings). You may edit this file by hand if needed; `build_report.py` only needs `accounts`, `periods`, `transactions` and `meta`.

### Extraction algorithm

1. **Collect rows.** PDF: `pdfplumber` `page.extract_tables()` on every page; if a page has no table, split its text into lines, start a row at each line that begins with a date, and take the trailing money tokens as amounts. CSV/XLSX: read rows directly.
2. **Find transaction rows.** A row with a date in one of its first four cells and at least one money cell.
3. **Parse dates.** Accept `dd/mm/yyyy`, `dd-mm-yyyy`, `dd.mm.yyyy`, `yyyy-mm-dd`, `dd Mon yyyy`, `dd-Mon-yy`, `Mon dd, yyyy`. Day first unless told otherwise.
4. **Parse money.** Strip currency symbols and thousands commas (Indian `1,23,456.78` and Western `123,456.78` both work). A trailing `Cr`/`Dr` is a flag. Brackets or a minus sign mean negative. A number with 10 or more digits and no decimal point is a reference number, not money.
5. **Find columns.** Use the header row when there is one (keywords: date; description, narration, particulars, remarks, details; debit, withdrawal; credit, deposit; balance; amount; type, dr/cr). Otherwise: the balance column is the last money column that is filled on almost every row; the other money columns are amounts; the description is the non-money column with the most text.
6. **Find the order.** Some banks list newest first. Try both orders and keep the one where more rows satisfy the balance rule.
7. **Find the direction from the balance.** For each row, `delta = balance - previous balance`. If `|delta|` equals the row's amount, then `delta < 0` is a debit and `delta > 0` is a credit. This one rule handles separate debit and credit columns, a single amount column with a DR/CR flag, and signed amounts. For the first row, or when there is no balance, fall back to the DR/CR flag, then the column the amount sits in, then the sign.
8. **Verify.** Walk the rows: `previous balance - debit + credit` must equal `balance` (tolerance 0.01). Opening balance is the first row's balance with its own movement undone. Count every failure.
9. **Merge.** Several files for one account are joined in date order; a row that already exists (same date, description, debit, credit, balance) is dropped.

### Reading a narration

Common Indian formats, and what to pull out of them:

| Channel | Example | Counterparty |
|---|---|---|
| UPI (slash style) | `UPI/DR/512345678901/NAME/BANK/payee-id/remark` | segment after the 12-digit reference; next is the bank, next the payee ID, next the remark |
| UPI (hyphen style) | `UPI-NAME-name@bank-IFSC-512345678901-remark` | first segment after `UPI` that has letters and no `@` |
| NEFT / RTGS / IMPS | `NEFT*IFSC*REF*NAME*...` or `NEFT-NAME-REMARK` | first segment with letters that is not a code |
| Card | `POS 4321XXXX MERCHANT CITY`, `ECOM 123 MERCHANT` | the words left after removing codes and numbers |
| Auto-debit | `ACH D- LENDERNAME-REF`, `NACH...` | the name token |
| ATM | `ATM WDL`, `ATM CASH`, `NWD`, `AWB` | cash |
| Cheque | `CHQ`, `CLG` | usually unknown |
| Cash deposit | `CASH DEP`, `BY CASH`, `CDM` | cash in |

Names and payee IDs are often cut short by the bank. Show them as written. The 12-digit UPI/IMPS reference is the key for matching the two sides of a transfer and for spotting duplicates.

### Self-transfer detection

- **By name:** remove everything but letters from the counterparty and from the holder's name; it is a match when the counterparty (5+ letters) is the start of the holder's full name, or starts with the holder's first name.
- **By pair:** a debit in one account and a credit of the same amount in another supplied account, with the same reference (certain), or within one day (likely).
- **Unpaired:** a self transfer by name with no matching leg means the other account was not supplied or does not cover that date. Report it.
- Self transfers in and out should cancel across all accounts. If they do not, the difference is the unpaired legs plus wallet loads, card payments and investments.

### Periods

- **Calendar month** (default): each month clipped to the data; marked "partial" when not a full month.
- **Income cycle:** anchor dates are the dates of `INCOME` credits that are at least 60% of the largest income credit. Each cycle runs from an anchor to the day before the next. All transactions on an anchor date belong to the new cycle (statements have no clock time). Needs at least two anchors; otherwise months are used.
- Always show the number of days and a per-day figure when comparing periods of different length.

### Reconciliation

Per account: `opening + sum(credits) - sum(debits) = closing`.

Across all accounts, by bucket:
`opening + INCOME + INFLOW + REVIEW in + PASS in + SELF in - EXPENSE - REVIEW out - PASS out - SELF out = closing`.

Both must hold to the smallest currency unit. A difference means a missing row, a duplicated row or a wrong sign, never "rounding".

### Duplicates

- Same reference twice in the same account and direction: a real duplicate; report it.
- Same reference in two accounts: the two sides of a self transfer; not a duplicate.
- Same payee, amount and day with different references: separate payments (tickets, repeat purchases); keep them and list them.

### Limits to state honestly

- Tested on Indian savings-account statements (SBI and PNB PDFs) and on CSV layouts with separate debit/credit columns, a signed amount column, and an amount column with a DR/CR flag. Other layouts usually work because direction comes from the balance, but check Step 1 carefully.
- Credit card statements, loan statements and foreign-currency accounts are not handled as such.
- Scanned image PDFs need OCR first.
- The merchant list is mostly Indian brands. Unknown merchants fall into "Other" or "Local shops (QR)"; rename them with overrides.

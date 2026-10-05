# Reference

Read this only when a step in SKILL.md sends you here: to check why a transaction got its bucket, to debug extraction, or to rebuild the scripts if they are unavailable.

## How the draft classifier decides

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

## Where the draft is deliberately cautious

- A payment to a parent, spouse, landlord or flatmate is `REVIEW`, not `SELF`. It is someone else's account. Never mark it `SELF`.
- For a **business or freelance** user, customer payments arrive as "Received from individuals" (`INFLOW`). After the user confirms, move them to `INCOME` with an override (SKILL.md Step 4).
- A shop QR payment is `EXPENSE` but the category is only "Local shops (QR)". Do not guess what was bought from a shortened name.
- Credit card bill payments are `SELF`. The actual spending is on the card statement. Tell the user that card spending is not analysed unless they share the card statement.
- An auto-debit is assumed to be a loan EMI. It could be insurance or a SIP. Ask if the amount is significant.

## Data files

`transactions.json` (from extract_statement.py):

```json
{"accounts": [{"label": "HDFC ··1234", "start": "2025-04-01", "end": "2025-06-30", "opening": 10000.00,
               "closing": 18450.25, "rows": 212, "debits": 141549.75, "credits": 150000.00, "verified": true}],
 "transactions": [{"account": "HDFC ··1234", "seq": 0, "date": "2025-04-02", "description": "original text",
                   "debit": 0.0, "credit": 50000.0, "balance": 60000.0}]}
```

`classified.json` (from analyze.py) adds to each transaction: `counterparty`, `label`, `category`, `bucket`, `hint`; and adds top-level `periods` (`name`, `start`, `end`), `meta` and `auto` (duplicates, same-day repeats, missing recurring debits, coverage warnings). You may edit this file by hand if needed; `build_report.py` only needs `accounts`, `periods`, `transactions` and `meta`.

## Extraction algorithm

1. **Collect rows.** PDF: `pdfplumber` `page.extract_tables()` on every page; if a page has no table, split its text into lines, start a row at each line that begins with a date, and take the trailing money tokens as amounts. CSV/XLSX: read rows directly.
2. **Find transaction rows.** A row with a date in one of its first four cells and at least one money cell.
3. **Parse dates.** Accept `dd/mm/yyyy`, `dd-mm-yyyy`, `dd.mm.yyyy`, `yyyy-mm-dd`, `dd Mon yyyy`, `dd-Mon-yy`, `Mon dd, yyyy`. Day first unless told otherwise.
4. **Parse money.** Strip currency symbols and thousands commas (Indian `1,23,456.78` and Western `123,456.78` both work). A trailing `Cr`/`Dr` is a flag. Brackets or a minus sign mean negative. A number with 10 or more digits and no decimal point is a reference number, not money.
5. **Find columns.** Use the header row when there is one (keywords: date; description, narration, particulars, remarks, details; debit, withdrawal; credit, deposit; balance; amount; type, dr/cr). Otherwise: the balance column is the last money column that is filled on almost every row; the other money columns are amounts; the description is the non-money column with the most text.
6. **Find the order.** Some banks list newest first. Try both orders and keep the one where more rows satisfy the balance rule.
7. **Find the direction from the balance.** For each row, `delta = balance - previous balance`. If `|delta|` equals the row's amount, then `delta < 0` is a debit and `delta > 0` is a credit. This one rule handles separate debit and credit columns, a single amount column with a DR/CR flag, and signed amounts. For the first row, or when there is no balance, fall back to the DR/CR flag, then the column the amount sits in, then the sign.
8. **Verify.** Walk the rows: `previous balance - debit + credit` must equal `balance` (tolerance 0.01). Opening balance is the first row's balance with its own movement undone. Count every failure.
9. **Merge.** Several files for one account are joined in date order; a row that already exists (same date, description, debit, credit, balance) is dropped.

## Reading a narration

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

## Self-transfer detection

- **By name:** remove everything but letters from the counterparty and from the holder's name; it is a match when the counterparty (5+ letters) is the start of the holder's full name, or starts with the holder's first name.
- **By pair:** a debit in one account and a credit of the same amount in another supplied account, with the same reference (certain), or within one day (likely).
- **Unpaired:** a self transfer by name with no matching leg means the other account was not supplied or does not cover that date. Report it.
- Self transfers in and out should cancel across all accounts. If they do not, the difference is the unpaired legs plus wallet loads, card payments and investments.

## Periods

- **Calendar month** (default): each month clipped to the data; marked "partial" when not a full month.
- **Income cycle:** anchor dates are the dates of `INCOME` credits that are at least 60% of the largest income credit. Each cycle runs from an anchor to the day before the next. All transactions on an anchor date belong to the new cycle (statements have no clock time). Needs at least two anchors; otherwise months are used.
- Always show the number of days and a per-day figure when comparing periods of different length.

## Reconciliation

Per account: `opening + sum(credits) - sum(debits) = closing`.

Across all accounts, by bucket:
`opening + INCOME + INFLOW + REVIEW in + PASS in + SELF in - EXPENSE - REVIEW out - PASS out - SELF out = closing`.

Both must hold to the smallest currency unit. A difference means a missing row, a duplicated row or a wrong sign, never "rounding".

## Duplicates

- Same reference twice in the same account and direction: a real duplicate; report it.
- Same reference in two accounts: the two sides of a self transfer; not a duplicate.
- Same payee, amount and day with different references: separate payments (tickets, repeat purchases); keep them and list them.

## Limits to state honestly

- Tested on Indian savings-account statements (SBI and PNB PDFs) and on CSV layouts with separate debit/credit columns, a signed amount column, and an amount column with a DR/CR flag. Other layouts usually work because direction comes from the balance, but check the extraction output carefully.
- Credit card statements, loan statements and foreign-currency accounts are not handled as such.
- Scanned image PDFs need OCR first.
- The merchant list is mostly Indian brands. Unknown merchants fall into "Other" or "Local shops (QR)"; rename them with overrides.

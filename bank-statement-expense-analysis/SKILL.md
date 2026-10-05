---
name: "bank-statement-expense-analysis"
description: "Use when the user shares bank statements (PDF/CSV/XLSX) and wants month-wise or salary-cycle analysis of money in, money out, where it went, with clarifying questions and an HTML report."
---

# Bank statement expense analysis

Turn one or more bank statements into a reconciled picture of what came in, what went out, and where it went, month by month or salary cycle by salary cycle. Ask the user about anything that cannot be classified with confidence, then deliver a clickable HTML report.

The core rule: **money leaving an account is not automatically an expense.** Every transaction lands in exactly one bucket:

- **A. Genuine expense**: money actually spent or consumed.
- **B. Self transfer**: money moved between the user's own accounts, wallets, cards or investments. Never an expense.
- **C. Review required**: cannot be classified with confidence. Never silently counted as an expense.
- **Pass-through**: money received and paid back out (or lent and returned) for the same amount. Neither income nor expense.
- **Inflow**: salary, other employer credits, money from individuals, interest, dividends, refunds, cashback.

## Step 1: Extract every transaction in code

Never read figures off the PDF by eye or estimate totals in prose. Parse with code (pdfplumber `extract_tables()` works for SBI and PNB layouts; inspect the first, second and last page before writing the parser, since each bank differs).

For each row capture: account, date, original description (whitespace collapsed, kept verbatim), debit, credit, running balance.

Then prove the extraction is complete:

1. Walk the rows and check `previous balance - debit + credit = balance` on every row. Zero mismatches is the bar.
2. Compare debit count, credit count, total debits, total credits and closing balance against the statement's own summary line if it has one.
3. Note each statement's exact date range. Statements often end on different days; say so, and never present a period as complete when one account's rows stop early. If the cover page shows a later balance than the last row, compute and report the unseen gap.
4. Some statements list newest first. Reverse them before the balance walk.
5. If the user later sends a newer statement for the same account, confirm overlapping rows match before merging, and do not double count.

## Step 2: Parse the counterparty

For UPI rows (`UPI/DR|CR/<ref>/<name>/<bank>/<vpa>/<remark>`), pull out the reference number, name, bank, VPA and remark. Names and VPAs are truncated and may be split by line wrapping; strip spaces before matching but show the statement's own spelling to the user.

Useful signals:

- VPA beginning `q` + digits, `paytm`, `paytmqr`, `bharatpe`, `vyapar`, `gpay-<digits>`, `getepay`, `ombk` is a **shop QR code**. Real spending, but what was bought is unknown. Label it "Local shops (QR)" and do not guess a category from the name.
- VPA that is a phone number or a personal handle is an **individual**. Default to Review required.
- Remarks sometimes carry a hint (for example "ROOM", "Elec", "Fami"). Quote them to the user; do not over-interpret.

## Step 3: Classify

Apply in this order:

1. **Self transfer**: counterparty carries the user's own name at another bank, or the same UPI reference number appears as a debit in one statement and a credit in another. Matching references across statements is the strongest proof. A self transfer with no matching leg means the other statement does not cover that date; say which one.
2. **Salary**: recurring credit of similar amount from the same sender (NEFT/IMPS, employer tag). Smaller credits from the same sender go under "Employer, other" unless the user says what they are.
3. **Pass-through**: same person, same amount, in and out within a few days. Also cash withdrawn the same day someone sent the identical amount (keep this one in Review and ask).
4. **Known merchants**: normalise obvious brands and group them (Swiggy, Zomato, Zepto, Blinkit, Flipkart, Amazon, Myntra, Meesho, Jio, metro, railways, streaming and app subscriptions, loan NACH/ACH auto-debits, bank charges, card forex markup lines grouped with their purchase).
5. **Refunds**: a credit from a merchant matching an earlier debit. If a purchase is refunded in full, drop both from expenses and mention it.
6. **Shop QR codes**: genuine expense, category "Local shops (QR)".
7. **Everything else to an individual, cash, wallet loads, unrecognised large payments**: Review required.

Categories to use where the data supports them: Food & Dining, Groceries, Shopping, Transport, Fuel, Bills & Utilities, Rent, Loan EMI, Subscriptions, Entertainment, Healthcare, Education, Travel, Cash Withdrawal, Investments/Savings, Family Support, Bank Charges, Local shops (QR), Other. Do not invent merchant names or categories. Keep the original description beside every normalised name.

Money received from individuals is shown as an inflow, not netted against expenses. State that if it was repayment for shared bills, the user's own spending is lower by that amount.

## Step 4: Duplicate check

- A UPI reference appearing twice inside one account is a duplicate. Report it.
- The same reference in two different accounts is a self transfer, not a duplicate.
- Same payee + same amount + same day with different references are separate transactions (tickets, repeat purchases). Keep them separate and list them so the user can confirm.

## Step 5: Ask before finalising

This step is required. Once classification is done, collect the Review items and ask the user about the ones that move the totals. Do not ask about every small payment.

- Rank Review items by amount and by recurrence (same payee around the same day each month is probably rent, a shared bill, an EMI or family support).
- Ask about roughly the top 4 to 8 with the question tool, one question per payee, with concrete options such as: Rent or housing / Family support / Shared bill or flatmate / Loan given or repaid / Personal spending / Something else. Include the date, amount and any remark in the question.
- Also ask about: who a payee is when the guess rests on a clue (for example a name matching the address line), what smaller employer credits are, missing recurring debits (an EMI that stopped appearing), and any single unidentified merchant payment that is a large share of the period.
- Small leftover payments to individuals stay in Review with a single line total.
- If the user is not there to answer, finish with those items in Review, show totals both ways ("confirmed" and "if every review item is a cost"), and list the open questions at the top of the report.
- When the user answers, reclassify, recompute everything in code, and republish. Offer to save confirmed payee meanings into this skill so they are not asked again.

## Step 6: Compute

Define periods either by calendar month or by salary cycle (salary day up to the day before the next salary). Use whichever the user asks for; when they say "after salary", use cycles. Transactions on a salary day belong to the new cycle. Flag cycles of unequal length and give a per-day figure before comparing them.

For each period, across all accounts combined:

- Salary, other employer credits, received from individuals, interest/refunds/cashback
- Genuine expenses, Review required (out and in), Self transfers (excluded), Pass-through (excluded)
- Combined balance at start and end, and the change
- Salary left after confirmed expenses, and again if every Review item is a cost

Also produce: category table (amount, % of expense, count, ranked), top merchants, period-over-period comparison, and the unusual items list (large single payments, very frequent small payments with their total, category jumps, recurring subscriptions and overlaps, recurring debits that stopped, anything needing verification).

**Reconciliation is mandatory.** Opening balance + every inflow line - every outflow line must equal the statements' closing balance to the paisa. If it does not, find out why before publishing. Self transfers in and out should cancel; when they do not, name the unmatched leg.

Recount every figure quoted in prose from the data (counts as well as amounts). If a later message corrects an earlier number, say so plainly.

## Step 7: Deliver the HTML report

Publish as an artifact when that is available (load the artifact design guidance first); otherwise send a single self-contained .html file. Embed the classified data as JSON and render tables with script so every total is computed from the same rows.

Sections, in this order:

1. Headline answer and the open questions or caveats that change it
2. Period or salary-cycle cards
3. Category bars and table
4. Top merchants
5. Period comparison
6. Review required table with the reason each item needs a look
7. Unusual items
8. Duplicate check
9. Reconciliation table
10. "Where did my money go?" plain-language summary
11. 5 to 10 practical observations on habits and where spending could be cut
12. Assumptions
13. Full ledger: searchable, filterable by type and category, showing date, account, merchant, category, type, debit, credit and the original description, with a running row count and totals for the current filter

Colour-code the buckets consistently (expense, self transfer, review, pass-through, inflow) and support light and dark themes. Use Indian number grouping for rupees (₹1,28,300).

In the chat reply, give the headline numbers, the two or three things worth checking, and the open questions. Do not repeat the whole report.

## Things that go wrong

- Treating transfers to a parent or flatmate as self transfers. They are someone else's account: Family Support, Rent or Review, never Self transfer.
- Counting both legs of a self transfer, or counting it as income on the receiving side.
- Guessing what a QR-code shop sold from a truncated name.
- Comparing a 24-day cycle with a 32-day one without saying so.
- Presenting a period as complete when one account's statement ends earlier.
- Missing that a regular auto-debit did not happen, which makes a month look cheaper than it was.
- This is bookkeeping help, not financial advice. Give facts and observations; leave decisions to the user.
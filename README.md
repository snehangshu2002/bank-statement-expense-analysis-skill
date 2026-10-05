# Bank Statement Expense Analysis — a Claude skill

A skill that teaches Claude to turn bank statements into a reconciled answer to "where did my money go?", month by month or salary cycle by salary cycle.

## What it does

- Reads every transaction from PDF, CSV or XLSX statements in code, and checks each running balance and the bank's own totals before analysing anything.
- Sorts every transaction into one of five buckets: genuine expense, self transfer, review required, pass-through, or inflow. Money moved between your own accounts is never counted as spending.
- Matches the two legs of a transfer across statements by UPI reference number, and checks for duplicates.
- Asks you about the unclear payments that change the totals (large or recurring payments to individuals, cash, unidentified merchants) before finalising.
- Produces a clickable HTML report: period or salary-cycle cards, category and merchant tables, period comparison, unusual items, a reconciliation to the paisa, and a searchable ledger that keeps each original description.

It was written against Indian bank statements (SBI and PNB layouts, UPI descriptions, rupee formatting). The method works for other banks, but the parsing hints are UPI-specific.

## Install

**Claude apps:** zip the `bank-statement-expense-analysis` folder on its own and add it as a custom skill. The steps are in Anthropic's help centre at https://support.claude.com (search for "skills").

**Claude Code:** copy the folder into your skills directory.

```bash
git clone https://github.com/snehangshu2002/bank-statement-expense-analysis-skill.git
cp -r bank-statement-expense-analysis-skill/bank-statement-expense-analysis ~/.claude/skills/
```

## Use

Attach one or more statements and ask, for example:

> Analyse my bank statements for the last two months and show where my salary went after each credit.

Claude will extract and verify the rows, ask a handful of questions about payments it cannot classify, then give you the report.

## Privacy

Bank statements contain account numbers, addresses and the names of people you pay. This repository contains instructions only and no statement data. Do not commit your own statements or generated reports to a public repository.

## Not financial advice

The skill does bookkeeping: it reports facts and observations from your statements. Decisions are yours.

## License

MIT. See [LICENSE](LICENSE).

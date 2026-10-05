# Bank Statement Expense Analysis — a Claude skill

A skill that teaches Claude to turn bank statements into a proven answer to "what came in, what went out, and where did it go?", month by month or per income cycle.

It works for any account type: salaried, self-employed, business, freelance, pension or student. It does not assume a salary; it asks.

## What it does

- **Reads any bank's statement** (PDF, CSV or Excel). Columns are found by header keywords or by content, and debit/credit direction is taken from the running balance, so the same code handles separate Debit/Credit columns, a single Amount column with a DR/CR flag, and signed amounts.
- **Proves the extraction** by checking `previous balance - debit + credit = balance` on every row before analysing anything.
- **Sorts every transaction into one of six buckets:** genuine expense, self transfer, review required, pass-through, income, other inflow. Money moved between your own accounts is never counted as spending.
- **Matches the two sides of a transfer** across statements by payment reference, and checks for duplicates.
- **Asks you** about the unclear payments that change the totals before finalising.
- **Refuses to report if the books do not balance**, then writes a clickable HTML report: period cards, money in, expenses by category, top payees, period comparison, review table, checks, reconciliation and a searchable ledger that keeps every original description.

## What is in the folder

```
bank-statement-expense-analysis/
  SKILL.md                      step-by-step instructions, written so smaller models can follow them
  scripts/
    extract_statement.py        statements -> transactions.json (verified)
    analyze.py                  draft classification, questions to ask, overrides
    build_report.py             reconciliation gate + HTML report
```

The scripts also work on their own, without Claude:

```bash
pip install pdfplumber openpyxl
python3 scripts/extract_statement.py statement.pdf -o transactions.json
python3 scripts/analyze.py transactions.json -o classified.json --owner "YOUR NAME AS ON STATEMENT"
python3 scripts/build_report.py classified.json -o report.html
```

## Install

**Claude apps:** zip the `bank-statement-expense-analysis` folder on its own and add it as a custom skill. The steps are in Anthropic's help centre at https://support.claude.com (search for "skills").

**Claude Code:** copy the folder into your skills directory.

```bash
git clone https://github.com/snehangshu2002/bank-statement-expense-analysis-skill.git
cp -r bank-statement-expense-analysis-skill/bank-statement-expense-analysis ~/.claude/skills/
```

## Use

Attach one or more statements and ask, for example:

> Analyse my bank statements month by month and show where my money went.

## What it has been tested on

- Real SBI and PNB savings-account PDFs (India), including merging two overlapping statements of one account.
- Synthetic CSV layouts: separate debit/credit columns, a signed amount column listed newest first, and an amount column with a DR/CR flag and no balance.

Other banks' layouts usually work because direction comes from the balance, but this is not guaranteed. The merchant list is mostly Indian brands. Credit card statements, loan statements and scanned image PDFs (without OCR) are not handled. If a statement does not extract cleanly, please open an issue describing the column layout, with all personal data removed.

## Privacy

Bank statements contain account numbers, addresses and the names of people you pay. This repository contains instructions and code only. Do not commit your own statements or generated reports; the `.gitignore` blocks the usual file types.

## Not financial advice

The skill does bookkeeping: it reports facts and observations from your statements. Decisions are yours.

## License

MIT. See [LICENSE](LICENSE).

#!/usr/bin/env python3
"""Build the HTML report from classified.json (output of analyze.py).

Usage:
  python3 build_report.py classified.json -o report.html [--narrative narrative.json]

All numbers on the page are computed here from the transaction rows, so the
tables always agree with each other. The script refuses to write a report when
the books do not reconcile (opening + credits - debits != closing for an
account that has a running balance), unless --allow-unreconciled is given.

narrative.json (all keys optional, plain text, **bold** allowed):
  {"title": "Money Trail Apr-Jun 2025",          # 2-4 word page name
   "headline": "One sentence answer",
   "headline_note": "The caveat that changes the answer",
   "open_questions": ["..."], "summary": ["paragraph", "..."],
   "unusual": ["..."], "observations": ["..."], "assumptions": ["..."],
   "review_reasons": {"PAYEE LABEL": "why this needs a look"}}
"""
import argparse, datetime as dt, html, json, re, sys
from collections import defaultdict

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('classified')
ap.add_argument('-o', '--out', default='report.html')
ap.add_argument('--narrative')
ap.add_argument('--allow-unreconciled', action='store_true')
a = ap.parse_args()
C = json.load(open(a.classified))
N = json.load(open(a.narrative)) if a.narrative else {}
if 'periods' not in C or not C['transactions'] or 'bucket' not in C['transactions'][0]:
    sys.exit('This file is not classified yet. Run analyze.py on it first and pass its output here.')
TX, ACC, PER = C['transactions'], C['accounts'], C['periods']
BUCKETS = ('EXPENSE', 'SELF', 'REVIEW', 'PASS', 'INCOME', 'INFLOW')
bad = [t for t in TX if t['bucket'] not in BUCKETS]
if bad:
    sys.exit(f"Unknown bucket {bad[0]['bucket']!r} on {bad[0]['date']} {bad[0]['description'][:40]}")
r2 = lambda v: round(v + 0.0, 2)

# ---- reconciliation gate ---------------------------------------------------------------------
recon, ok = [], True
for x in ACC:
    rows = [t for t in TX if t['account'] == x['label']]
    cr, dr = r2(sum(t['credit'] for t in rows)), r2(sum(t['debit'] for t in rows))
    if x['opening'] is None or x['closing'] is None:
        recon.append(dict(label=x['label'], opening=None, credits=cr, debits=dr, calc=None, closing=None, diff=None))
        continue
    calc = r2(x['opening'] + cr - dr)
    diff = r2(calc - x['closing'])
    ok &= abs(diff) < 0.011
    recon.append(dict(label=x['label'], opening=x['opening'], credits=cr, debits=dr, calc=calc, closing=x['closing'], diff=diff))
print('RECONCILIATION')
for r in recon:
    print(f"  {r['label']}: opening {r['opening']} + credits {r['credits']} - debits {r['debits']} = {r['calc']} | statement closing {r['closing']} | diff {r['diff']}")
if not ok and not a.allow_unreconciled:
    sys.exit('NOT RECONCILED: a row is missing, duplicated or has the wrong sign. Fix extraction before reporting.')


def tot(rows):
    S = lambda b, k: r2(sum(t[k] for t in rows if t['bucket'] == b))
    d = dict(income=S('INCOME', 'credit'), inflow=S('INFLOW', 'credit'), expense=S('EXPENSE', 'debit'),
             review_out=S('REVIEW', 'debit'), review_in=S('REVIEW', 'credit'), self_out=S('SELF', 'debit'),
             self_in=S('SELF', 'credit'), pass_out=S('PASS', 'debit'), pass_in=S('PASS', 'credit'),
             n_expense=sum(1 for t in rows if t['bucket'] == 'EXPENSE'),
             credits=r2(sum(t['credit'] for t in rows)), debits=r2(sum(t['debit'] for t in rows)))
    d['net'] = r2(d['credits'] - d['debits'])
    cats = defaultdict(lambda: [0.0, 0])
    for t in rows:
        if t['bucket'] == 'EXPENSE':
            cats[t['category']][0] += t['debit']; cats[t['category']][1] += 1
    d['cats'] = {k: [r2(v[0]), v[1]] for k, v in cats.items()}
    return d


def combined_balance(day, before=True):
    """Sum of every account's balance just before `day` (or at the end of `day`)."""
    s = 0.0
    for x in ACC:
        if x['opening'] is None:
            return None
        bal = x['opening']
        for t in TX:
            if t['account'] == x['label'] and (t['date'] < day if before else t['date'] <= day):
                bal = bal - t['debit'] + t['credit']
        s += bal
    return r2(s)


periods = []
for p in PER:
    rows = [t for t in TX if p['start'] <= t['date'] <= p['end']]
    d = tot(rows)
    days = (dt.date.fromisoformat(p['end']) - dt.date.fromisoformat(p['start'])).days + 1
    d.update(name=p['name'], start=p['start'], end=p['end'], days=days,
             open=combined_balance(p['start'], True), close=combined_balance(p['end'], False))
    periods.append(d)
ALL = tot(TX)
merch = defaultdict(lambda: [0.0, 0, ''])
for t in TX:
    if t['bucket'] == 'EXPENSE':
        m = merch[t['label']]; m[0] += t['debit']; m[1] += 1; m[2] = t['category']
merchants = [[k, v[2], r2(v[0]), v[1]] for k, v in sorted(merch.items(), key=lambda kv: -kv[1][0])][:25]
rev = defaultdict(lambda: dict(out=0.0, inn=0.0, n=0, dates=[], hint=''))
for t in TX:
    if t['bucket'] == 'REVIEW':
        r = rev[t['label']]; r['out'] += t['debit']; r['inn'] += t['credit']; r['n'] += 1; r['dates'].append(t['date']); r['hint'] = t.get('hint', '')
reasons = N.get('review_reasons', {})
review = [[k, r2(v['out']), r2(v['inn']), v['n'], reasons.get(k) or v['hint'], v['dates'][:4]]
          for k, v in sorted(rev.items(), key=lambda kv: -(kv[1]['out'] + kv[1]['inn']))]
income = defaultdict(lambda: [0.0, 0])
for t in TX:
    if t['bucket'] in ('INCOME', 'INFLOW'):
        k = ('Income: ' if t['bucket'] == 'INCOME' else 'Other: ') + t['category']
        income[k][0] += t['credit']; income[k][1] += 1
inflows = [[k, r2(v[0]), v[1]] for k, v in sorted(income.items(), key=lambda kv: (kv[0][:1] != 'I', -kv[1][0]))]

start, end = min(t['date'] for t in TX), max(t['date'] for t in TX)
fmt = lambda s: dt.date.fromisoformat(s).strftime('%-d %b %Y')
title = N.get('title') or f"Money Trail {dt.date.fromisoformat(start).strftime('%b')}–{dt.date.fromisoformat(end).strftime('%b %Y')}"
auto = C.get('auto', {})
data = dict(meta=C['meta'], title=title, range=[start, end], accounts=ACC, recon=recon, periods=periods, all=ALL,
            merchants=merchants, review=review, inflows=inflows, auto=auto,
            narrative={k: N.get(k) for k in ('headline', 'headline_note', 'open_questions', 'summary', 'unusual', 'observations', 'assumptions')},
            ledger=[[t['date'], t['account'], t['description'], t['label'], t['category'], t['bucket'], t['debit'], t['credit']]
                    for t in sorted(TX, key=lambda t: (t['date'], t['account'], t['seq']))])

TEMPLATE = r'''<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column like a passbook audit. Summary first, periods next, full ledger last. */
:root{--bg:#f3f5f4;--panel:#fff;--fg:#17211f;--muted:#5d6b68;--line:#d5dcda;--accent:#0b5d57;--exp:#a23b2a;--self:#2f5f9e;--rev:#9a6a00;--non:#6a5a8c;--inc:#1d7a45;--bar:#dfe6e4;
--display:"IBM Plex Sans Condensed","Arial Narrow",sans-serif;--body:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111716;--panel:#19211f;--fg:#e4ebe9;--muted:#93a29f;--line:#2c3836;--accent:#5fc4b8;--exp:#f08a76;--self:#86b2ee;--rev:#e2b34a;--non:#b4a3dc;--inc:#6fcf97;--bar:#26312f;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#111716;--panel:#19211f;--fg:#e4ebe9;--muted:#93a29f;--line:#2c3836;--accent:#5fc4b8;--exp:#f08a76;--self:#86b2ee;--rev:#e2b34a;--non:#b4a3dc;--inc:#6fcf97;--bar:#26312f;color-scheme:dark}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 var(--body)}
.wrap{max-width:980px;margin:0 auto;padding-inline:20px;padding-block:32px 64px;display:flex;flex-direction:column;gap:36px}
h1{font:600 34px/1.1 var(--display);margin:0;text-wrap:balance}
h2{font:600 22px/1.2 var(--display);margin:0 0 4px;text-wrap:balance}
h3{font:600 15px/1.3 var(--body);margin:0}
p{margin:0;max-width:68ch}.muted{color:var(--muted)}.small{font-size:13px}
section{display:flex;flex-direction:column;gap:14px;min-width:0}
.eyebrow{font:500 12px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
td.n,th.n,.num{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.tw{overflow-x:auto;border:1px solid var(--line);background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font:500 11.5px var(--mono);letter-spacing:.05em;text-transform:uppercase;color:var(--muted);white-space:nowrap}
tr:last-child td{border-bottom:0}tr.tot td{font-weight:600;border-top:2px solid var(--fg)}
.cycles{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}
.cyc{background:var(--panel);border:1px solid var(--line);padding:16px;display:flex;flex-direction:column;gap:10px;min-width:0}
.cyc dl{margin:0;display:grid;grid-template-columns:1fr auto;gap:5px 12px;font-size:13.5px}
.cyc dt{color:var(--muted)}.cyc dd{margin:0;font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right}
.cyc .big{font:500 24px var(--mono)}.rule{grid-column:1/-1;border-top:1px solid var(--line);margin:3px 0}
.bars{display:flex;flex-direction:column;gap:5px}
.b{display:grid;grid-template-columns:minmax(110px,190px) 1fr 96px;gap:10px;align-items:center;font-size:13px}
.b .t{height:12px;background:var(--bar)}.b .f{height:100%;background:var(--exp)}
.pill{display:inline-block;font:500 11px var(--mono);padding:1px 6px;border:1px solid currentColor;white-space:nowrap}
.EXPENSE{color:var(--exp)}.SELF{color:var(--self)}.REVIEW{color:var(--rev)}.PASS{color:var(--non)}.INCOME,.INFLOW{color:var(--inc)}
ul,ol{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:8px;max-width:72ch}
.note{border-left:3px solid var(--rev);padding:10px 14px;background:var(--panel);display:flex;flex-direction:column;gap:8px}
.ctl{display:flex;flex-wrap:wrap;gap:8px}
input,select{font:14px var(--body);padding:6px 8px;border:1px solid var(--line);background:var(--panel);color:var(--fg);min-width:0}
input:focus-visible,select:focus-visible{outline:2px solid var(--accent)}
#led td.d{font:12px var(--mono);color:var(--muted);max-width:330px;overflow-wrap:anywhere}
.legend{display:flex;flex-wrap:wrap;gap:8px 14px;font-size:13px}
</style>
<div class="wrap">
<header style="display:flex;flex-direction:column;gap:10px"><div class="eyebrow" id="eyebrow"></div><h1 id="h1"></h1><p class="muted" id="lede"></p>
<div class="legend"><span class="pill EXPENSE">GENUINE EXPENSE</span><span class="pill SELF">SELF TRANSFER</span><span class="pill REVIEW">REVIEW REQUIRED</span><span class="pill PASS">PASS-THROUGH</span><span class="pill INCOME">INCOME / INFLOW</span></div></header>
<section id="s-head"><div class="eyebrow">Read this first</div><h2 id="headline"></h2><div class="note" id="note" hidden></div><div class="tw"><table id="hero"></table></div></section>
<section><div class="eyebrow">Periods</div><h2>Period by period</h2><p class="muted small">Balances are all accounts combined, so money moved between your own accounts does not change them.</p><div class="cycles" id="cycles"></div></section>
<section><div class="eyebrow">Money in</div><h2>Where money came from</h2><div class="tw"><table id="inf"></table></div></section>
<section><div class="eyebrow">Money out</div><h2>Confirmed expenditure by category</h2><p class="muted small">Self transfers, pass-throughs and review items are excluded.</p><div class="bars" id="bars"></div><div class="tw"><table id="cat"></table></div></section>
<section><div class="eyebrow">Merchants</div><h2>Top payees</h2><div class="tw"><table id="mer"></table></div></section>
<section id="s-cmp"><div class="eyebrow">Comparison</div><h2>Period against period</h2><div class="tw"><table id="cmp"></table></div><p class="muted small">Periods differ in length. Read the per-day row before comparing totals.</p></section>
<section id="s-rev"><div class="eyebrow">Review required</div><h2>Payments that could not be classified</h2><div class="tw"><table id="rev"></table></div></section>
<section id="s-unusual"><div class="eyebrow">Unusual items</div><h2>What stands out</h2><ul id="unusual"></ul></section>
<section><div class="eyebrow">Checks</div><h2>Duplicates and coverage</h2><ul id="checks"></ul></section>
<section><div class="eyebrow">Reconciliation</div><h2>Opening balance to closing balance</h2><div class="tw"><table id="rec"></table></div><div class="tw"><table id="rec2"></table></div></section>
<section id="s-sum"><div class="eyebrow">Summary</div><h2>Where did the money go?</h2><div id="summary" style="display:flex;flex-direction:column;gap:10px"></div></section>
<section id="s-obs"><div class="eyebrow">Observations</div><h2>Spending habits</h2><ol id="obs"></ol></section>
<section id="s-asm"><div class="eyebrow">Assumptions</div><h2>How things were classified</h2><ul id="asm"></ul></section>
<section><div class="eyebrow">Ledger</div><h2>All transactions</h2>
<div class="ctl"><input id="q" type="search" placeholder="Search description or payee" aria-label="Search"><select id="fb" aria-label="Type"><option value="">All types</option><option value="EXPENSE">Genuine expense</option><option value="SELF">Self transfer</option><option value="REVIEW">Review required</option><option value="PASS">Pass-through</option><option value="INCOME">Income</option><option value="INFLOW">Other inflow</option></select><select id="fc" aria-label="Category"><option value="">All categories</option></select><select id="fp" aria-label="Period"><option value="">All periods</option></select><span class="muted small" id="cnt" style="align-self:center"></span></div>
<div class="tw" style="max-height:640px;overflow:auto"><table id="led"></table></div></section>
</div>
<script>
const D=__DATA__;
const CUR=D.meta.currency||'',LOC=D.meta.locale||'en-IN';
const R=n=>n==null?'n/a':(n<0?'−':'')+CUR+Math.abs(n).toLocaleString(LOC,{maximumFractionDigits:0});
const R2=n=>n==null?'n/a':(n<0?'−':'')+CUR+Math.abs(n).toLocaleString(LOC,{minimumFractionDigits:2,maximumFractionDigits:2});
const fd=s=>new Date(s+'T00:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short'});
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const rich=s=>esc(s).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
const list=(id,sec,arr)=>{if(arr&&arr.length)$(id).innerHTML=arr.map(s=>'<li>'+rich(s)+'</li>').join('');else if(sec)$(sec).hidden=true};
const A=D.all,P=D.periods,L=D.ledger,NV=D.narrative;
$('eyebrow').textContent=D.accounts.map(a=>a.label).join(' + ')+' · '+fd(D.range[0])+' – '+fd(D.range[1])+' '+D.range[1].slice(0,4);
$('h1').textContent=D.title;
$('lede').textContent=L.length+' transactions read from '+D.accounts.length+' account'+(D.accounts.length>1?'s':'')+'. '+(D.accounts.every(a=>a.verified)?'Every row was checked against the bank\'s running balance.':'Some rows could not be checked against a running balance; see Checks.');
$('headline').textContent=NV.headline||('Confirmed spending '+R(A.expense)+', with '+R(A.review_out)+' still to classify');
const nb=[];if(NV.headline_note)nb.push('<p>'+rich(NV.headline_note)+'</p>');
if(NV.open_questions&&NV.open_questions.length)nb.push('<p><b>Open questions</b></p><ul>'+NV.open_questions.map(q=>'<li>'+rich(q)+'</li>').join('')+'</ul>');
if(nb.length){$('note').hidden=false;$('note').innerHTML=nb.join('')}
const pill=(b,t)=>`<span class="pill ${b}">${t}</span> `;
$('hero').innerHTML=`<tr><th>Whole period, all accounts</th><th class="n">Amount</th></tr>
<tr><td>${pill('INCOME','IN')}Income</td><td class="n">${R2(A.income)}</td></tr>
<tr><td>${pill('INFLOW','IN')}Other money in</td><td class="n">${R2(A.inflow)}</td></tr>
<tr><td>${pill('EXPENSE','A')}Genuine expenditure, confirmed</td><td class="n">${R2(A.expense)}</td></tr>
<tr><td>${pill('REVIEW','C')}Review required, paid out${A.review_in?' (and '+R(A.review_in)+' received)':''}</td><td class="n">${R2(A.review_out)}</td></tr>
<tr><td>${pill('SELF','B')}Self transfers, excluded</td><td class="n">${R2(A.self_out)}</td></tr>
<tr><td>${pill('PASS','·')}Pass-through, excluded</td><td class="n">${R2(A.pass_out)}</td></tr>`;
$('cycles').innerHTML=P.map(c=>`<div class="cyc"><h3>${esc(c.name)}</h3><div class="muted small">${fd(c.start)} – ${fd(c.end)} · ${c.days} days</div>
<div><div class="muted small">Income received</div><div class="big">${R(c.income)}</div></div><dl>
<dt>Other money in</dt><dd>${R2(c.inflow)}</dd><div class="rule"></div>
<dt class="EXPENSE">Genuine expenditure</dt><dd>${R2(c.expense)}</dd><dt class="REVIEW">Review required (out)</dt><dd>${R2(c.review_out)}</dd>${c.review_in?`<dt class="REVIEW">Review required (in)</dt><dd>${R2(c.review_in)}</dd>`:''}
<dt class="SELF">Self transfers out / in</dt><dd>${R(c.self_out)} / ${R(c.self_in)}</dd><dt class="PASS">Pass-through out / in</dt><dd>${R(c.pass_out)} / ${R(c.pass_in)}</dd><div class="rule"></div>
<dt>Combined balance at start</dt><dd>${R2(c.open)}</dd><dt>Combined balance at end</dt><dd>${R2(c.close)}</dd><dt>Net change (all in − all out)</dt><dd>${R2(c.net)}</dd>
<dt>Income left after confirmed expenses</dt><dd>${R2(c.income-c.expense)}</dd><dt>…and if every review item is a cost</dt><dd>${R2(c.income-c.expense-c.review_out+c.review_in)}</dd></dl></div>`).join('');
$('inf').innerHTML='<tr><th>Source</th><th class="n">Amount</th><th class="n">Credits</th></tr>'+(D.inflows.length?D.inflows.map(r=>`<tr><td>${esc(r[0])}</td><td class="n">${R2(r[1])}</td><td class="n">${r[2]}</td></tr>`).join(''):'<tr><td colspan="3">No income or other inflows classified.</td></tr>')+`<tr class="tot"><td>Total (excluding self transfers and pass-through)</td><td class="n">${R2(A.income+A.inflow)}</td><td class="n"></td></tr>`;
const cl=Object.entries(A.cats).sort((x,y)=>y[1][0]-x[1][0]),mx=cl.length?cl[0][1][0]:1;
$('bars').innerHTML=cl.map(([k,v])=>`<div class="b"><span>${esc(k)}</span><div class="t"><div class="f" style="width:${(v[0]/mx*100).toFixed(1)}%"></div></div><span class="num">${R(v[0])}</span></div>`).join('');
$('cat').innerHTML='<tr><th>Category</th><th class="n">Amount</th><th class="n">% of expense</th><th class="n">Transactions</th></tr>'+cl.map(([k,v])=>`<tr><td>${esc(k)}</td><td class="n">${R2(v[0])}</td><td class="n">${A.expense?(v[0]/A.expense*100).toFixed(1):'0.0'}%</td><td class="n">${v[1]}</td></tr>`).join('')+`<tr class="tot"><td>Total genuine expenditure</td><td class="n">${R2(A.expense)}</td><td class="n">100%</td><td class="n">${A.n_expense}</td></tr>`;
$('mer').innerHTML='<tr><th>Payee</th><th>Category</th><th class="n">Total spent</th><th class="n">Transactions</th></tr>'+D.merchants.map(m=>`<tr><td>${esc(m[0])}</td><td>${esc(m[1])}</td><td class="n">${R2(m[2])}</td><td class="n">${m[3]}</td></tr>`).join('');
if(P.length<2)$('s-cmp').hidden=true;else{const Q=P.slice(-6),rows=[['Income',c=>c.income],['Other money in',c=>c.inflow],['Genuine expenses',c=>c.expense],['Genuine expenses per day',c=>c.expense/c.days],['Review required (out)',c=>c.review_out],['Self transfers (out)',c=>c.self_out]];
const ks=[...new Set(Q.flatMap(c=>Object.keys(c.cats)))].sort((x,y)=>Q.reduce((s,c)=>s+(c.cats[y]||[0])[0],0)-Q.reduce((s,c)=>s+(c.cats[x]||[0])[0],0));
ks.forEach(k=>rows.push(['· '+k,c=>(c.cats[k]||[0])[0]]));
const ch=(x,y)=>x?((y-x)/x>=0?'+':'−')+Math.abs((y-x)/x*100).toFixed(0)+'%':(y?'new':'–');
$('cmp').innerHTML='<tr><th>Metric</th>'+Q.map(c=>`<th class="n">${esc(c.name)}<br>${c.days} d</th>`).join('')+'<th class="n">Last change</th></tr>'+rows.map(r=>`<tr><td>${esc(r[0])}</td>`+Q.map(c=>`<td class="n">${R(r[1](c))}</td>`).join('')+`<td class="n">${ch(r[1](Q[Q.length-2]),r[1](Q[Q.length-1]))}</td></tr>`).join('')}
if(!D.review.length)$('s-rev').hidden=true;else $('rev').innerHTML='<tr><th>Payee (as on statement)</th><th class="n">Paid out</th><th class="n">Received</th><th class="n">Count</th><th>Why it needs a look</th></tr>'+D.review.map(r=>`<tr><td>${esc(r[0])}</td><td class="n">${R2(r[1])}</td><td class="n">${r[2]?R2(r[2]):''}</td><td class="n">${r[3]}</td><td class="small">${esc(r[4])}${r[3]<=4?' · '+r[5].map(fd).join(', '):''}</td></tr>`).join('')+`<tr class="tot"><td>Total</td><td class="n">${R2(A.review_out)}</td><td class="n">${R2(A.review_in)}</td><td></td><td></td></tr>`;
list('unusual','s-unusual',NV.unusual);list('obs','s-obs',NV.observations);list('asm','s-asm',NV.assumptions);
const au=D.auto||{},ck=[];
ck.push(au.duplicates&&au.duplicates.length?'**Possible duplicates inside one account:** '+au.duplicates.join('; '):'**No transaction is duplicated inside one account.** Every payment reference is unique within its statement.');
if(au.same_day_repeats&&au.same_day_repeats.length)ck.push('**Same payee, same amount, same day** (kept as separate payments because each has its own reference): '+au.same_day_repeats.join('; '));
(au.coverage||[]).forEach(c=>ck.push('**Coverage:** '+c));(au.missing_recurring||[]).forEach(c=>ck.push('**Recurring debit that stopped:** '+c));
list('checks',null,ck);
$('rec').innerHTML='<tr><th>Account</th><th class="n">Opening</th><th class="n">+ Credits</th><th class="n">− Debits</th><th class="n">= Calculated</th><th class="n">Statement closing</th><th class="n">Difference</th></tr>'+D.recon.map(r=>`<tr><td>${esc(r.label)}</td><td class="n">${R2(r.opening)}</td><td class="n">${R2(r.credits)}</td><td class="n">${R2(r.debits)}</td><td class="n">${R2(r.calc)}</td><td class="n">${R2(r.closing)}</td><td class="n">${R2(r.diff)}</td></tr>`).join('');
const o=D.recon.every(r=>r.opening!=null)?D.recon.reduce((s,r)=>s+r.opening,0):null,c=D.recon.every(r=>r.closing!=null)?D.recon.reduce((s,r)=>s+r.closing,0):null;
const rr=[['Opening balance, all accounts',o],['+ Income',A.income],['+ Other money in',A.inflow],['+ Review items received',A.review_in],['+ Pass-through received',A.pass_in],['+ Self transfers in',A.self_in],['− Genuine expenses',-A.expense],['− Review required paid out',-A.review_out],['− Pass-through paid out',-A.pass_out],['− Self transfers out',-A.self_out]];
const calc=o==null?null:rr.reduce((s,r)=>s+r[1],0);
$('rec2').innerHTML='<tr><th>By type of movement</th><th class="n">Amount</th></tr>'+rr.map(r=>`<tr><td>${r[0]}</td><td class="n">${R2(r[1])}</td></tr>`).join('')+`<tr class="tot"><td>Calculated closing balance</td><td class="n">${R2(calc)}</td></tr><tr><td>Statement closing balance, all accounts</td><td class="n">${R2(c)}</td></tr><tr><td>Difference</td><td class="n">${calc==null||c==null?'n/a':R2(Math.round((calc-c)*100)/100)}</td></tr>`+(Math.abs(A.self_in-A.self_out)>0.01?`<tr><td class="small muted" colspan="2">Self transfers in and out differ by ${R2(Math.abs(A.self_in-A.self_out))}: at least one leg falls outside the statements supplied, or went to a wallet or investment (see Checks).</td></tr>`:'');
if(NV.summary&&NV.summary.length)$('summary').innerHTML=NV.summary.map(s=>'<p>'+rich(s)+'</p>').join('');else{const top=cl.slice(0,6);
$('summary').innerHTML=`<p>You received <b>${R(A.income)}</b> in income and ${R(A.inflow)} in other inflows.</p><p><b>${R(A.expense)}</b> is confirmed spending:</p><ol>${top.map(([k,v])=>`<li>${esc(k)}: ${R(v[0])}</li>`).join('')}</ol><p><b>${R(A.review_out)}</b> went to payees that still need classifying.</p><p><b>${R(A.self_out)}</b> moved between your own accounts and <b>${R(A.pass_out)}</b> passed through; both are excluded from expenditure.</p>`}
const lab={EXPENSE:'EXPENSE',SELF:'SELF TRANSFER',REVIEW:'REVIEW',PASS:'PASS-THROUGH',INCOME:'INCOME',INFLOW:'INFLOW'};
[...new Set(L.map(x=>x[4]))].sort().forEach(v=>{const op=document.createElement('option');op.textContent=v;$('fc').appendChild(op)});
P.forEach((p,i)=>{const op=document.createElement('option');op.value=i;op.textContent=p.name;$('fp').appendChild(op)});
function draw(){const q=$('q').value.toLowerCase(),fb=$('fb').value,fc=$('fc').value,fp=$('fp').value,pp=fp===''?null:P[+fp];
const r=L.filter(x=>(!q||(x[2]+' '+x[3]).toLowerCase().includes(q))&&(!fb||x[5]==fb)&&(!fc||x[4]==fc)&&(!pp||(x[0]>=pp.start&&x[0]<=pp.end)));
$('cnt').textContent=r.length+' rows · out '+R2(r.reduce((s,x)=>s+x[6],0))+' · in '+R2(r.reduce((s,x)=>s+x[7],0));
$('led').innerHTML='<tr><th>Date</th><th>Account</th><th>Payee</th><th>Category</th><th>Type</th><th class="n">Debit</th><th class="n">Credit</th><th>Original description</th></tr>'+r.map(x=>`<tr><td style="white-space:nowrap">${fd(x[0])}</td><td style="white-space:nowrap">${esc(x[1])}</td><td>${esc(x[3])}</td><td>${esc(x[4])}</td><td><span class="pill ${x[5]}">${lab[x[5]]}</span></td><td class="n">${x[6]?R2(x[6]):''}</td><td class="n">${x[7]?R2(x[7]):''}</td><td class="d">${esc(x[2])}</td></tr>`).join('')}
['q','fb','fc','fp'].forEach(i=>$(i).addEventListener('input',draw));draw();
</script>
'''
page = TEMPLATE.replace('__TITLE__', html.escape(title)).replace(
    '__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
open(a.out, 'w', encoding='utf-8').write(page)
print(f"\nWrote {a.out} ({len(page)//1024} KB)")
print(f"TOTALS income {ALL['income']} | other in {ALL['inflow']} | expense {ALL['expense']} ({ALL['n_expense']} rows) | "
      f"review out {ALL['review_out']} in {ALL['review_in']} | self out {ALL['self_out']} in {ALL['self_in']} | pass out {ALL['pass_out']} in {ALL['pass_in']}")
print('Quote only these numbers (and the per-period ones on the page) in your reply.')

# Income vs Spend — how the numbers are calculated (and why they look the way they do)

You asked a very fair question:

> If income itself was ₹57L, how can expense be ₹74L? Income must be greater than
> expense if I'm thinking right, correct?

Short answer: **the original ₹74L "expense" was overstated** because it lumped in
money that wasn't really *spent* — money you moved to your own family as savings,
money you invested, and money that left one account but came back. After
separating those out, the picture is consistent again. This document shows every
step so you can verify it by hand.

---

## 1. The two different things people call "income" and "expense"

There are **two** money-in numbers and they are not the same:

| Term | Meaning |
|---|---|
| **All money received** | Every credit in your statements that isn't a self-transfer or duplicate. Includes salary **plus** money friends/family returned, loan disbursals, investment redemptions, insurance claims, cashbacks. |
| **Real income** | Only genuine *earnings*: salary (KoiReader), freelancing (Primus), tax refunds, interest, insurance claim. A **subset** of "all money received". |

So "real income ₹57L" is deliberately **narrow** — it's what you *earned*, not
everything that landed in your account. Comparing it directly to total spending is
apples-to-oranges. The right comparison is either:

- **All money in vs all money out** (the "Net (real)" line), or
- **Real income vs real expense** (after savings/investments are removed from
  spending).

Both now reconcile.

---

## 2. The corrected breakdown (current data: ICICI + HDFC, 4,511 rows, 2021–2026)

Starting from the raw statements:

```
Raw credits  ≈ ₹1.01 Cr        Raw debits ≈ ₹1.01 Cr      (looks huge, double-counted)

  − Self-transfers   ₹44.5L  (431 rows)   money between YOUR OWN accounts
  − Exact duplicates ₹0.31L  (11 rows)    same row in two overlapping exports
  ───────────────────────────────────────────────────────────────────────
  = Real money in    ₹84.5L                Real money out   ₹77.3L
```

Now split the two "real" sides by **what the money actually was**:

```
REAL MONEY IN  ₹84.5L
   ├─ Real income (earned)            ₹57.0L   salary 52.4 + freelance 3.2 + refunds 1.4 + claim 2.0 ...
   └─ Other receipts                  ₹27.5L   money returned by people, loan disbursals,
                                               investment redemptions, etc. (NOT earnings)

REAL MONEY OUT ₹77.3L
   ├─ Real expense (consumption)      ₹48.4L   food, rent, shopping, bills, medical, Benazir, ...
   ├─ Invested / saved                ₹3.2L    Groww, Zerodha, SGB, PPF, NPS (savings, not spend)
   └─ Family savings (mother+sister)  ₹22.7L   money parked with Husna/Zarinne as FDs
                                               (your "self-investment" — not consumption)
```

**Net (real) = Real money in − Real money out = ₹84.5L − ₹77.3L = +₹8.8L.**

So you are **net positive** over the period. And once savings/investments are
removed from "spending":

> **Real income ₹57.0L  >  Real expense ₹48.4L.** Income is greater than expense,
> exactly as you expected.

The earlier "expense ₹74L" simply hadn't yet pulled out the ₹22.7L you moved to
your mother and sister (treated as savings now) — that single change is what
flips the comparison back to normal.

---

## 3. What "Net (real)" means

> **Net (real) = all real money received − all real money paid out**, where
> "real" excludes self-transfers (moving money between your own ICICI/HDFC/PNB/SBI
> accounts and your own Paytm handles) and exact duplicate rows.

It is the honest "did my net cash position go up or down" number across the
external world. It is **not** income−expense; it counts every receipt and every
payment, including investments and family transfers. Here it is **+₹8.8L**.

---

## 4. Why "real money out" can still exceed "real income" in raw terms

Even ₹77.3L out vs ₹57L earned is normal, because spending is funded by **more
than this period's salary**:

1. **Family savings & investments (₹25.9L).** Moving money to your mother/sister
   as FDs, or into Groww/PPF/SGB, leaves your account but is **not consumed**.
   It's still yours. Excluded from "real expense".
2. **Money that came back (₹27.5L of receipts).** Friends/family returning money,
   investment redemptions, and the ICICI Lombard claim all add to money-in
   without being "income", and they fund further payments.
3. **Credit-card bill payments.** A CC bill paid from your bank is a debit, but
   the underlying purchases were made earlier on the card — the bank only sees the
   lump-sum repayment, so timing makes spend look concentrated.
4. **Cash withdrawals.** ATM cash is a debit; what it was spent on isn't tracked.
5. **Missing accounts (PNB / SBI).** Some payments (notably several to Benazir)
   were sent from PNB/SBI accounts whose statements aren't loaded yet. Those
   appear here only as **manual entries** (recalled), flagged on the Extraction
   view as missing-bank data to fill later.

---

## 4a. Paytm reconciliation (added Jan 2024 onward)

Paytm is a UPI front-end on top of your bank accounts, so its statement overlaps
the bank statements. We reconcile precisely using the **UPI Ref No. (NPCI RRN)**,
which is identical in Paytm and the bank narration:

- **Funded by ICICI / HDFC** → the row already exists in those statements
  (matched by RRN). It is **dropped** to avoid double counting, but its richer
  Paytm payee (e.g. "to Benazir 8617663869@paytm") is used to **improve
  detection** — without changing the transaction's identity. (~1,700 rows.)
- **Funded by PNB / SBI / a credit card / UPI-Lite** → these are **not** in any
  loaded statement, so they are **added** as new transactions. (~830 rows.)

This is what let the recalled Benazir payments finally reconcile — most of the
"missing" ones were sent from **PNB/SBI**, which only Paytm reveals.

**Why "Net (real)" can look negative after adding Paytm.** We now see the
*outflows* from PNB/SBI and the *spends* on your credit cards — but **not** the
*inflows* into PNB/SBI, nor the credit-card statements. So money-out is more
complete than money-in, which pushes the net down. It is a **data-completeness
gap, not double counting** (income is unchanged at ₹57L; ICICI/HDFC overlaps were
deduped). Loading PNB/SBI statements would restore the balance.

## 5. How to verify each number yourself

| Claim | Where to check |
|---|---|
| Salary ₹52.4L from KoiReader | **Income** tab → "KoiReader Technologies" section (60 payments). Matches your LPA: 7.5→8→9.5→15→24.3. |
| Self-transfers ₹44.5L excluded | **Ledger** → untick "Hide self-transfers"; the dimmed rows are the excluded ones. |
| Family savings ₹22.7L | **Family** tab → Mother (sent ₹13.3L) + Sister (sent ₹9.4L). Override the "saved" figure if some was spent on home. |
| Investments ₹3.2L | **Investments** tab → by instrument. |
| Accident claim ₹2.0L | **Accident & Marriage** tab → ICICI Lombard credit. |
| Benazir net ~−₹9.9L | **Benazir** tab → summary cards + sections (iPhone, laptop, Zara, Axis loan, studies). |
| Approved vs unverified | **Summary** tab → status bar (auto-classified rows are *unverified* until you confirm ✓ each). |

---

## 6. One caveat on family savings

Money sent to your **mother (Husna)** and **sister (Zarinne)** is treated as
**self-investment** by default (they keep it as FDs in their own name), and is
therefore **excluded from "real expense"**. But you noted some of it is used for
**home expenses**. On the **Family** tab each person has an override:

- Default **"saved"** = net sent to them.
- Overwrite it with the amount actually saved; the remainder is then effectively
  home spending. Only you can set this — the app never guesses the split.

If you decide a large share was home spending, move it back into expense by
lowering the "saved" figure; the Summary totals update accordingly.

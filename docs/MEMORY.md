# Project Memory & Context

This file records the human context behind the ledger. **It is seed information
to help you review — not automatic proof of anything.** Verify every transaction
yourself in the dashboard. The software makes no legal or financial conclusions.

---

## Purpose

Document and organise transactions that involve, or were made on behalf of:

- **Benazir Rahaman** — the relevant person.
- **Nazrana / Najrana** — Benazir's mother. The name has several spellings
  (Nazrana, Najrana, with/without "Khatun"/"Khatoon"); all are treated as
  aliases for the same person.

The account holder is **Farhan Hai Khan** (these are his ICICI and HDFC
statements).

## What we are trying to see

- money **paid out** to / for these people,
- money **received** from them,
- amounts that may have been taken, given, repaid, owed, or are unclear,
- a written reason/comment for each classification,
- flags for manual review, "unknown", and "do not remember",
- manual entries for payments that don't show the person's name directly.

## Remembered context (seed only — confirm before relying on it)

- There may be **payments made on Benazir's behalf** that do **not** mention her
  in the narration. A noted example is a **Kotak Life Insurance** payment. Record
  these as **manual entries** and link them to the originating bank transaction.
- There may be **repayment** context (money expected back, or already repaid).
  The app does **not** assume this. Mark repayments yourself using the
  `benazir_repayment` category and the review status / comment fields.
- There may be **EMI**-related context (e.g. an Axis EMI). EMIs are auto-tagged
  only by the plain `loan_or_emi` keyword rule; whether a given EMI relates to
  Benazir is a **manual** decision.

> **Important:** "owed" is never inferred automatically. It only reflects what
> *you* record via review status and comments. Treat every remembered detail
> above as a prompt to go and check the actual transactions, not as a conclusion.

## Data on record (as extracted)

- **HDFC**: 1 statement file (`Acct Statement_9965_*.xls`).
- **ICICI**: 6 statement files (`OpTransactionHistory*.xls`).
- The dashboard already detects direct alias hits for "Benazir Rahaman" in both
  banks' UPI narrations. Nazrana/Najrana had no direct narration hits in the
  current files — if you know of payments to/for her mother, add or mark them
  manually.

## Hard rules

- The source folder **`all_bank_statements/` is read-only** and must remain
  untouched. All generated data lives under `data/`.
- Manual decisions are the **source of truth** for any owed/repayable
  classification.
- The app runs **locally only**: no cloud, no external API, no telemetry.
- Re-reading the statements never loses your manual work — decisions are keyed by
  a stable transaction id and re-applied each run.

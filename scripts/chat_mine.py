"""Mine the WhatsApp chat for context around Benazir payments.

Parses the export into (datetime, sender, message), then for a given date+amount
returns nearby messages — especially those mentioning the amount or money words —
so we can infer a reason. Read-only; prints candidate contexts.
"""

from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

CHAT = Path("data/benazir_chat_data/Full_WhatsApp_Chat_with_Benazir.txt")
_LINE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2})\s*([AP]M)\s*-\s*([^:]+):\s*(.*)$")
_MONEY = re.compile(r"\b(\d{3,6})\b|₹|rupee|rs\.?|paisa|sent|send|paid|pay|transfer|gpay|upi|paytm|"
                    r"rent|loan|emi|fees|salary|gold|insurance|kotak|iphone|laptop|phone|amount|money|"
                    r"return|owe|owed|due|borrow|lend", re.IGNORECASE)


def load_chat() -> pd.DataFrame:
    rows = []
    cur = None
    for line in CHAT.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = _LINE.match(line)
        if m:
            d, hm, ap, sender, msg = m.groups()
            try:
                ts = pd.to_datetime(f"{d} {hm} {ap}", format="mixed")
            except Exception:
                ts = pd.NaT
            cur = {"ts": ts, "sender": sender.strip(), "msg": msg.strip()}
            rows.append(cur)
        elif cur is not None:  # continuation of previous message
            cur["msg"] += " " + line.strip()
    df = pd.DataFrame(rows).dropna(subset=["ts"])
    return df


def context(chat: pd.DataFrame, date, amount=None, days=2, money_only=True) -> list[str]:
    target = pd.Timestamp(date)
    lo, hi = target - timedelta(days=days), target + timedelta(days=days + 1)
    win = chat[(chat["ts"] >= lo) & (chat["ts"] <= hi)]
    out = []
    amt_str = str(int(amount)) if amount else None
    for _, r in win.iterrows():
        msg = r["msg"]
        if msg in ("<Media omitted>", "null", "This message was deleted") or not msg:
            continue
        hit_amt = amt_str and (amt_str in msg or (amount and str(int(amount))[:3] in msg))
        if money_only and not (_MONEY.search(msg) or hit_amt):
            continue
        flag = " <<<AMT" if hit_amt else ""
        out.append(f'    {r["ts"]:%Y-%m-%d %H:%M} {r["sender"][:8]:8} {msg[:90]}{flag}')
    return out


if __name__ == "__main__":
    chat = load_chat()
    print(f"Parsed {len(chat)} messages, {chat['ts'].min():%Y-%m-%d}..{chat['ts'].max():%Y-%m-%d}")
    # Targets passed as "date,amount" pairs on argv, else a default F/G/H set.
    targets = []
    if len(sys.argv) > 1:
        for a in sys.argv[1:]:
            d, amt = a.split(",")
            targets.append((d, float(amt)))
    else:
        targets = [("2025-01-30", 8500), ("2025-03-31", 24000), ("2025-05-28", 26000),
                   ("2025-06-26", 19200), ("2025-07-31", 4207), ("2025-08-01", 30000)]
    for d, amt in targets:
        print(f"\n=== {d}  ₹{amt:.0f} ===")
        ctx = context(chat, d, amt, days=2)
        for line in ctx[:14]:
            print(line)
        if not ctx:
            print("    (no money-related messages nearby)")

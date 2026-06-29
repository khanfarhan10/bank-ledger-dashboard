"""Deep chat analysis to classify Benazir general-section transactions.

For each unclassified payment, pulls chat context (+/- a few days), scores money-
transfer signals, and suggests a category by keyword voting. Prints a scannable
report so masters can be created from confident groups.
"""

from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.config_loader import load_aliases, load_threshold  # noqa: E402
from src.services.pipeline import extract_normalize_classify, finalize_ledger  # noqa: E402
from src.services.decision_store import DecisionStore  # noqa: E402
from src.services import analytics  # noqa: E402

CHAT = Path("data/benazir_chat_data/Full_WhatsApp_Chat_with_Benazir.txt")
_LINE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2})\s*([AP]M)\s*-\s*([^:]+):\s*(.*)$")

# money / transfer signal words (English + Hinglish/Bengali)
SIGNAL = re.compile(r"\b(sent|send|sending|paid|pay|transfer|transferred|received|"
                    r"bhej\w*|bhej\w*|bhej diya|bhej do|bhejo|bhejna|bhejun|bhejdo|daal\w*|"
                    r"daldiya|kar diya|kr diya|de diya|diya|paisa|paise|rupee|rupees|"
                    r"\brs\b|gpay|g-pay|phonepe|upi|paytm|screenshot|amount|mila|mil gya|"
                    r"aa gya|aagya|account|loan|emi|rent|kiraya|fees|fee|gold|sona)\b", re.IGNORECASE)

CATS = {
    "rent": r"rent|kiraya|room|flat|landlord|makaan|ghar ka",
    "studies": r"\bfees?\b|exam|llb|\bba\b|college|university|vbu|semester|admission|form|registration|study|padhai|book|material|uniform|iem|tuition|coaching",
    "medical": r"doctor|medicine|hospital|clinic|\bdr\b|health|sick|bimar|tablet|blood|test|report|thyroid|pain|treatment",
    "food": r"khana|food|swiggy|zomato|lunch|dinner|breakfast|hungry|bhookh|order|eat",
    "travel": r"trip|travel|sikkim|train|\bbus\b|ticket|irctc|flight|ghoomne|tour|darjeeling|kolkata|hotel|resort",
    "gold_loan": r"\bgold\b|sona|\bloan\b|\bemi\b|kotak|insurance|jewell|gehna|gold loan|pledge",
    "gift_shopping": r"gift|birthday|dress|saree|shopping|amazon|flipkart|myntra|kapde|cloth",
    "job": r"salary|\bjob\b|relieving|company|notice period|compensation|interview|joining|office",
    "emergency": r"urgent|emergency|jaldi|immediately|zaroorat|need\b|chahiye|broke|nothing left",
}


def load_chat() -> pd.DataFrame:
    rows, cur = [], None
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
        elif cur is not None:
            cur["msg"] += " " + line.strip()
    return pd.DataFrame(rows).dropna(subset=["ts"])


def vote_category(text: str) -> list:
    t = text.lower()
    hits = [(c, len(re.findall(p, t))) for c, p in CATS.items()]
    hits = [(c, n) for c, n in hits if n]
    return sorted(hits, key=lambda x: -x[1])


def main():
    chat = load_chat()
    a = load_aliases(); t = load_threshold(); store = DecisionStore()
    df = finalize_ledger(extract_normalize_classify("all_bank_statements", a, t)["classified"], store, t)
    b = analytics.benazir_analytics(df, store)
    gen = [m for m in b["masters"] if m["code"] == "GEN"][0]
    txns = [m for m in gen["members"] if not m["offset"]]
    txns.sort(key=lambda x: -x["amount"])
    print(f"Chat msgs {len(chat)} | General non-offset txns {len(txns)}\n")

    for m in txns:
        d = pd.Timestamp(m["transaction_date"])
        win = chat[(chat["ts"] >= d - timedelta(days=3)) & (chat["ts"] <= d + timedelta(days=2))]
        amt = str(int(m["amount"]))
        scored = []
        for _, r in win.iterrows():
            msg = r["msg"]
            if msg in ("<Media omitted>", "null", "This message was deleted") or len(msg) < 3:
                continue
            s = 0
            if amt in msg: s += 4
            elif len(amt) >= 4 and amt[:3] in msg: s += 2
            if SIGNAL.search(msg): s += 2
            if s: scored.append((s, r["ts"], r["sender"], msg))
        scored.sort(key=lambda x: -x[0])
        ctx = " ".join(x[3] for x in scored[:6])
        cats = vote_category(ctx)
        catstr = cats[0][0] if cats else "?"
        best = scored[0][3][:64] if scored else "(no signal)"
        print(f"{m['transaction_date']} {m['direction'][:4]:4} Rs{m['amount']:>7,.0f} [{catstr:11}] {best}")


if __name__ == "__main__":
    main()

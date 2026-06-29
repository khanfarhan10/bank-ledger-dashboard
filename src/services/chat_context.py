"""WhatsApp chat context for the 'Figuring Out Benazir Expenses' page.

Loads the exported chat once (cached in-process), parses it into
(timestamp, sender, message), and for a given payment date+amount returns the
nearby messages — flagging money-signal lines and lines that mention the exact
amount. Read-only; nothing here writes to the chat file.
"""

from __future__ import annotations

import pickle
import re
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

CHAT_PATH = Path("data/benazir_chat_data/Full_WhatsApp_Chat_with_Benazir.txt")
CACHE_PATH = Path("data/cache/chat_parsed.pkl")

# WhatsApp export line: "M/D/YY, H:MM AM/PM - Sender: message"
_LINE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2})\s*([AP]M)\s*-\s*([^:]+):\s*(.*)$"
)

# Money / transfer signal words (English + Hinglish/Bengali) used by Benazir & me.
_SIGNAL = re.compile(
    r"\b(sent|send|sending|paid|pay|transfer\w*|received|recieve\w*|"
    r"bhej\w*|bhejo|bhejna|bhejun|bhejdo|bhej diya|daal\w*|daldiya|de diya|diya|"
    r"paisa|paise|rupee|rupees|\brs\b|\bk\b|gpay|g-pay|phonepe|phone pe|upi|paytm|"
    r"screenshot|amount|mila|mil gya|aa gya|aagya|account|balance|"
    r"loan|emi|rent|kiraya|deposit|advance|broker\w*|fees?|gold|sona|"
    r"insurance|kotak|laptop|repair|service cent\w*|admission|exam|college|"
    r"return|owe|owed|due|borrow|lend|udhaar|udhar|chahiye|zaroorat|urgent)\b",
    re.IGNORECASE,
)

_MEDIA = {"<Media omitted>", "null", "This message was deleted",
          "This message was deleted.", "You deleted this message"}


@lru_cache(maxsize=1)
def load_chat() -> pd.DataFrame:
    """Parse the chat export into a sorted (ts, sender, msg) frame, cached.

    Timestamps are parsed VECTORISED (one pass over the whole column with a
    couple of explicit formats) — parsing per-line with format='mixed' over
    200k+ messages took ~2 minutes; this takes a few seconds.
    """
    if not CHAT_PATH.exists():
        return pd.DataFrame(columns=["ts", "sender", "msg"])
    src_mtime = CHAT_PATH.stat().st_mtime_ns
    if CACHE_PATH.exists():  # fast path: reuse the parsed pickle if source unchanged
        try:
            with open(CACHE_PATH, "rb") as fh:
                blob = pickle.load(fh)
            if blob.get("src_mtime") == src_mtime:
                return blob["df"]
        except Exception:
            pass
    rows, cur = [], None
    for line in CHAT_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = _LINE.match(line)
        if m:
            d, hm, ap, sender, msg = m.groups()
            cur = {"raw_dt": f"{d} {hm} {ap}", "sender": sender.strip(), "msg": msg.strip()}
            rows.append(cur)
        elif cur is not None:  # continuation line of the previous message
            cur["msg"] = (cur["msg"] + " " + line.strip()).strip()
    if not rows:
        return pd.DataFrame(columns=["ts", "sender", "msg"])
    df = pd.DataFrame(rows)
    ts = pd.to_datetime(df["raw_dt"], format="%m/%d/%y %I:%M %p", errors="coerce")
    miss = ts.isna()
    if miss.any():  # some exports use a 4-digit year
        ts.loc[miss] = pd.to_datetime(df.loc[miss, "raw_dt"],
                                      format="%m/%d/%Y %I:%M %p", errors="coerce")
    df["ts"] = ts
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    df = df[["ts", "sender", "msg"]]
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "wb") as fh:
            pickle.dump({"src_mtime": src_mtime, "df": df}, fh,
                        protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return df


@lru_cache(maxsize=1)
def _chat_arrays():
    """Presorted parallel arrays for fast window slicing via searchsorted.

    All per-message strings (date, time) are precomputed VECTORISED here once,
    so the per-payment loop only indexes — no pd.Timestamp()/strftime() per
    message (that made each request several seconds)."""
    df = load_chat()
    if df.empty:
        empty = np.array([], dtype="datetime64[ns]")
        return {"ts": empty, "senders": [], "msgs": [],
                "is_me": np.array([], dtype=bool), "date": [], "time": [],
                "money": np.array([], dtype=bool)}
    senders = df["sender"].tolist()
    return {
        "ts": df["ts"].values.astype("datetime64[ns]"),
        "senders": senders,
        "msgs": df["msg"].tolist(),
        "is_me": np.array([str(s).strip().lower() in ("fhk", "farhan", "you", "me")
                           for s in senders], dtype=bool),
        "date": df["ts"].dt.strftime("%Y-%m-%d").tolist(),
        "time": df["ts"].dt.strftime("%H:%M").tolist(),
        # money-signal flag precomputed VECTORISED once (one regex pass over the
        # whole chat) so per-payment windows only index, never re-run the regex.
        "money": df["msg"].str.contains(_SIGNAL, regex=True, na=False).to_numpy(),
    }


def chat_span() -> dict:
    df = load_chat()
    if df.empty:
        return {"messages": 0, "first": None, "last": None}
    return {
        "messages": int(len(df)),
        "first": df["ts"].min().date().isoformat(),
        "last": df["ts"].max().date().isoformat(),
    }


def _amount_variants(amount) -> list[str]:
    """String forms of an amount to look for in chat (e.g. 8000 -> 8000, 8,000, 8k)."""
    try:
        n = int(round(float(amount)))
    except (TypeError, ValueError):
        return []
    out = {str(n), f"{n:,}"}
    if n >= 1000 and n % 1000 == 0:
        out.add(f"{n // 1000}k")
        out.add(f"{n // 1000} k")
    if n >= 1000:
        out.add(str(n)[:2])   # rough prefix (e.g. 8617 -> '86') used as a weak hint
    return [v for v in out if len(v) >= 2]


def context_for(date, amount=None, days: int = 5, limit: int | None = None) -> dict:
    """Messages within +/- `days` of `date`, money-flagged and amount-flagged.

    Returns {"messages": [...], "money_count": int, "amount_hits": int}.
    The display cap scales with the window so widening the days actually shows
    more messages (not the same truncated 60).
    """
    if limit is None:
        limit = min(220, max(60, int(days) * 16))
    arr = _chat_arrays()
    ts = arr["ts"]
    try:
        target = pd.Timestamp(date)
    except (TypeError, ValueError):
        target = pd.NaT
    if len(ts) == 0 or pd.isna(target):
        return {"messages": [], "money_count": 0, "amount_hits": 0}
    lo = np.datetime64(target - timedelta(days=days))
    hi = np.datetime64(target + timedelta(days=days) + timedelta(hours=23, minutes=59))
    i = int(np.searchsorted(ts, lo, side="left"))
    j = int(np.searchsorted(ts, hi, side="right"))

    senders, msgs, is_me = arr["senders"], arr["msgs"], arr["is_me"]
    dates, times, money = arr["date"], arr["time"], arr["money"]
    exact = _amount_variants(amount) if amount is not None else []
    exact_strong = exact[:2]  # the full-number forms are the strong matches

    out, money_count, amount_hits = [], 0, 0
    for k in range(i, j):
        msg = msgs[k]
        if not msg or msg in _MEDIA:
            continue
        is_money = bool(money[k])
        amt_hit = any(v in msg for v in exact_strong)
        if is_money:
            money_count += 1
        if amt_hit:
            amount_hits += 1
        out.append({
            "k": k,
            "date": dates[k],
            "time": times[k],
            "sender": senders[k],
            "is_me": bool(is_me[k]),
            "msg": msg if len(msg) <= 400 else msg[:400] + "…",
            "money": is_money,
            "amt_hit": amt_hit,
        })
    # Prefer to keep money/amount-bearing lines if we have to truncate.
    if len(out) > limit:
        out.sort(key=lambda m: (not m["amt_hit"], not m["money"], m["k"]))
        out = out[:limit]
        out.sort(key=lambda m: m["k"])
    return {"messages": out, "money_count": money_count, "amount_hits": amount_hits}

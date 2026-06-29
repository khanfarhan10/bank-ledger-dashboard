"""WhatsApp chat context for the 'Figuring Out Benazir Expenses' page.

Loads the exported chat once (cached in-process), parses it into
(timestamp, sender, message), and for a given payment date+amount returns the
nearby messages — flagging money-signal lines and lines that mention the exact
amount. Read-only; nothing here writes to the chat file.
"""

from __future__ import annotations

import pickle
import re
from bisect import bisect_left
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

CHAT_PATH = Path("data/benazir_chat_data/Full_WhatsApp_Chat_with_Benazir.txt")
CACHE_PATH = Path("data/cache/chat_parsed.pkl")
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

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


def _build_messages_by_ist_timestamp(df: pd.DataFrame) -> dict[datetime, list[dict]]:
    """Build the complete in-memory chat index without collapsing duplicates."""
    messages_by_ist_timestamp: dict[datetime, list[dict]] = {}
    for k, (raw_ts, raw_sender, raw_msg) in enumerate(
        df[["ts", "sender", "msg"]].itertuples(index=False, name=None)
    ):
        ts = pd.Timestamp(raw_ts)
        ts = ts.tz_localize(IST) if ts.tzinfo is None else ts.tz_convert(IST)
        ist_ts = ts.to_pydatetime()
        sender = "" if pd.isna(raw_sender) else str(raw_sender).strip()
        msg = "" if pd.isna(raw_msg) else str(raw_msg)
        messages_by_ist_timestamp.setdefault(ist_ts, []).append({
            "k": k,
            "date": ist_ts.date().isoformat(),
            "time": ist_ts.strftime("%H:%M"),
            "sender": sender,
            "is_me": sender.lower() in ("fhk", "farhan", "you", "me"),
            "msg": msg,
            "money": bool(_SIGNAL.search(msg)),
        })
    return messages_by_ist_timestamp


@lru_cache(maxsize=1)
def _messages_by_ist_timestamp() -> dict[datetime, list[dict]]:
    """Parse and index the chat once, then reuse it for every payment."""
    return _build_messages_by_ist_timestamp(load_chat())


@lru_cache(maxsize=1)
def _sorted_ist_timestamps() -> tuple[datetime, ...]:
    return tuple(sorted(_messages_by_ist_timestamp()))


def chat_span() -> dict:
    messages_by_timestamp = _messages_by_ist_timestamp()
    timestamps = _sorted_ist_timestamps()
    if not timestamps:
        return {"messages": 0, "first": None, "last": None}
    return {
        "messages": sum(len(messages) for messages in messages_by_timestamp.values()),
        "first": timestamps[0].date().isoformat(),
        "last": timestamps[-1].date().isoformat(),
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


def context_for(date, amount=None, days: int = 5, include_messages: bool = True) -> dict:
    """Messages within +/- `days` of `date`, money-flagged and amount-flagged.

    Returns every message in the complete IST calendar window. No relevance
    filtering or display cap is applied. Pass include_messages=False to get just
    the money/amount counts cheaply (the bulk page lazy-loads each chat on
    demand, so it only needs counts up front).
    """
    messages_by_timestamp = _messages_by_ist_timestamp()
    timestamps = _sorted_ist_timestamps()
    try:
        target_date = pd.Timestamp(date).date()
    except (TypeError, ValueError):
        target_date = None
    if not timestamps or target_date is None:
        return {"messages": [], "money_count": 0, "amount_hits": 0}

    window_days = max(0, int(days))
    lo = datetime.combine(target_date - timedelta(days=window_days), time.min, IST)
    hi = datetime.combine(target_date + timedelta(days=window_days + 1), time.min, IST)
    i = bisect_left(timestamps, lo)
    j = bisect_left(timestamps, hi)

    exact = _amount_variants(amount) if amount is not None else []
    exact_strong = exact[:2]  # the full-number forms are the strong matches

    out, money_count, amount_hits = [], 0, 0
    for timestamp in timestamps[i:j]:
        for message in messages_by_timestamp[timestamp]:
            msg = message["msg"]
            if not msg or msg in _MEDIA:
                continue
            amt_hit = any(variant in msg for variant in exact_strong)
            if message["money"]:
                money_count += 1
            if amt_hit:
                amount_hits += 1
            if include_messages:
                out.append({**message, "amt_hit": amt_hit})

    return {"messages": out, "money_count": money_count, "amount_hits": amount_hits}

"""Transparent, regex-based classification rules — kept deliberately simple.

This is the single place that maps a transaction's *narration text* to a
**primary category** and to zero-or-more **tags** (multi-label). No AI, no
external calls — just readable regular expressions you can audit and extend.

Two independent ideas live here:

1. CATEGORY  — one best-fit bucket per transaction (the headline classification).
   Rules are tried top-to-bottom; the first matching rule wins. Direction
   (RECEIVED / PAID_OUT) can gate a rule so, e.g., "salary" only matches credits.

2. TAGS      — many descriptive labels per transaction, applied independently of
   the category. A single Swiggy payment can be tagged {food, food_delivery};
   a Kotak premium can be tagged {insurance, tax_saving_80c}. Tags are how one
   entry carries multiple valid sub-classifications.

Self-transfer and person detection are handled elsewhere (self_identity.yml /
aliases.yml) and take priority over these rules in classification_service.

To extend: add a (label, [patterns]) row to the relevant list below. Patterns
are case-insensitive Python regex matched against the lowercased narration.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Brand / merchant vocabularies (reused across category and tag rules).
# Add new brands here and they flow through to both category and tags.
# ---------------------------------------------------------------------------

_FOOD_DELIVERY = r"swiggy|zomato|instamart|blinkit|zepto|dunzo|eatfit|eatsure|box8|freshmenu"
_RESTAURANTS = r"kfc|mcdonald|dominos|domino's|pizza|burger king|kareem|kareems|kerim|haldiram|barbeque|bbq|biryani|cafe|coffee|starbucks|chai|barista|subway|wow momo|behrouz|faasos"
_GROCERY = r"bigbasket|big basket|dmart|d-mart|d mart|grofers|jiomart|reliance fresh|reliance retail|spencer|more retail|nature.?s basket|licious|country delight"
_SHOPPING_ONLINE = r"amazon|amzn|flipkart|myntra|ajio|meesho|nykaa|tatacliq|tata cliq|snapdeal|firstcry|lenskart|decathlon"
_TRANSPORT = r"uber|ola |olacabs|rapido|irctc|redbus|makemytrip|make my trip|goibibo|ixigo|yatra|indigo|spicejet|vistara|air india|namma metro|metro rail|fastag|paytm.?fastag|toll"
_FUEL = r"\b(hp|hpcl|iocl|indian oil|bharat petroleum|bpcl|reliance petro|shell|nayara|essar)\b|petrol|fuel|filling station"
_UTILITIES = r"electricity|wbsedcl|cesc|power ltd|bijli|water bill|gas bill|indane|hp gas|bharat gas|piped gas|broadband|wifi|airtel|jio|vodafone|\bvi \b|bsnl|act fibernet|hathway|tata sky|dish tv|d2h|recharge|dth"
_ENTERTAINMENT = r"netflix|hotstar|disney|prime video|spotify|youtube premium|sony liv|sonyliv|zee5|jiocinema|bookmyshow|pvr|inox|gaana|jiosaavn"
_EDUCATION = r"udemy|coursera|upgrad|byju|unacademy|vedantu|great learning|tuition|course fee|exam fee|university|college fee"
_MEDICAL = r"pharmacy|apollo|medplus|netmeds|1mg|pharmeasy|hospital|clinic|diagnostic|lab test|thyrocare|dr lal|practo|medicine|chemist"

# ---------------------------------------------------------------------------
# INVESTMENT brands — outgoing money that is *saved/invested*, not spent.
# Each maps to a tag so the Investments page can break them down.
# ---------------------------------------------------------------------------

_INVESTMENT_BRANDS = {
    "investment_groww": r"groww|nextbillion|billion technologies",
    "investment_zerodha": r"zerodha|kite|coin\.zerodha|nextbilling|zerodha broking",
    "investment_mutual_fund": r"mutual fund|\bmf\b|nav |sip |systematic invest|bse star|nse mf|mf utilit|camsonline|cams |kfintech|kfin |indmoney|ind money|kuvera|paytm money|et money|etmoney",
    "investment_sgb": r"sgb|sovereign gold|gold bond|rbi bond|govt bond|g-sec|gsec",
    "investment_ppf": r"\bppf\b|public provident",
    "investment_stocks": r"\bdemat\b|broking|securities|stock|equity|upstox|angel one|angelone|5paisa|icicidirect|icici direct|hdfc sec|kotak sec|motilal",
    "investment_nps": r"\bnps\b|national pension|nsdl pension|protean",
    "investment_fd_rd": r"trf to fd|recurring deposit|\brd no\b|term deposit",
}

# 80C / tax-saving instruments (a tag layered on top of the above where relevant).
# Includes Kotak life insurance handles/narrations (insurance.kotak, kotak life).
_TAX_SAVING_80C = (
    r"\bppf\b|public provident|\belss\b|tax saver|tax saving|sukanya|nsc |"
    r"national saving|life insurance|\blic\b|kotak life|insurance\.kotak|"
    r"kotak.{0,4}insuranc|term plan|\bnps\b"
)

# ---------------------------------------------------------------------------
# INCOME (RECEIVED only) — employer salary, refunds, interest, etc.
# ---------------------------------------------------------------------------

_EMPLOYERS = r"koireader|primus global|primus-global"

# (category, regex, human_reason, direction)  — direction None = any.
# Tried in order; first match wins. RECEIVED-gated income rules come first.
CATEGORY_RULES: list[tuple[str, str, str, str | None]] = [
    # --- income (credits) ---
    ("salary_or_income", _EMPLOYERS, "Employer credit (KoiReader / Primus Global).", "RECEIVED"),
    ("salary_or_income", r"salary|payroll|sal cr|sal credit", "Narration mentions salary/payroll on a credit.", "RECEIVED"),
    ("it_refund", r"incometaxrefund|income tax refund|it refund|itr.?refund|refund.*income tax|cbdt refund|tax refund", "Income-tax refund credit.", "RECEIVED"),
    ("interest_income", r"int\.pd|interest paid|int credit|saving.*interest|fd interest|interest on", "Bank/FD interest credit.", "RECEIVED"),
    # Failed-transaction reversals returning money — NOT income.
    ("refund_reversal", r"\brvsl\b|reversal|refund reversal|failed txn", "Reversal / failed-transaction refund (own money back).", "RECEIVED"),
    # Investment redemptions/withdrawals coming back — own money, not income.
    ("investment_redemption", r"withdraw req|redemption|groww|zerodha|paytm money|mutual fund|sgb", "Investment redemption / withdrawal back to account.", "RECEIVED"),
    ("cashback_reward", r"cashback|reward", "Cashback / reward credit.", "RECEIVED"),

    # --- investments (debits, saved not spent) ---
    ("investment", r"groww|zerodha|mutual fund|\bsip\b|sovereign gold|gold bond|\bsgb\b|ft-sgb|\bppf\b|public provident|\bnps\b|elss|bse star|nse mf|camsonline|kfintech|indmoney|kuvera|upstox|angel one|5paisa|icicidirect|trf to fd|recurring deposit",
     "Investment / savings outflow.", "PAID_OUT"),

    # --- insurance / loans ---
    ("insurance", r"kotak life|life insurance|insurance|\blic\b|policy|premium|term plan|hdfc life|max life|sbi life|star health|hdfc ergo|bajaj allianz", "Insurance premium / policy.", None),
    ("loan_or_emi", r"\bemi\b|\bloan\b|lending|insta loan|personal loan|home loan|car loan|nbfc|bajaj fin|finserv", "Loan / EMI.", None),

    # --- everyday spend (debits, but direction-agnostic is fine) ---
    ("food", _FOOD_DELIVERY, "Food delivery order.", None),
    ("food", _RESTAURANTS, "Restaurant / cafe.", None),
    ("groceries", _GROCERY, "Groceries / quick-commerce.", None),
    ("shopping", _SHOPPING_ONLINE, "Online shopping.", None),
    ("transport", _TRANSPORT, "Travel / transport / cabs.", None),
    ("fuel", _FUEL, "Fuel / petrol.", None),
    ("utilities", _UTILITIES, "Utilities / telecom / recharge.", None),
    ("entertainment", _ENTERTAINMENT, "Entertainment / subscriptions.", None),
    ("education", _EDUCATION, "Education / courses.", None),
    ("medical", _MEDICAL, "Medical / pharmacy / healthcare.", None),

    # --- money movement ---
    ("cash_withdrawal", r"cash wdl|cash withdrawal|\bnwd\b|\batm\b|nfs/|atw/", "Cash / ATM withdrawal.", None),
    ("bank_charges", r"amb chrg|sms chg|smschgs|annual fee|atm.*chg|gst|service charge|amc |processing fee|min bal|penal|chrg incl", "Bank charge / fee.", None),
]


# Multi-label tags: (tag, regex). Applied independently; a row can get many.
# direction is not gated here — tags are descriptive.
TAG_RULES: list[tuple[str, str]] = [
    ("food", _FOOD_DELIVERY),
    ("food", _RESTAURANTS),
    ("food_delivery", _FOOD_DELIVERY),
    ("groceries", _GROCERY),
    ("shopping", _SHOPPING_ONLINE),
    ("transport", _TRANSPORT),
    ("fuel", _FUEL),
    ("utilities", _UTILITIES),
    ("entertainment", _ENTERTAINMENT),
    ("education", _EDUCATION),
    ("medical", _MEDICAL),
    ("upi", r"\bupi\b|@ptyes|@ptaxis|@pty|@ybl|@oksbi|@okaxis|@okhdfcbank|@okicici|@apl|@ibl"),
    ("neft", r"\bneft\b"),
    ("imps", r"\bimps\b|\bmmt\b"),
    ("wallet_load", r"paytm|phonepe|amazon pay|mobikwik|freecharge"),
    ("salary", r"salary|payroll|" + _EMPLOYERS),
    ("interest", r"int\.pd|interest"),
    ("insurance", r"insurance|\blic\b|kotak life|premium|policy|term plan"),
    ("loan_emi", r"\bemi\b|\bloan\b|lending"),
    ("bank_charge", r"amb chrg|sms chg|gst|annual fee|service charge"),
    ("tax_saving_80c", _TAX_SAVING_80C),
    ("income_tax", r"income tax|cbdt|tds|advance tax|self assessment tax|\bdtax\b"),
]

# Investment tags layered on top (also exposed for the Investments page).
INVESTMENT_TAG_RULES: list[tuple[str, str]] = list(_INVESTMENT_BRANDS.items())

# Friendly display names for investment tags (for the Investments breakdown).
INVESTMENT_TAG_LABELS: dict[str, str] = {
    "investment_groww": "Groww",
    "investment_zerodha": "Zerodha",
    "investment_mutual_fund": "Mutual funds (other platforms)",
    "investment_sgb": "Sovereign Gold Bonds (SGB)",
    "investment_ppf": "PPF",
    "investment_stocks": "Stocks / Demat / broking",
    "investment_nps": "NPS",
    "investment_fd_rd": "Fixed / Recurring deposits",
}


# --- compiled-pattern helpers -----------------------------------------------

def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# Pre-compile everything once at import for speed over thousands of rows.
_CATEGORY_COMPILED = [(cat, _compile(pat), reason, direction) for cat, pat, reason, direction in CATEGORY_RULES]
_TAG_COMPILED = [(tag, _compile(pat)) for tag, pat in TAG_RULES]
_INVESTMENT_COMPILED = [(tag, _compile(pat)) for tag, pat in INVESTMENT_TAG_RULES]


def match_category(text: str, direction: str) -> tuple[str | None, str | None]:
    """Return (category, reason) for the first matching rule, or (None, None).

    ``direction`` gates RECEIVED/PAID_OUT-specific rules.
    """
    direction = (direction or "").upper()
    for cat, rx, reason, want_dir in _CATEGORY_COMPILED:
        if want_dir and want_dir != direction:
            continue
        if rx.search(text):
            return cat, reason
    return None, None


def match_tags(text: str) -> list[str]:
    """Return the sorted, de-duplicated list of descriptive tags for ``text``."""
    tags: list[str] = []
    for tag, rx in _TAG_COMPILED:
        if tag not in tags and rx.search(text):
            tags.append(tag)
    for tag, rx in _INVESTMENT_COMPILED:
        if tag not in tags and rx.search(text):
            tags.append(tag)
    return tags


def match_investment_tags(text: str) -> list[str]:
    """Return only the investment-specific tags present in ``text``."""
    return [tag for tag, rx in _INVESTMENT_COMPILED if rx.search(text)]

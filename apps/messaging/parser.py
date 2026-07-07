"""
SMS command parser.

Supported commands (case-insensitive):
  LEAVE YYYY-MM-DD [YYYY-MM-DD] [optional reason]
  STATUS
  CANCEL [YYYY-MM-DD]
  HELP

You can also just text naturally, e.g. 'can I take Aug 1 off?'
"""
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dateparser import — graceful degradation if not installed
# ---------------------------------------------------------------------------
try:
    import dateparser
    import dateparser.search as _dp_search
    _DATEPARSER_AVAILABLE = True
except ImportError:
    dateparser = None          # type: ignore[assignment]
    _dp_search = None          # type: ignore[assignment]
    _DATEPARSER_AVAILABLE = False
    logger.warning(
        "dateparser is not installed; NLP date parsing is disabled. "
        "Install python-dateparser==1.2.0 to enable it."
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

HELP_TEXT = (
    "Hospital Leave System\n"
    "Commands:\n"
    "  LEAVE YYYY-MM-DD [end-date] [reason]\n"
    "  STATUS — view your upcoming leaves\n"
    "  CANCEL [YYYY-MM-DD] — cancel a leave by start date\n"
    "  HELP — show this message\n"
    "You can also just text naturally, e.g. 'can I take Aug 1 off?'"
)

# NLP intent keywords
_LEAVE_KEYWORDS = re.compile(
    r"\b(off|out|leave|vacation|away|day off|taking|requesting|"
    r"need to be|can i take|calling in|sick|pto|absent)\b",
    re.IGNORECASE,
)
_STATUS_KEYWORDS = re.compile(
    r"\b(status|my leaves|upcoming|schedule|what do i have)\b",
    re.IGNORECASE,
)
_CANCEL_KEYWORDS = re.compile(
    r"\b(cancel|cancel my|remove my leave|taking back)\b",
    re.IGNORECASE,
)
_HELP_KEYWORDS = re.compile(
    r"\b(help|commands|what can i|how do i)\b",
    re.IGNORECASE,
)

# dateparser settings
_DP_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RETURN_AS_TIMEZONE_AWARE": False,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ParsedCommand:
    command: str                    # "leave" | "status" | "cancel" | "help" | "unknown"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    reason: str = ""
    cancel_date: Optional[date] = None
    raw: str = ""
    nlp_parsed: bool = False        # True when the NLP path produced this result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def parse_sms(text: str) -> ParsedCommand:
    raw = text.strip()
    logger.debug("parse_sms called: %r", raw)
    normalized = raw.lower()

    # --- keyword-based parsing (original logic) ---
    if normalized.startswith("help"):
        return ParsedCommand(command="help", raw=raw)

    if normalized.startswith("status"):
        return ParsedCommand(command="status", raw=raw)

    if normalized.startswith("cancel"):
        dates = DATE_PATTERN.findall(raw)
        cancel_date = _parse_date(dates[0]) if dates else None
        return ParsedCommand(command="cancel", cancel_date=cancel_date, raw=raw)

    if (
        normalized.startswith("leave")
        or normalized.startswith("off")
        or normalized.startswith("vacation")
    ):
        dates = DATE_PATTERN.findall(raw)
        if not dates:
            return ParsedCommand(
                command="unknown",
                raw=raw,
                reason="No date found. " + HELP_TEXT,
            )
        start_date = _parse_date(dates[0])
        end_date = _parse_date(dates[1]) if len(dates) >= 2 else start_date
        if start_date is None:
            return ParsedCommand(command="unknown", raw=raw)
        if end_date and end_date < start_date:
            end_date = start_date
        last_date_str = dates[-1]
        after_date = raw[raw.rfind(last_date_str) + len(last_date_str):].strip()
        reason = after_date if after_date else ""
        return ParsedCommand(
            command="leave",
            start_date=start_date,
            end_date=end_date or start_date,
            reason=reason,
            raw=raw,
        )

    # --- NLP fallback ---
    result = _try_nlp_parse(raw)
    if result.command != "unknown":
        logger.debug(
            "NLP parse result: command=%s nlp=%s", result.command, result.nlp_parsed
        )
        return result

    logger.warning("Unknown command: %r", raw)
    return ParsedCommand(command="unknown", raw=raw)


# ---------------------------------------------------------------------------
# NLP parser
# ---------------------------------------------------------------------------
def _try_nlp_parse(text: str) -> ParsedCommand:
    """Attempt to parse a natural-language leave request using dateparser + regex."""
    if not _DATEPARSER_AVAILABLE:
        return ParsedCommand(command="unknown", raw=text)

    normalized = text.lower()

    # Detect intent
    if _HELP_KEYWORDS.search(normalized):
        return ParsedCommand(command="help", raw=text, nlp_parsed=True)

    if _STATUS_KEYWORDS.search(normalized):
        return ParsedCommand(command="status", raw=text, nlp_parsed=True)

    if _CANCEL_KEYWORDS.search(normalized):
        start_date, end_date = _extract_dates_nlp(text)
        cancel_date = start_date  # use the first date found as the leave to cancel
        return ParsedCommand(
            command="cancel",
            cancel_date=cancel_date,
            raw=text,
            nlp_parsed=True,
        )

    if _LEAVE_KEYWORDS.search(normalized):
        start_date, end_date = _extract_dates_nlp(text)
        if start_date is None:
            # Could not extract a date; still recognised intent but incomplete
            return ParsedCommand(
                command="unknown",
                raw=text,
                reason="Understood leave request but could not identify a date. "
                       + HELP_TEXT,
            )
        reason = _extract_reason(text)
        return ParsedCommand(
            command="leave",
            start_date=start_date,
            end_date=end_date or start_date,
            reason=reason,
            raw=text,
            nlp_parsed=True,
        )

    return ParsedCommand(command="unknown", raw=text)


# ---------------------------------------------------------------------------
# Date extraction helpers
# ---------------------------------------------------------------------------
def _extract_dates_nlp(text: str) -> tuple[Optional[date], Optional[date]]:
    """
    Return (start_date, end_date) by searching the text for date expressions.

    Strategy:
    1. Use dateparser.search.search_dates to find all date references.
    2. If 2+ dates are found: first = start, second = end.
    3. If 1 date found: start = end = that date.
    4. Fall back to dateparser.parse() for simple relative phrases.
    """
    # search_dates returns list of (match_str, datetime) or None
    found = _dp_search.search_dates(text, settings=_DP_SETTINGS)  # type: ignore[union-attr]

    if found and len(found) >= 2:
        # Check for "to" / "through" / "thru" between the two matches to confirm a range
        start_dt = found[0][1]
        end_dt = found[1][1]
        start = start_dt.date() if start_dt else None
        end = end_dt.date() if end_dt else None
        if start and end and end < start:
            end = start
        return start, end

    if found and len(found) == 1:
        d = found[0][1].date() if found[0][1] else None
        return d, d

    # Fallback: try parsing the whole string as a single date/relative phrase
    parsed = dateparser.parse(text, settings=_DP_SETTINGS)  # type: ignore[union-attr]
    if parsed:
        d = parsed.date()
        return d, d

    return None, None


def _extract_reason(text: str) -> str:
    """
    Strip recognised date tokens from text and return the remainder as the reason.
    Common connective words ("for", "to", "through", "on", "I", "a", "off", etc.)
    at the start/end are trimmed.
    """
    if not _DATEPARSER_AVAILABLE:
        return ""

    found = _dp_search.search_dates(text, settings=_DP_SETTINGS)  # type: ignore[union-attr]
    remainder = text
    if found:
        for match_str, _ in found:
            remainder = remainder.replace(match_str, " ", 1)

    # Remove leading intent words / filler
    _FILLER = re.compile(
        r"^\s*(can i (take|be)?|i need|need to be|requesting|i('m| am) (taking|going to be)?|"
        r"taking|need a day off|calling in|i will be|i'll be|off|out|leave|vacation|for|on|a|"
        r"this|next|to|through|thru|,|\.)\s*",
        re.IGNORECASE,
    )
    prev = None
    while prev != remainder:
        prev = remainder
        remainder = _FILLER.sub("", remainder).strip()

    return remainder.strip(" .,")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def _parse_date(date_str: str) -> Optional[date]:
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None

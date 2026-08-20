"""Portable strftime for no-padding format codes.

``%-d`` / ``%-I`` (day and hour without a leading zero) are a glibc extension.
They work on Render, which is Linux, and they are what the codebase has always
used — but they are not portable: BSD libc, which macOS uses, and the Windows
CRT do not accept them. On Windows the equivalent is ``%#d``, and there is no
spelling that works everywhere.

Rather than hand-build every string, ``strftime_nopad`` expands just the
no-padding codes itself and hands the rest to the platform's strftime. Call
sites keep their original format strings.

    strftime_nopad(dt, "%A, %B %-d")   -> "Monday, August 3"
    strftime_nopad(dt, "%-I:%M %p")    -> "7:30 PM"
"""

# Each entry renders the field with no padding. Values are always digits, so
# substituting them into the format string cannot introduce a new directive.
_NOPAD_CODES = {
    "d": lambda t: str(t.day),
    "m": lambda t: str(t.month),
    "y": lambda t: str(t.year % 100),
    "H": lambda t: str(t.hour),
    "I": lambda t: str(t.hour % 12 or 12),
    "M": lambda t: str(t.minute),
    "S": lambda t: str(t.second),
    "j": lambda t: str(t.timetuple().tm_yday),
}


def strftime_nopad(value, fmt: str) -> str:
    """Like value.strftime(fmt), but %-<code> works on every platform.

    `value` may be a date or a datetime; time-of-day codes naturally require a
    datetime. Unknown directives are passed through to strftime untouched, so
    this stays a drop-in replacement.
    """
    out = []
    i = 0
    while i < len(fmt):
        if fmt[i] != "%":
            out.append(fmt[i])
            i += 1
            continue

        nxt = fmt[i + 1:i + 2]
        if nxt == "%":
            out.append("%%")
            i += 2
            continue

        code = fmt[i + 2:i + 3]
        if nxt == "-" and code in _NOPAD_CODES:
            out.append(_NOPAD_CODES[code](value))
            i += 3
            continue

        # Any other directive (including an unrecognised %-X) goes through as-is.
        out.append(fmt[i:i + 2])
        i += 2

    return value.strftime("".join(out))


def format_event_time(value) -> str:
    """The calendar's canonical time-of-day string: "7 PM", "7:30 PM".

    Twelve-hour, no leading zero, and a whole hour drops its ":00". This exact
    incantation was repeated at eleven call sites across the scrapers and the
    backend; they all delegate here now.
    """
    return strftime_nopad(value, "%-I:%M %p").replace(":00 ", " ")

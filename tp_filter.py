#!/usr/bin/env python3
"""
TP (UiB) iCal filter
- Fetches a TP subscription .ics URL
- Keeps only your chosen groups/parts per course
- Writes a cleaned .ics you can import or host

Usage:
  1) Edit CONFIG below (URL + your groups)
  2) python tp_filter.py
  3) Import filtered.ics into your calendar
     (For auto-updates, host filtered.ics somewhere and subscribe to that URL)
"""

from __future__ import annotations
import re
import sys
import urllib.request
from dataclasses import dataclass
from typing import Dict, List

# ----------------- CONFIG -----------------
ICAL_SUBSCRIPTION_URL = "https://tp.educloud.no/uib/timeplan/ical.php?type=course&sem=25h&id%5B%5D=INF102%2C1&id%5B%5D=INF113%2C1&id%5B%5D=INF214%2C1&id%5B%5D=MAT111%2C1&id%5B%5D=MAT221%2C1"

# List the courses you actually take, and which *group-type* events to keep.
# Lectures/Seminars/Workshops are kept automatically if the course is listed.
# Only "group-like" events are filtered by the patterns below.
#
# Pre-filled from your screenshot (adjust freely):
COURSE_KEEP_RULES: Dict[str, List[str]] = {
    # Course code : list of patterns to KEEP for "group-like" events
    "INF102": ["Aktiv time 7"],
    "INF113": ["Gruppe 4"],
    "INF214": ["Gruppe 1"],
    "MAT111": ["Gruppe 02"],  # if no fixed group, you can remove this line
    "MAT221": [],             # no group chosen? leave empty -> lectures kept, groups dropped
}

# Words that indicate "group-like" sessions which should be filtered by the rules above.
GROUP_WORDS = [
    "gruppe", "group", "aktiv time", "lab", "øving", "övning", "exercise class",
    "class group", "seminargruppe", "workshopgruppe"
]

# Words that indicate "always keep" (non-group) teaching types.
ALWAYS_KEEP_WORDS = [
    "forelesning", "seminar", "regneverksted", "oppgavesesjon", "review", "lecture", "workshop"
]

OUTPUT_FILE = "filtered.ics"
# --------------- END CONFIG ---------------


def http_get(url: str) -> str:
    with urllib.request.urlopen(url) as resp:
        raw = resp.read()
    # iCal is text, usually UTF-8
    return raw.decode("utf-8", errors="replace")


def unfold_ical(text: str) -> str:
    # RFC5545: lines may be folded with CRLF + space / tab at the beginning of the next line.
    # Replace CRLF followed by space or tab with nothing.
    return re.sub(r"(?:\r?\n)[ \t]", "", text)


@dataclass
class Event:
    raw: str
    summary: str
    description: str

    @property
    def course_code(self) -> str | None:
        # Try to detect something like INF102, MAT111, etc. from the summary
        m = re.search(r"\b([A-Z]{3}\d{3})\b", self.summary)
        return m.group(1) if m else None

    @property
    def is_group_like(self) -> bool:
        s = self.summary.lower()
        return any(w in s for w in GROUP_WORDS)

    @property
    def is_always_keep(self) -> bool:
        s = self.summary.lower()
        return any(w in s for w in ALWAYS_KEEP_WORDS)


def parse_events(ical_text: str) -> List[Event]:
    unfolded = unfold_ical(ical_text)
    blocks = re.split(r"(?=BEGIN:VEVENT)", unfolded)
    events: List[Event] = []
    for blk in blocks:
        if "BEGIN:VEVENT" not in blk:
            continue
        # Extract SUMMARY/DESCRIPTION robustly
        def prop(name: str) -> str:
            m = re.search(rf"^{name}(?:;[^:]*)?:(.*)$", blk, flags=re.MULTILINE)
            return m.group(1).strip() if m else ""
        summary = prop("SUMMARY")
        description = prop("DESCRIPTION")
        events.append(Event(raw=blk, summary=summary, description=description))
    return events


def filter_events(events: List[Event]) -> List[Event]:
    kept: List[Event] = []
    for ev in events:
        code = ev.course_code
        if not code:
            # If we cannot detect a course code, be conservative: keep it
            kept.append(ev)
            continue

        # Only consider courses listed in COURSE_KEEP_RULES
        if code not in COURSE_KEEP_RULES:
            # Not one of your courses -> drop
            continue

        if ev.is_always_keep:
            kept.append(ev)
            continue

        if ev.is_group_like:
            patterns = [p.lower() for p in COURSE_KEEP_RULES.get(code, []) if p.strip()]
            if not patterns:
                # No allowed patterns for this course -> drop group-like events
                continue
            s = ev.summary.lower()
            if any(p in s for p in patterns):
                kept.append(ev)
            else:
                continue
        else:
            # Not recognized as group-like, not "always keep":
            # keep by default if it's within your listed courses.
            kept.append(ev)
    return kept


def rebuild_ical(original_text: str, kept_events: List[Event]) -> str:
    # Extract header and footer from the original
    unfolded = unfold_ical(original_text)
    # Grab everything before first VEVENT and after last END:VEVENT as header/footer
    header_match = re.split(r"BEGIN:VEVENT", unfolded, maxsplit=1)
    if len(header_match) == 1:
        # No events?
        return original_text
    header = header_match[0]
    # Footer: anything after the final END:VEVENT
    end_positions = [m.end() for m in re.finditer(r"END:VEVENT", unfolded)]
    footer = ""
    if end_positions:
        last_end = end_positions[-1]
        footer = unfolded[last_end:]
    else:
        footer = "\nEND:VCALENDAR\n"

    # Rebuild calendar text
    body = ""
    for ev in kept_events:
        # Ensure each block ends with END:VEVENT\n
        block = ev.raw
        if not block.strip().endswith("END:VEVENT"):
            # Try to cut at END:VEVENT to be safe
            m = re.search(r"BEGIN:VEVENT.*?END:VEVENT", block, flags=re.DOTALL)
            if m:
                block = m.group(0)
        body += block.strip() + "\n"

    # Ensure header starts with BEGIN:VCALENDAR
    if "BEGIN:VCALENDAR" not in header:
        header = "BEGIN:VCALENDAR\n" + header
    # Ensure footer ends with END:VCALENDAR
    if "END:VCALENDAR" not in footer:
        footer = footer.rstrip() + "\nEND:VCALENDAR\n"
    return header + body + footer


def main():
    if ICAL_SUBSCRIPTION_URL.startswith("PASTE_"):
        print("❗ Please edit ICAL_SUBSCRIPTION_URL in the script first.")
        sys.exit(1)

    print("Fetching TP iCal…")
    src = http_get(ICAL_SUBSCRIPTION_URL)
    print("Parsing events…")
    events = parse_events(src)
    print(f"Found {len(events)} events")

    print("Filtering…")
    kept = filter_events(events)
    print(f"Keeping {len(kept)} events")

    print("Rebuilding calendar…")
    out = rebuild_ical(src, kept)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(out)

    print(f"✅ Wrote {OUTPUT_FILE}")
    print("Tip: host this file (e.g., GitHub Pages/Dropbox direct link) and subscribe to the URL for auto-updates.")

if __name__ == "__main__":
    main()

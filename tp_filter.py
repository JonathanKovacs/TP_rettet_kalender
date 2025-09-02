#!/usr/bin/env python3
"""
TP (UiB) iCal filter
- Fetches a TP subscription .ics URL
- Keeps only your chosen groups/parts per course
- Writes a cleaned filtered.ics you can import or host

How to use:
  1) In GitHub: Settings → Secrets and variables → Actions → New secret
     Name: TP_ICAL_URL, Value: <your TP subscription URL>
  2) Adjust COURSE_KEEP_RULES below to your groups
  3) Run locally: python tp_filter.py  (if TP_ICAL_URL is set in env)
     or via GitHub Actions (recommended)
"""

from __future__ import annotations
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from typing import Dict, List

# ----------------- CONFIG -----------------

# Will be provided by GitHub Actions secret or your local env
ICAL_SUBSCRIPTION_URL = os.getenv("TP_ICAL_URL", "")

# List the courses you actually take, and which *group-type* events to keep.
# Lectures/Seminars/Workshops are kept automatically if the course is listed.
# Only "group-like" events are filtered by the patterns below.
COURSE_KEEP_RULES: Dict[str, List[str]] = {
    # Course code : list of patterns to KEEP for "group-like" events
    "INF102": ["Aktiv time 7"],
    "INF113": ["Gruppe 4"],
    "INF214": ["Gruppe 1"],
    "MAT111": ["Gruppe 02"],  # note leading zero
    "MAT221": [],             # no groups -> lectures kept, groups dropped
}

# Words that indicate "group-like" sessions which should be filtered by the rules above.
GROUP_WORDS = [
    "gruppe", "group", "aktiv time", "lab", "øving", "övning",
    "exercise class", "class group", "seminargruppe", "workshopgruppe"
]

# Words that indicate "always keep" (non-group) teaching types.
ALWAYS_KEEP_WORDS = [
    "forelesning", "seminar", "regneverksted", "oppgavesesjon",
    "review", "lecture", "workshop"
]

OUTPUT_FILE = "filtered.ics"
# --------------- END CONFIG ---------------


def http_get(url: str) -> str:
    with urllib.request.urlopen(url) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def unfold_ical(text: str) -> str:
    # RFC5545: lines may be folded (CRLF + space/tab). Unfold them.
    return re.sub(r"(?:\r?\n)[ \t]", "", text)


@dataclass
class Event:
    raw: str
    summary: str
    description: str

    @property
    def course_code(self) -> str | None:
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
            # Unknown event -> keep (conservative)
            kept.append(ev)
            continue

        # Only courses you listed are kept at all
        if code not in COURSE_KEEP_RULES:
            continue

        # Always keep non-group teaching types (lectures, seminars, etc.)
        if ev.is_always_keep:
            kept.append(ev)
            continue

        # For group-like sessions, keep only if they match allowed patterns
        if ev.is_group_like:
            patterns = [p.lower() for p in COURSE_KEEP_RULES.get(code, []) if p.strip()]
            if not patterns:
                # No groups chosen -> drop group-like events
                continue
            s = ev.summary.lower()
            if any(p in s for p in patterns):
                kept.append(ev)
            continue

        # Default: keep if it's within a listed course
        kept.append(ev)

    return kept


def rebuild_ical(original_text: str, kept_events: List[Event]) -> str:
    unfolded = unfold_ical(original_text)

    header_match = re.split(r"BEGIN:VEVENT", unfolded, maxsplit=1)
    if len(header_match) == 1:
        return original_text
    header = header_match[0]

    end_positions = [m.end() for m in re.finditer(r"END:VEVENT", unfolded)]
    footer = unfolded[end_positions[-1]:] if end_positions else "\nEND:VCALENDAR\n"

    body = ""
    for ev in kept_events:
        block = ev.raw
        if not block.strip().endswith("END:VEVENT"):
            m = re.search(r"BEGIN:VEVENT.*?END:VEVENT", block, flags=re.DOTALL)
            if m:
                block = m.group(0)
        body += block.strip() + "\n"

    if "BEGIN:VCALENDAR" not in header:
        header = "BEGIN:VCALENDAR\n" + header
    if "END:VCALENDAR" not in footer:
        footer = footer.rstrip() + "\nEND:VCALENDAR\n"

    return header + body + footer


def main():
    if not ICAL_SUBSCRIPTION_URL:
        print("❗ Missing TP_ICAL_URL (set it under Settings → Secrets → Actions).")
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
    print("Tip: host this file (e.g., GitHub Pages) and subscribe to the URL for auto-updates.")


if __name__ == "__main__":
    main()

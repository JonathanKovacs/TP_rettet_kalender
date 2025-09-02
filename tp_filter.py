#!/usr/bin/env python3
from __future__ import annotations
import os, re, sys, urllib.request
from dataclasses import dataclass
from typing import Dict, List

# ----------------- CONFIG -----------------
# Supplied via GitHub Actions secret (Settings → Secrets → Actions → TP_ICAL_URL)
ICAL_SUBSCRIPTION_URL = os.getenv("TP_ICAL_URL", "")

# What to keep for each course (group-like items only).
# Lectures/Seminars/Workshops for listed courses are kept automatically.
COURSE_KEEP_RULES: Dict[str, List[str]] = {
    "INF102": ["time 7"],     # matches "Aktiv time 7" or "Dropp-inn time 7"
    "INF113": ["gruppe 4"],
    "INF214": ["gruppe 1"],
    "MAT111": ["gruppe 02"],
    "MAT221": ["gruppe"],     # keep your MAT221 group (any group)
}

# Words that indicate group-like sessions
GROUP_WORDS = [
    "gruppe", "group", "seminargruppe", "workshopgruppe",
    "aktiv time", "dropp-inn time", "drop-in time", "drop in time",
    "lab", "øving", "övning", "exercise class", "class group"
]

# Words for always-keep teaching types
ALWAYS_KEEP_WORDS = [
    "forelesning", "seminar", "regneverksted", "oppgavesesjon",
    "review", "lecture", "workshop"
]

OUTPUT_FILE = "filtered.ics"
# --------------- END CONFIG ---------------


def http_get(url: str) -> str:
    with urllib.request.urlopen(url) as resp:
        return resp.read().decode("utf-8", errors="replace")


def unfold_ical(text: str) -> str:
    return re.sub(r"(?:\r?\n)[ \t]", "", text)  # RFC5545 unfold


def norm(s: str) -> str:
    """Normalize text for tolerant matching."""
    s = s.lower()
    s = s.replace("–", "-").replace("—", "-")
    s = s.replace("drop-in", "dropp-inn").replace("drop in", "dropp-inn")
    # unify ' 07' -> ' 7' etc
    s = re.sub(r"\b0+(\d)\b", r"\1", s)
    # collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


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
        s = norm(self.summary)
        return any(w in s for w in [norm(w) for w in GROUP_WORDS])

    @property
    def is_always_keep(self) -> bool:
        s = norm(self.summary)
        return any(w in s for w in [norm(w) for w in ALWAYS_KEEP_WORDS])


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
        events.append(Event(raw=blk, summary=prop("SUMMARY"), description=prop("DESCRIPTION")))
    return events


def filter_events(events: List[Event]) -> List[Event]:
    kept: List[Event] = []
    for ev in events:
        code = ev.course_code
        if not code:
            kept.append(ev)  # unknown → keep
            continue

        if code not in COURSE_KEEP_RULES:
            continue  # drop courses you didn't list

        if ev.is_always_keep:
            kept.append(ev)
            continue

        if ev.is_group_like:
            patterns = [norm(p) for p in COURSE_KEEP_RULES.get(code, []) if p.strip()]
            if not patterns:
                continue  # you chose no groups for this course → drop group-like
            s = norm(ev.summary)
            if any(p in s for p in patterns):
                kept.append(ev)
            continue

        # default: keep if it's part of a listed course
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
            if m: block = m.group(0)
        body += block.strip() + "\n"

    if "BEGIN:VCALENDAR" not in header: header = "BEGIN:VCALENDAR\n" + header
    if "END:VCALENDAR" not in footer: footer = footer.rstrip() + "\nEND:VCALENDAR\n"
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

    kept = filter_events(events)
    print(f"Keeping {len(kept)} events")

    out = rebuild_ical(src, kept)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"✅ Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

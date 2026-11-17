"""Command line: build a filing + tracker plan from EOB text files.

    python -m ghi_eob plan --settings settings.json --tracker tracker.json EOB.txt [EOB.txt ...]

Each EOB.txt holds the text Google Drive extracted from one PDF; its file name
(without .txt) is used as the source id, so name it after the Drive file id.
tracker.json is either the "values" array of the whole All Claims tab (header
row first), or {"header": [...], "start_row": N, "values": [...]} holding the
header plus a block of rows starting at sheet row N.
The plan is printed as JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .parser import NotAnEOB, parse
from .plan import filings_for, tracker_updates


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ghi_eob")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="plan filing and tracker updates")
    p.add_argument("--settings", required=True, type=Path)
    p.add_argument("--tracker", type=Path, help="JSON values of the tracker tab; omit to skip tracker matching")
    p.add_argument("eobs", nargs="+", type=Path)
    args = ap.parse_args(argv)

    settings = json.loads(args.settings.read_text())
    sources, parsed, issues = [], [], []
    for path in args.eobs:
        source = {"source": path.stem}
        try:
            eob = parse(path.read_text())
        except NotAnEOB:
            source["skipped"] = "not an NYCE PPO EOB"
            sources.append(source)
            continue
        if not eob.claims:
            source["skipped"] = "looks like an NYCE PPO EOB but no claims could be read"
            sources.append(source)
            continue
        filings, file_issues = filings_for(eob, settings)
        source.update(eob=eob.to_dict(), filings=filings, issues=file_issues)
        sources.append(source)
        parsed.append(eob)

    updates = []
    if args.tracker:
        data = json.loads(args.tracker.read_text())
        if isinstance(data, dict) and "header" in data:
            rows, start = [data["header"]] + data["values"], int(data["start_row"])
        else:
            rows, start = (data["values"] if isinstance(data, dict) else data), 2
        updates, issues = tracker_updates(parsed, rows, settings, start_row=start)

    json.dump({"sources": sources, "tracker_updates": updates, "tracker_issues": issues}, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

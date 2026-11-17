"""Turn parsed EOBs into a plan: where each PDF is filed, which tracker cells change.

Nothing here talks to Google. The plan is a plain dict that the person or
agent running the procedure applies with the Drive and Sheets tools, so every
change can be reviewed first (a dry run is just "make the plan, don't apply it").
"""

from __future__ import annotations

import re
from collections import OrderedDict, defaultdict

from .parser import EOB, Claim

DOCTOR_CREDENTIALS = {"MD", "DO", "PHD", "PSYD", "DDS", "DMD", "DPM", "OD", "DC", "EDD"}


# --- names -------------------------------------------------------------------

def provider_key(raw: str) -> str:
    """'CONTE, VINCENT,A,PHD' -> 'CONTE'; 'LABCORP' -> 'LABCORP'."""
    return raw.split(",")[0].strip().upper()


def guess_provider_names(raw: str) -> dict:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 1:
        name = parts[0].title()
        return {"tracker": name, "file": name}
    last, first = parts[0].title(), parts[1].split()[0].title()
    credentials = {c.upper() for p in parts[2:] for c in p.replace(".", "").split()}
    file_name = f"Dr. {last}" if credentials & DOCTOR_CREDENTIALS else f"{first} {last}"
    return {"tracker": last, "file": file_name}


def provider_names(raw: str, settings: dict) -> tuple[dict, bool]:
    """Return ({'tracker', 'file'}, known) for a provider as printed on the EOB."""
    known = settings.get("providers", {}).get(provider_key(raw))
    if known:
        return known, True
    return guess_provider_names(raw), False


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", name).strip()


# --- filing ------------------------------------------------------------------

def filings_for(eob: EOB, settings: dict) -> tuple[list[dict], list[str]]:
    """One filing per (patient, provider) on the EOB; each gets a named copy of the PDF."""
    groups: "OrderedDict[tuple[str, str], list[Claim]]" = OrderedDict()
    for claim in eob.claims:
        groups.setdefault((claim.patient, provider_key(claim.provider)), []).append(claim)

    filings, issues = [], []
    people = settings.get("people", {})
    for (patient, _), claims in groups.items():
        person = people.get(patient)
        if not person:
            issues.append(f"Patient '{patient}' is not in settings.people, so it was not filed.")
            continue
        provider, known = provider_names(claims[0].provider, settings)
        if not known:
            issues.append(
                f"New provider '{claims[0].provider}': guessed '{provider['file']}' for the file name "
                f"and '{provider['tracker']}' for the tracker. Add it to settings.providers to confirm."
            )
        dates = sorted({line.date for claim in claims for line in claim.lines})
        if not dates:
            issues.append(f"Claim {claims[0].claim_number} has no service dates I could read; not filed.")
            continue
        when = dates[0] if len(dates) == 1 else f"{dates[0]} - {dates[-1]}"
        folder = safe(f"{when} - {person['full']} - {provider['file']}")
        suffix = " - GHI EOB & Check.pdf" if eob.has_check else " - GHI EOB.pdf"
        filings.append(
            {
                "patient": person["short"],
                "person_folder_id": person.get("folder_id", ""),
                "year_folder": f"{dates[0][:4]} Claims",
                "claim_folder": folder,
                "file_name": folder + suffix,
                "claim_numbers": [c.claim_number for c in claims],
            }
        )
    return filings, issues


# --- tracker -----------------------------------------------------------------

def column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def money(value: float) -> str:
    return f"${value:,.2f}"


def _norm(value: str) -> str:
    return value.strip().replace("$", "").replace(",", "").lower()


def tracker_updates(
    eobs: list[EOB], rows: list[list[str]], settings: dict, start_row: int = 2
) -> tuple[list[dict], list[str]]:
    """Match each claimed service date to one tracker row and fill its GHI cells.

    `rows` is the header row followed by data rows; `start_row` is the sheet row
    number of the first data row (2 when the whole tab was read).

    Only empty cells are filled. A cell that already holds a different value is
    reported, never overwritten (except status values listed as overwritable).
    """
    cfg = settings["tracker"]
    cols = cfg["columns"]
    header = rows[0]

    def col(name: str) -> int:
        try:
            return header.index(cols[name])
        except ValueError as exc:
            raise ValueError(f"Tracker has no column '{cols[name]}'") from exc

    c = {name: col(name) for name in cols}

    def cell(row: list[str], name: str) -> str:
        i = c[name]
        return row[i].strip() if i < len(row) else ""

    people = settings.get("people", {})
    overwritable = {v.lower() for v in cfg.get("status_overwritable", [])}
    member_names = set(people)
    updates: list[dict] = []
    issues: list[str] = []
    claimed_rows: dict[int, str] = {}

    for eob in eobs:
        paid_to_member = any(p.to in member_names for p in eob.payments)
        paid_to_provider = any(p.to not in member_names for p in eob.payments)
        paid_to = ""
        if paid_to_provider and not paid_to_member:
            paid_to = cfg.get("paid_to_provider", "")
        elif paid_to_member and not paid_to_provider:
            paid_to = cfg.get("paid_to_member", "")

        for claim in eob.claims:
            person = people.get(claim.patient)
            if not person:
                continue  # already reported by filings_for
            provider, _ = provider_names(claim.provider, settings)
            paid_by_date: dict[str, float] = defaultdict(float)
            for line in claim.lines:
                paid_by_date[line.date] += line.plan_paid

            for date, paid in paid_by_date.items():
                label = f"{date} {person['short']} / {provider['tracker']} (claim {claim.claim_number})"
                candidates = [
                    n for n, row in enumerate(rows[1:], start=start_row)
                    if cell(row, "dos") == date
                    and cell(row, "patient").lower() == person["short"].lower()
                    and cell(row, "provider").lower() == provider["tracker"].lower()
                    and cell(row, "type").lower() != "rx"
                    and n not in claimed_rows
                ]
                same_claim = [n for n in candidates if cell(rows[n - start_row + 1], "claim_number") == claim.claim_number]
                open_rows = [n for n in candidates if not cell(rows[n - start_row + 1], "claim_number")]
                chosen = same_claim or open_rows or candidates
                if not chosen:
                    issues.append(f"No tracker row for {label}, paid {money(paid)}. Add a row, then rerun.")
                    continue
                if len(chosen) > 1:
                    issues.append(f"{len(chosen)} tracker rows match {label} (rows {chosen}); left alone.")
                    continue
                n = chosen[0]
                claimed_rows[n] = claim.claim_number
                row = rows[n - start_row + 1]
                wanted = {
                    "status": cfg["status_value"],
                    "claim_number": claim.claim_number,
                    "paid": money(paid),
                }
                if paid_to:
                    wanted["paid_to"] = paid_to
                for name, value in wanted.items():
                    current = cell(row, name)
                    if _norm(current) == _norm(value):
                        continue
                    if current and not (name == "status" and current.lower() in overwritable):
                        issues.append(
                            f"Row {n} ({label}): '{cols[name]}' already says '{current}', "
                            f"EOB says '{value}'. Not changed."
                        )
                        continue
                    updates.append(
                        {
                            "range": f"'{cfg['sheet']}'!{column_letter(c[name])}{n}",
                            "value": value,
                            "was": current,
                            "row": n,
                            "why": label,
                        }
                    )
    return updates, issues

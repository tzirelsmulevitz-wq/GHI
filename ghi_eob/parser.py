"""Read the text of an NYCE PPO (GHI) Explanation of Benefits into structured data.

The text is what Google Drive's PDF text extraction returns. Line breaks in it
vary from one EOB to the next, so the parser works on labels and on the order
of dates and dollar amounts rather than on fixed line positions.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

MONEY = re.compile(r"\$\s*([\d,]+\.\d{2})")
SERVICE_DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{2})\b")
CLAIM_NUMBER = re.compile(r"Claim Number:\s*(\d{6,})")
PAYMENT = re.compile(
    r"Payment to:\s*(?P<to>.+?)\s*Payment date:\s*(?P<date>[\d-]+)\s*"
    r"Payment amount:\s*\$\s*(?P<amount>[\d,]+\.\d{2})",
    re.S,
)
LABELS = {"patient account:", "plan pays", "you pay", "provider name:", "claim number:"}

# Money columns that follow each service date on a claim line, in order:
# billed, discount, not allowed, PLAN PAID, plan paid (repeated), copay,
# coinsurance, deductible, not covered, TOTAL YOU MAY OWE.
PLAN_PAID_INDEX = 3
YOU_OWE_INDEX = 9
AMOUNTS_PER_LINE = 10


@dataclass
class ServiceLine:
    date: str  # YYYY-MM-DD
    billed: float
    plan_paid: float
    you_may_owe: float


@dataclass
class Claim:
    patient: str  # as printed, e.g. "JANE DOE"
    claim_number: str
    provider: str  # as printed, e.g. "DOE, JOHN, MD"
    lines: list[ServiceLine] = field(default_factory=list)

    @property
    def plan_paid(self) -> float:
        return round(sum(line.plan_paid for line in self.lines), 2)


@dataclass
class Payment:
    to: str
    date: str
    amount: float


@dataclass
class EOB:
    claims: list[Claim]
    payments: list[Payment]
    has_check: bool

    def to_dict(self) -> dict:
        data = asdict(self)
        for claim, raw in zip(self.claims, data["claims"]):
            raw["plan_paid"] = claim.plan_paid
        return data


class NotAnEOB(ValueError):
    """The text is not an NYCE PPO explanation of benefits."""


def is_nyce_eob(text: str) -> bool:
    lowered = text.lower()
    return "explanation of benefits" in lowered and (
        "nyc employees ppo plan" in lowered or "nyce ppo" in lowered
    )


def _money(value: str) -> float:
    return float(value.replace(",", ""))


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _value_after(label: str, block: str) -> str:
    """The text after `label` on its line, or else the next non-label line."""
    lines = _lines(block)
    for i, line in enumerate(lines):
        if line.lower().startswith(label.lower()):
            rest = line[len(label):].strip()
            if rest:
                return rest
            for candidate in lines[i + 1:]:
                if candidate.lower() in LABELS or candidate.isdigit():
                    continue
                return candidate
    return ""


def _service_lines(block: str) -> list[ServiceLine]:
    body = block.split("Totals")[0]
    found = []
    for match in SERVICE_DATE.finditer(body):
        amounts = [_money(m) for m in MONEY.findall(body[match.end():])][:AMOUNTS_PER_LINE]
        if len(amounts) < AMOUNTS_PER_LINE:
            continue
        month, day, year = match.groups()
        found.append(
            ServiceLine(
                date=f"20{year}-{month}-{day}",
                billed=amounts[0],
                plan_paid=amounts[PLAN_PAID_INDEX],
                you_may_owe=amounts[YOU_OWE_INDEX],
            )
        )
    return found


def parse(text: str) -> EOB:
    if not is_nyce_eob(text):
        raise NotAnEOB("text does not look like an NYCE PPO explanation of benefits")

    starts = [m.start() for m in re.finditer(r"Patient:", text)]
    claims = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = text[start:end]
        number = CLAIM_NUMBER.search(block)
        if not number:
            continue
        claims.append(
            Claim(
                patient=_value_after("Patient:", block).upper(),
                claim_number=number.group(1),
                provider=_value_after("Provider Name:", block).upper(),
                lines=_service_lines(block),
            )
        )

    payments = [
        Payment(to=" ".join(m["to"].split()).upper(), date=m["date"], amount=_money(m["amount"]))
        for m in PAYMENT.finditer(text)
    ]
    return EOB(claims=claims, payments=payments, has_check=bool(re.search(r"Check No\.?", text)))

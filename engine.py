"""Deterministic CBC extraction and exact-value lookup."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
ALIASES = {
    "Hemoglobin": ("hemoglobin", "haemoglobin", "hgb", "hb"),
    "WBC": ("wbc", "white blood cell", "white blood cell count", "white blood count", "leukocyte", "total leukocyte count", "total wbc count"),
    "RBC": ("rbc", "red blood cell", "red blood cell count", "red blood count"),
    "Hematocrit": ("hematocrit", "haematocrit", "hct", "pcv"),
    "MCV": ("mcv", "mean corpuscular volume"),
    "Platelets": ("platelets", "platelet", "platelet count", "plt"),
}
NUM = r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?"
RANGE = re.compile(rf"({NUM})\s*(?:-|–|—|to)\s*({NUM})", re.IGNORECASE)
URGENT_PHRASES = ("chest pain", "cannot breathe", "can't breathe", "severe difficulty breathing", "fainted", "unconscious", "severe bleeding")


@dataclass(frozen=True)
class Result:
    marker: str
    value: float
    unit: str
    low: float | None
    high: float | None
    line_number: int
    raw_line: str

    @property
    def status(self) -> str:
        if self.low is None or self.high is None:
            return "Range missing"
        if self.value < self.low:
            return "Below report range"
        if self.value > self.high:
            return "Above report range"
        return "Within report range"

    @property
    def range_label(self) -> str:
        return f"{self.low:g}–{self.high:g} {self.unit}" if self.low is not None and self.high is not None else "Not shown"


def _normalize_number(value: str) -> float:
    return float(value.replace(",", ""))


def _line_match(line: str):
    clean = line.strip().strip("| ")
    for marker, aliases in ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            match = re.match(rf"^{re.escape(alias)}(?=\s|\||:|\d)", clean, re.IGNORECASE)
            if match:
                return marker, clean[match.end():].strip(" |:\t")
    return None, None


def parse_report(text: str) -> dict[str, Result]:
    """Parse supported CBC rows and use only the range printed on that row."""
    found: dict[str, Result] = {}
    conflicts: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        marker, tail = _line_match(raw_line)
        if marker is None or tail is None:
            continue
        prefix_unit = ''
        parenthetical = re.match(r'^\(([^)]*)\)\s*', tail)
        if parenthetical:
            if re.search(r'[/^%]|fL|g/dL', parenthetical.group(1)):
                prefix_unit = parenthetical.group(1)
            tail = tail[parenthetical.end():]
        value_match = re.search(NUM, tail)
        if not value_match:
            continue
        value = _normalize_number(value_match.group())
        after_value = tail[value_match.end():]
        range_match = RANGE.search(after_value)
        unit_area = after_value[:range_match.start()] if range_match else after_value
        unit = re.sub(r'\s+', ' ', unit_area.replace('|', ' ')).strip(" :()[]\t")
        unit = re.sub(r'^(?:H|L|High|Low)\s+', '', unit)
        unit = re.sub(r'\s*(?:reference|ref\.?|range)\s*:?.*$', '', unit, flags=re.I)
        unit = unit or prefix_unit or "unit not shown"
        low = _normalize_number(range_match.group(1)) if range_match else None
        high = _normalize_number(range_match.group(2)) if range_match else None
        if low is not None and high is not None and low > high:
            low, high = None, None
        candidate = Result(marker, value, unit, low, high, line_number, raw_line.strip())
        if marker in found and (found[marker].value, found[marker].unit, found[marker].low, found[marker].high) != (value, unit, low, high):
            conflicts.add(marker)
        found[marker] = candidate
    for marker in conflicts:
        found.pop(marker, None)
    return found


def selected_markers(question: str, results: dict[str, Result]) -> list[str]:
    words = question.lower()
    explicit = [marker for marker, aliases in ALIASES.items() if marker in results and any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", words) for alias in aliases)]
    if explicit:
        return explicit
    abnormal = [marker for marker, result in results.items() if result.status in ("Below report range", "Above report range")]
    return abnormal[:3] or list(results)[:3]


def lookup_result(marker: str, results: dict[str, Result]) -> dict[str, Any]:
    canonical = next((name for name, aliases in ALIASES.items() if marker.lower() == name.lower() or marker.lower() in aliases), None)
    if not canonical or canonical not in results:
        return {"error": "That test was not found in the uploaded report."}
    result = results[canonical]
    return {"marker": result.marker, "value": result.value, "unit": result.unit, "report_range": result.range_label,
            "status": result.status, "report_line": result.line_number}


TOOLS = [
    {"type": "function", "function": {"name": "lookup_result", "description": "Get the exact CBC value, unit, and report interval. Call before quoting a number.", "parameters": {"type": "object", "properties": {"marker": {"type": "string"}}, "required": ["marker"]}}},
    {"type": "function", "function": {"name": "request_consultation", "description": "Record a local synthetic consultation request only if explicitly asked. This does not book a real clinician.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
]

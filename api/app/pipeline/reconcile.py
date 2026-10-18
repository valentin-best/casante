"""Merge the same item across documents and flag where documents disagree.

Items with the same normalized key are the same thing. Mentions that agree become one
item citing every source. Mentions that disagree on dose, frequency or a lab value stay
separate items, and a conflict lists each side with its sources: the app never decides
which one is right.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Hashable
from typing import Any

Item = dict[str, Any]

# Unit conversions round, so 5.5 mmol/L (99.09 mg/dL) is the same glucose as 99 mg/dL
LAB_TOLERANCE = 0.01
# Documents expected to list every allergy. Lab reports and prescriptions often don't.
ALLERGY_LISTING_TYPES = {"discharge_summary", "clinic_letter"}


def reconcile_record(record: dict[str, Any]) -> None:
    """Merge items in place and fill `conflicts`. Runs after normalize_record."""
    dates = {doc["id"]: doc["date"] for doc in record["documents"]}
    conflicts: list[dict[str, Any]] = []

    def by_date(items: list[Item]) -> list[Item]:
        """Oldest first. Undated documents count as oldest so they never supersede."""
        return sorted(items, key=lambda item: _date(item, dates) or "")

    record["medications"] = _medications(record["medications"], by_date, conflicts)
    record["labs"] = _labs(record["labs"], by_date, conflicts)
    record["allergies"] = _allergies(
        record["allergies"], record["documents"], by_date, conflicts
    )
    record["conditions"] = [
        _merge(by_date(mentions)) for mentions in _group(record["conditions"], _key)
    ]
    record["procedures"] = [
        _merge(by_date(mentions))
        for mentions in _group(record["procedures"], lambda p: (_key(p), p.get("date")))
    ]
    record["conflicts"] = conflicts


def _key(item: Item) -> str:
    return item["normalized"]["key"]


def _date(item: Item, dates: dict[str, str | None]) -> str | None:
    """Date of the document an item came from (before merging, each has one source)."""
    return dates.get(item["sources"][0]["document_id"])


def _group(items: list[Item], key: Callable[[Item], Hashable]) -> list[list[Item]]:
    groups: dict[Hashable, list[Item]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return list(groups.values())


def _cluster(
    mentions: list[Item], agree: Callable[[Item, Item], bool]
) -> list[list[Item]]:
    """Split mentions into groups where every pair agrees, in order of first mention."""
    clusters: list[list[Item]] = []
    for mention in mentions:
        for cluster in clusters:
            if all(agree(mention, other) for other in cluster):
                cluster.append(mention)
                break
        else:
            clusters.append([mention])
    return clusters


def _merge(mentions: list[Item]) -> Item:
    """Fields from the latest mention, gaps filled from older ones; every source kept."""
    merged: Item = {}
    normalized: dict[str, Any] = {}
    for mention in reversed(mentions):
        for field, value in mention.items():
            if field not in ("sources", "normalized") and merged.get(field) is None:
                merged[field] = value
        for field, value in mention["normalized"].items():
            if normalized.get(field) is None:
                normalized[field] = value
    merged["sources"] = [
        source for mention in mentions for source in mention["sources"]
    ]
    merged["normalized"] = normalized
    return merged


def _conflict(
    kind: str,
    section: str,
    key: str,
    name: str,
    variants: list[tuple[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "section": section,
        "key": key,
        "name": name,
        "variants": [
            {"value": value, "sources": sources} for value, sources in variants
        ],
    }


def _unknown_or_equal(a: Any, b: Any) -> bool:
    return a is None or b is None or a == b


# ------------------------------------------------------------------ medications


def _dose(med: Item) -> tuple[float, str] | None:
    normalized = med["normalized"]
    if normalized["dose_value"] is None:
        return None
    return normalized["dose_value"], normalized["dose_unit"]


def _same_regimen(a: Item, b: Item) -> bool:
    """A dose or frequency missing from one document is not a disagreement."""
    return _unknown_or_equal(_dose(a), _dose(b)) and _unknown_or_equal(
        a["normalized"]["times_per_day"], b["normalized"]["times_per_day"]
    )


def _regimen(med: Item) -> str:
    return " ".join(part for part in (med.get("dose"), med.get("frequency")) if part)


def _medications(
    items: list[Item],
    by_date: Callable[[list[Item]], list[Item]],
    conflicts: list[dict[str, Any]],
) -> list[Item]:
    """A stop supersedes earlier mentions; later mentions are a restart, compared alone."""
    result = []
    for mentions in _group(items, _key):
        current = by_date(mentions)
        stops = [i for i, med in enumerate(current) if med.get("status") == "stopped"]
        if stops:
            result.append(_merge(current[: stops[-1] + 1]))
            current = current[stops[-1] + 1 :]

        merged = [_merge(cluster) for cluster in _cluster(current, _same_regimen)]
        result.extend(merged)
        if len(merged) > 1:
            doses = {_dose(med) for med in merged} - {None}
            conflicts.append(
                _conflict(
                    "dose" if len(doses) > 1 else "frequency",
                    "medications",
                    _key(current[-1]),
                    current[-1]["name"],
                    [(_regimen(med), med["sources"]) for med in merged],
                )
            )
    return result


# ------------------------------------------------------------------ labs


def _same_value(a: Item, b: Item) -> bool:
    va, vb = a["normalized"]["value"], b["normalized"]["value"]
    if va is None or vb is None:
        return True
    return a["normalized"]["unit"] == b["normalized"]["unit"] and math.isclose(
        va, vb, rel_tol=LAB_TOLERANCE
    )


def _result(lab: Item) -> str:
    if lab.get("value") is None:
        return "No value"
    return f"{lab['value']:g} {lab.get('unit') or ''}".strip()


def _labs(
    items: list[Item],
    by_date: Callable[[list[Item]], list[Item]],
    conflicts: list[dict[str, Any]],
) -> list[Item]:
    """Results on different dates are a trend, not duplicates: only same-date ones merge."""
    result = []
    for mentions in _group(items, lambda lab: (_key(lab), lab.get("date"))):
        ordered = by_date(mentions)
        merged = [_merge(cluster) for cluster in _cluster(ordered, _same_value)]
        result.extend(merged)
        if len(merged) > 1:
            conflicts.append(
                _conflict(
                    "lab_value",
                    "labs",
                    _key(ordered[-1]),
                    ordered[-1]["test"],
                    [(_result(lab), lab["sources"]) for lab in merged],
                )
            )
    return result


# ------------------------------------------------------------------ allergies


def _allergies(
    items: list[Item],
    documents: list[dict[str, Any]],
    by_date: Callable[[list[Item]], list[Item]],
    conflicts: list[dict[str, Any]],
) -> list[Item]:
    """Flag an allergy that a document expected to list allergies leaves out."""
    listing = [doc["id"] for doc in documents if doc["type"] in ALLERGY_LISTING_TYPES]
    result = []
    for mentions in _group(items, _key):
        allergy = _merge(by_date(mentions))
        result.append(allergy)
        cited = {source["document_id"] for source in allergy["sources"]}
        missing = [doc_id for doc_id in listing if doc_id not in cited]
        if missing:
            conflicts.append(
                _conflict(
                    "allergy_missing",
                    "allergies",
                    _key(allergy),
                    allergy["substance"],
                    [
                        ("Listed", allergy["sources"]),
                        (
                            "Not listed",
                            [{"document_id": d, "evidence": []} for d in missing],
                        ),
                    ],
                )
            )
    return result

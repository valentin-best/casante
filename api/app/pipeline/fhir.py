"""Convert a unified record into a FHIR R4 collection Bundle."""

from __future__ import annotations

from typing import Any

FHIR_SOURCE_URL = "https://casante.dev/fhir/StructureDefinition/source"


def _code(
    text: str | None, system: str | None = None, code: str | None = None
) -> dict[str, Any]:
    coding: dict[str, Any] = {}
    if system is not None:
        coding["system"] = system
    if code is not None:
        coding["code"] = code
    result: dict[str, Any] = {"text": text or "Unknown"}
    if coding:
        result["coding"] = [coding]
    return result


def _source_extension(item: dict[str, Any]) -> dict[str, Any] | None:
    sources = item.get("sources")
    if not sources:
        return None
    return {
        "url": FHIR_SOURCE_URL,
        "valueString": "; ".join(
            f"{source.get('document_id', 'unknown')}: "
            f"{', '.join(source.get('evidence') or [])}"
            for source in sources
        ),
    }


def _resource(
    resource: dict[str, Any], item: dict[str, Any] | None = None
) -> dict[str, Any]:
    if item is not None:
        extension = _source_extension(item)
        if extension:
            resource["extension"] = [extension]
    return resource


def _patient_reference(patient_id: str | None) -> dict[str, str] | None:
    return {"reference": f"Patient/{patient_id}"} if patient_id else None


def _add_patient(resource: dict[str, Any], patient_id: str | None) -> None:
    subject = _patient_reference(patient_id)
    if subject:
        resource["subject"] = subject


def _medication(
    item: dict[str, Any], index: int, patient_id: str | None
) -> dict[str, Any]:
    status = item.get("status")
    status_map = {"changed": "unknown", "stopped": "stopped"}
    resource: dict[str, Any] = {
        "resourceType": "MedicationStatement",
        "id": f"medication-{index}",
        "status": status_map.get(status, status or "unknown"),
        "medicationCodeableConcept": _code(
            item.get("name"),
            "http://www.nlm.nih.gov/research/umls/rxnorm"
            if item.get("normalized", {}).get("rxcui")
            else None,
            item.get("normalized", {}).get("rxcui"),
        ),
    }
    _add_patient(resource, patient_id)
    dosage: dict[str, Any] = {}
    if item.get("dose") or item.get("route") or item.get("frequency"):
        dosage["text"] = " ".join(
            part
            for part in (item.get("dose"), item.get("route"), item.get("frequency"))
            if part
        )
        resource["dosage"] = [dosage]
    if item.get("start_date"):
        resource["effectivePeriod"] = {"start": item["start_date"]}
        if item.get("stop_date"):
            resource["effectivePeriod"]["end"] = item["stop_date"]
    return _resource(resource, item)


def _allergy(
    item: dict[str, Any], index: int, patient_id: str | None
) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "AllergyIntolerance",
        "id": f"allergy-{index}",
        "clinicalStatus": _code(
            "active",
            "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
            "active",
        ),
        "code": _code(item.get("substance")),
    }
    severity = item.get("severity")
    if severity and severity != "unknown":
        resource["reaction"] = [
            {"manifestation": [_code(item.get("reaction"))], "severity": severity}
        ]
    _add_patient(resource, patient_id)
    return _resource(resource, item)


def _condition(
    item: dict[str, Any], index: int, patient_id: str | None
) -> dict[str, Any]:
    status = item.get("status") or "unknown"
    resource: dict[str, Any] = {
        "resourceType": "Condition",
        "id": f"condition-{index}",
        "clinicalStatus": _code(
            status, "http://terminology.hl7.org/CodeSystem/condition-clinical", status
        ),
        "code": _code(item.get("name")),
    }
    if item.get("onset_date"):
        resource["onsetDateTime"] = item["onset_date"]
    _add_patient(resource, patient_id)
    return _resource(resource, item)


def _observation(
    item: dict[str, Any], index: int, patient_id: str | None
) -> dict[str, Any]:
    normalized = item.get("normalized") or {}
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"observation-{index}",
        "status": "final",
        "category": [
            _code(
                "Laboratory",
                "http://terminology.hl7.org/CodeSystem/observation-category",
                "laboratory",
            )
        ],
        "code": _code(item.get("test"), "http://loinc.org", normalized.get("loinc")),
    }
    if item.get("value") is not None:
        resource["valueQuantity"] = {"value": item["value"]}
        if item.get("unit"):
            resource["valueQuantity"]["unit"] = item["unit"]
    if item.get("reference_range"):
        resource["referenceRange"] = [{"text": item["reference_range"]}]
    if item.get("flag") and item["flag"] != "normal":
        resource["interpretation"] = [_code(item["flag"])]
    if item.get("date"):
        resource["effectiveDateTime"] = item["date"]
    _add_patient(resource, patient_id)
    return _resource(resource, item)


def _procedure(
    item: dict[str, Any], index: int, patient_id: str | None
) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "Procedure",
        "id": f"procedure-{index}",
        "status": "completed" if item.get("date") else "unknown",
        "code": _code(item.get("name")),
    }
    if item.get("date"):
        resource["performedDateTime"] = item["date"]
    _add_patient(resource, patient_id)
    return _resource(resource, item)


def _document(
    item: dict[str, Any], index: int, patient_id: str | None
) -> dict[str, Any]:
    attachment: dict[str, Any] = {"title": item.get("filename") or f"document-{index}"}
    resource: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "id": f"document-{index}",
        "status": "current",
        "type": _code(item.get("type")),
        "content": [{"attachment": attachment}],
    }
    if item.get("date"):
        resource["date"] = item["date"]
    _add_patient(resource, patient_id)
    return resource


def record_to_fhir(
    record: dict[str, Any], patient_id: str | None = None
) -> dict[str, Any]:
    """Return a FHIR R4 collection Bundle for a reconciled unified record."""
    resources: list[dict[str, Any]] = []
    mappings = (
        ("medications", _medication),
        ("allergies", _allergy),
        ("conditions", _condition),
        ("labs", _observation),
        ("procedures", _procedure),
    )
    for section, mapper in mappings:
        resources.extend(
            mapper(item, index, patient_id)
            for index, item in enumerate(record.get(section, []), 1)
        )
    resources.extend(
        _document(document, index, patient_id)
        for index, document in enumerate(record.get("documents", []), 1)
    )
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "fullUrl": f"urn:uuid:{resource['resourceType']}-{resource['id']}",
                "resource": resource,
            }
            for resource in resources
        ],
    }


build_fhir_bundle = record_to_fhir

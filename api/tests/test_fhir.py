from app.pipeline.fhir import record_to_fhir


def test_record_to_fhir_maps_all_record_sections():
    bundle = record_to_fhir(
        {
            "medications": [
                {"name": "Metformin", "status": "active", "dose": "500 mg"}
            ],
            "allergies": [
                {"substance": "Penicillin", "reaction": "rash", "severity": "moderate"}
            ],
            "conditions": [
                {"name": "Diabetes", "status": "active", "onset_date": "2020-01-01"}
            ],
            "labs": [
                {
                    "test": "Glucose",
                    "value": 99,
                    "unit": "mg/dL",
                    "normalized": {"loinc": "2345-7"},
                }
            ],
            "procedures": [{"name": "Appendectomy", "date": "2024-01-01"}],
            "documents": [
                {
                    "id": "doc-1",
                    "filename": "report.pdf",
                    "type": "lab_report",
                    "date": "2024-01-01",
                }
            ],
        },
        patient_id="patient-1",
    )

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert [entry["resource"]["resourceType"] for entry in bundle["entry"]] == [
        "MedicationStatement",
        "AllergyIntolerance",
        "Condition",
        "Observation",
        "Procedure",
        "DocumentReference",
    ]
    assert bundle["entry"][0]["resource"]["subject"] == {
        "reference": "Patient/patient-1"
    }
    assert bundle["entry"][3]["resource"]["code"]["coding"][0]["code"] == "2345-7"


def test_record_to_fhir_omits_empty_optional_fields():
    bundle = record_to_fhir({"medications": [{"name": "Aspirin"}]})
    medication = bundle["entry"][0]["resource"]

    assert medication["status"] == "unknown"
    assert "dosage" not in medication
    assert "effectivePeriod" not in medication

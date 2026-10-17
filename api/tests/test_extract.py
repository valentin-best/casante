import json
from pathlib import Path

from app.pipeline.extract import extract_document
from app.pipeline.ingest import IngestResult, Line, Page


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        return next(self.responses)


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


class Response:
    def __init__(self, text):
        self.text = text


def document() -> IngestResult:
    return IngestResult(
        file_hash="a" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                image_path="unused.png",
                needs_ocr=False,
                lines=[Line(id="p1-L1", page=1, text="Aspirin 100 mg", bbox=[0, 0, 1, 1])],
            )
        ],
    )


def payload(evidence):
    return {
        "document": {"type": None, "provider": None, "date": None},
        "medications": [
            {
                "name": "Aspirin",
                "dose": "100 mg",
                "route": None,
                "frequency": None,
                "status": None,
                "start_date": None,
                "stop_date": None,
                "evidence": evidence,
            }
        ],
        "allergies": [],
        "conditions": [],
        "labs": [],
        "procedures": [],
    }


def test_drops_items_with_no_existing_evidence(tmp_path: Path):
    client = FakeClient([Response(json.dumps(payload(["p1-L404"])))])

    result = extract_document(document(), client=client, cache_dir=tmp_path)

    assert result.medications == []
    assert client.models.calls == 1


def test_retries_invalid_json_and_caches_valid_result(tmp_path: Path):
    client = FakeClient(
        [Response("{not json"), Response(json.dumps(payload(["p1-L1"])))]
    )

    first = extract_document(document(), client=client, cache_dir=tmp_path, sleep=lambda _: None)
    second = extract_document(document(), client=client, cache_dir=tmp_path)

    assert first.medications[0].evidence == ["p1-L1"]
    assert second == first
    assert client.models.calls == 2

import json

import pytest
from PIL import Image

from test_scoring import _cell
from regnskapsnoter_eval import iterate


def setup_iteration(tmp_path, monkeypatch):
    rasters = tmp_path / "rasters"
    truth = tmp_path / "truth"
    rasters.mkdir()
    truth.mkdir()
    Image.new("RGB", (200, 100), "white").save(rasters / "123_page0012.png")
    (truth / "123.json").write_text("{}")
    monkeypatch.setattr(iterate, "load_truth_from_local", lambda path: {})
    monkeypatch.setattr(iterate, "truth_numbers", lambda data, **kwargs: {"123": {11103}})

    class Voter:
        def __init__(self, **kwargs):
            pass

        def run(self, image, rects):
            return [_cell("Note 4 Bankinnskudd"), _cell("Bundne midler kr 11 103.")]

    monkeypatch.setattr(iterate, "TesseractVoter", Voter)
    monkeypatch.setattr(iterate, "TesseractTsvVoter", Voter)
    return rasters, truth, tmp_path / "out"


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_iteration_reuses_v2_audit_without_claiming_consensus(tmp_path, monkeypatch):
    rasters, truth, output = setup_iteration(tmp_path, monkeypatch)
    result = iterate.run_iteration(rasters, truth, "123", output)
    audit = records(output / "audit.jsonl")
    observations = records(output / "observations.jsonl")
    assert len(audit) == 2
    assert len(observations) == 4
    assert result["recovered_by_all"] == 1
    for entry in audit:
        assert entry["_meta"]["audit_schema_version"] == "v2"
        assert entry["_meta"]["document_id"] == "123"
        assert entry["_meta"]["page_no"] == 12
        assert entry["_meta"]["page_size"] == [200, 100]
        assert entry["consensus"] == []
        assert entry["diagnostics"]["iteration"]["consensus_computed"] is False
        engine = entry["diagnostics"]["iteration"]["engine"]
        expected = [row for row in observations if row["engine"] == engine]
        assert [c["text"] for c in entry["per_voter"][engine]] == [c["text"] for c in expected]
        assert [c["bbox"] for c in entry["per_voter"][engine]] == [c["bbox"] for c in expected]
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["audit"]["path"] == "audit.jsonl"


@pytest.mark.parametrize("failed_stage", ["note_candidates", "score_engine_text", "spatial_evidence"])
def test_completed_ocr_survives_downstream_failure(tmp_path, monkeypatch, failed_stage):
    rasters, truth, output = setup_iteration(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("downstream evaluation failed")

    monkeypatch.setattr(iterate, failed_stage, fail)
    with pytest.raises(RuntimeError, match="downstream evaluation failed"):
        iterate.run_iteration(rasters, truth, "123", output)
    audit = records(output / "audit.jsonl")
    assert len(audit) == 1
    assert audit[0]["diagnostics"]["iteration"]["stage"] == "ocr_completed"
    assert len(audit[0]["per_voter"]["tesseract"]) == 2
    assert len(records(output / "observations.jsonl")) == 2
    assert not (output / "evaluation.json").exists()

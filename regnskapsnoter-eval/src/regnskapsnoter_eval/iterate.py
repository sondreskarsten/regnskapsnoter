from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
from time import perf_counter
from pathlib import Path

from PIL import Image
from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_cascade_ocr.voters import TesseractVoter, TesseractTsvVoter
from regnskapsnoter_eval import load_truth_from_local, truth_numbers
from regnskapsnoter_eval.scoring import score_page_consensus, score_engine_text
from regnskapsnoter_eval.spatial import spatial_evidence


def run_iteration(raster_dir: Path, truth_dir: Path, orgnr: str, output: Path) -> dict:
    pages = sorted(raster_dir.glob(f"{orgnr}_page*.png"))
    if not pages:
        raise ValueError(f"No page rasters for {orgnr}")
    truth = truth_numbers(load_truth_from_local(truth_dir), drop_zero=True)
    if orgnr not in truth:
        raise ValueError(f"No reference values for {orgnr}")
    output.mkdir(parents=True, exist_ok=False)
    voters = {
        "tesseract": TesseractVoter(lang=["no", "nb"]),
        "tesseract_tsv": TesseractTsvVoter(lang=["no", "nb"]),
    }
    observations = {name: [] for name in voters}
    recovered = {name: set() for name in voters}
    spatial_recovered = {name: set() for name in voters}
    manifest = {
        "orgnr": orgnr,
        "metric": "document_integer_recovery",
        "spatial_diagnostic": {"min_vertical_overlap": 0.5, "max_gap_height_ratio": 1.5},
        "reference_sha256": hashlib.sha256((truth_dir / f"{orgnr}.json").read_bytes()).hexdigest(),
        "packages": {name: version(name) for name in ["regnskapsnoter-eval", "docling-cascade-ocr", "docling-core"]},
        "pages": [],
        "limitations": ["Two configurations of Tesseract are correlated.",
                       "Number recovery does not establish concept, period or cell accuracy."],
    }
    with (output / "observations.jsonl").open("w") as stream, (output / "progress.jsonl").open("w") as progress, (output / "spatial-evidence.jsonl").open("w") as spatial_stream:
        for path in pages:
            manifest["pages"].append({"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            with Image.open(path) as image:
                rect = BoundingBox(l=0, t=0, r=image.width, b=image.height, coord_origin=CoordOrigin.TOPLEFT)
                for name, voter in voters.items():
                    started = perf_counter()
                    cells = list(voter.run(image, [rect]))
                    observations[name].append(cells)
                    score = score_engine_text(engine=name, orgnr=orgnr,
                                              text="\n".join(c.text for c in cells),
                                              truth=truth[orgnr])
                    evidence = spatial_evidence(cells, truth[orgnr])
                    spatial_hits = {n for item in evidence for n in item["values"]}
                    spatial_recovered[name].update(spatial_hits)
                    for item in evidence:
                        spatial_stream.write(json.dumps({
                            "page": path.name, "engine": name, **item,
                        }, ensure_ascii=False) + "\n")
                    spatial_stream.flush()
                    newly_recovered = score.recovered - recovered[name]
                    recovered[name].update(score.recovered)
                    progress.write(json.dumps({
                        "page": path.name, "engine": name,
                        "seconds": perf_counter() - started,
                        "n_cells": len(cells),
                        "empty_output": not any(c.text.strip() for c in cells),
                        "page_recovered": sorted(score.recovered),
                        "spatial_recovered": sorted(spatial_hits),
                        "requires_spatial_review": sorted(score.recovered - spatial_hits),
                        "newly_recovered": sorted(newly_recovered),
                        "cumulative_recovered": sorted(recovered[name]),
                        "remaining_document_reference_values": sorted(truth[orgnr] - recovered[name]),
                    }) + "\n")
                    progress.flush()
                    for cell in cells:
                        bbox = cell.rect.to_bounding_box()
                        stream.write(json.dumps({
                            "page": path.name, "engine": name, "text": cell.text,
                            "confidence": cell.confidence,
                            "bbox": [bbox.l, bbox.t, bbox.r, bbox.b],
                        }, ensure_ascii=False) + "\n")
    reports = score_page_consensus(orgnr=orgnr, per_voter_pages=observations,
                              truth=truth[orgnr], min_voters_for_reliable=len(voters))
    result = {
        "n_reference_values": len(reports),
        "recovered_by_any": sum(r.n_hit > 0 for r in reports),
        "recovered_by_all": sum(r.unanimous for r in reports),
        "values": [asdict(r) for r in reports],
        "spatial_recovered_by_engine": {name: sorted(values) for name, values in spatial_recovered.items()},
        "requires_spatial_review_by_engine": {name: sorted(recovered[name] - spatial_recovered[name]) for name in voters},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (output / "evaluation.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raster-dir", type=Path, required=True)
    parser.add_argument("--truth-dir", type=Path, required=True)
    parser.add_argument("--orgnr", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_iteration(args.raster_dir, args.truth_dir, args.orgnr, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "values"}))


if __name__ == "__main__":
    main()

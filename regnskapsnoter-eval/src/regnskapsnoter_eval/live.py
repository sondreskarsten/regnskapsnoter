from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

import fitz
import requests

from .iterate import run_iteration

BASE = "https://data.brreg.no/regnskapsregisteret/regnskap"


def get_bytes(url: str, accept: str) -> bytes:
    for attempt in range(4):
        response = requests.get(url, headers={"Accept": accept}, timeout=(15, 120))
        limited = response.status_code == 429 or b"Too many requests" in response.content[:500]
        if limited or response.status_code in (500, 502, 503, 504):
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
        response.raise_for_status()
        if limited:
            raise RuntimeError("BRREG rate limit persisted after four attempts")
        return response.content
    raise RuntimeError("No response")


def select_reference(raw: bytes, years: list[int], year: int | None = None) -> dict:
    records = json.loads(raw)
    if not isinstance(records, list):
        records = [records]
    candidates = []
    for record in records:
        end = str(record.get("regnskapsperiode", {}).get("tilDato", ""))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
            actual_year = int(end[:4])
            if actual_year in years and (year is None or year == actual_year):
                candidates.append(record)
    if len(candidates) != 1:
        raise ValueError(f"Expected one matching reference; found {len(candidates)}")
    return candidates[0]


def numeric_metrics(record: dict) -> dict:
    result = {}
    def walk(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if float(value).is_integer():
                result[path] = value
    for section in ("resultatregnskapResultat", "eiendeler", "egenkapitalGjeld"):
        walk(record.get(section, {}), section)
    if not result:
        raise ValueError("No integer financial reference values")
    return result


def collect_and_run(orgnr: str, output: Path, year: int | None = None, max_pages: int = 60) -> dict:
    if not re.fullmatch(r"\d{9}", orgnr):
        raise ValueError("orgnr must contain nine digits")
    output.mkdir(parents=True, exist_ok=False)
    journal = {"orgnr": orgnr, "started_at": datetime.now(timezone.utc).isoformat(),
               "status": "started", "requests": []}
    manifest_path = output / "collection.json"
    def persist():
        manifest_path.write_text(json.dumps(journal, indent=2), encoding="utf-8")
    def fetch(name, url, accept):
        body = get_bytes(url, accept)
        (output / name).write_bytes(body)
        journal["requests"].append({"url": url, "accept": accept, "file": name,
                                    "sha256": hashlib.sha256(body).hexdigest(),
                                    "bytes": len(body), "received_at": datetime.now(timezone.utc).isoformat()})
        persist()
        time.sleep(1)
        return body
    persist()
    try:
        years_raw = fetch("years.json", f"{BASE}/aarsregnskap/kopi/{orgnr}/aar", "application/json")
        years = [int(y) for y in json.loads(years_raw)]
        raw = fetch("reference-raw.json", f"{BASE}/{orgnr}", "application/json")
        record = select_reference(raw, years, year)
        period = record["regnskapsperiode"]
        selected_year = int(period["tilDato"][:4])
        journal.update(year=selected_year, period=period, journalnr=record.get("journalnr"))
        pdf = fetch("source.pdf", f"{BASE}/aarsregnskap/kopi/{orgnr}/{selected_year}",
                    "application/octet-stream")
        if not pdf.lstrip().startswith(b"%PDF-"):
            raise ValueError("Kopi response is not a PDF")
        raster_dir = output / "rasters"
        raster_dir.mkdir()
        with fitz.open(stream=pdf, filetype="pdf") as document:
            journal["page_count"] = len(document)
            persist()
            if not 0 < len(document) <= max_pages:
                raise ValueError(f"Page count {len(document)} exceeds bound {max_pages}")
            for index, page in enumerate(document):
                pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
                pix.save(str(raster_dir / f"{orgnr}_page{index + 1:04d}.png"))
        truth_dir = output / "truth"
        truth_dir.mkdir()
        reference = {"orgnr": orgnr, "journalnr": record.get("journalnr"),
                     "period_from": period.get("fraDato"), "period_to": period["tilDato"],
                     "key_metrics": numeric_metrics(record), "raw_response": record}
        (truth_dir / f"{orgnr}.json").write_text(json.dumps(reference), encoding="utf-8")
        result = run_iteration(raster_dir, truth_dir, orgnr, output / "engine")
        journal.update(status="completed", result={k: v for k, v in result.items() if k != "values"})
        return journal
    except Exception as error:
        journal.update(status="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        journal["finished_at"] = datetime.now(timezone.utc).isoformat()
        persist()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--orgnr", nargs="+", required=True)
    parser.add_argument("--year", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=60)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for orgnr in args.orgnr:
        try:
            summaries.append(collect_and_run(orgnr, args.output / orgnr, args.year, args.max_pages))
        except Exception as error:
            summaries.append({"orgnr": orgnr, "status": "failed", "error": str(error)})
    (args.output / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(json.dumps(summaries))
    if any(r["status"] != "completed" for r in summaries):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

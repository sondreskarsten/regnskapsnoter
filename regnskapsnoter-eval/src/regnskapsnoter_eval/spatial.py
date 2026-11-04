from __future__ import annotations

from .scoring import number_present


def spatial_evidence(cells, truth):
    signs = {"-", "\u2212", "(", ")"}
    rows = []
    for index, cell in enumerate(cells):
        box = cell.rect.to_bounding_box()
        top, bottom = sorted((box.t, box.b))
        left, right = sorted((box.l, box.r))
        rows.append((index, cell.text, left, top, right, bottom))
    rows.sort(key=lambda row: (row[3], row[2], row[0]))
    lines = []
    for row in rows:
        height = row[5] - row[3]
        candidates = [
            line for line in lines
            if height > 0 and line["bottom"] > line["top"]
            and min(row[5], line["bottom"]) - max(row[3], line["top"])
            >= 0.5 * (min(height, line["bottom"] - line["top"])
                      if row[1].strip() in signs or all(c[1].strip() in signs for c in line["cells"])
                      else max(height, line["bottom"] - line["top"]))
        ]
        if candidates:
            line = min(candidates, key=lambda line: abs(row[3] - line["top"]))
            line["cells"].append(row)
        else:
            lines.append({"top": row[3], "bottom": row[5], "cells": [row]})
    segments = []
    for line in lines:
        current = []
        for row in sorted(line["cells"], key=lambda row: (row[2], row[0])):
            if current:
                previous = current[-1]
                gap = row[2] - previous[4]
                heights = (row[5] - row[3], previous[5] - previous[3])
                height = (max(heights) if row[1].strip() in signs or previous[1].strip() in signs
                          else min(heights))
                if gap < 0 or height <= 0 or gap > 1.5 * height:
                    segments.append(current)
                    current = []
            current.append(row)
        if current:
            segments.append(current)
    evidence = []
    for segment in segments:
        text = " ".join(row[1] for row in segment)
        hits = sorted(n for n in truth if number_present(n, text))
        if hits:
            evidence.append({
                "values": hits,
                "text": text,
                "cell_indices": [row[0] for row in segment],
                "bbox": [min(row[2] for row in segment),
                         min(row[3] for row in segment),
                         max(row[4] for row in segment),
                         max(row[5] for row in segment)],
            })
    return evidence

from __future__ import annotations

import re

_HEADING = re.compile(r"^\s*Note\s+([0-9]+|I)\s*[:.)-]?\s+(\S.*)$", re.IGNORECASE)


def note_candidates(cells, *, page, engine):
    cells = list(cells)
    headings = [(index, _HEADING.match(cell.text)) for index, cell in enumerate(cells)]
    headings = [(index, match) for index, match in headings if match is not None]
    candidates = []
    for position, (start, match) in enumerate(headings):
        stop = headings[position + 1][0] if position + 1 < len(headings) else len(cells)
        token = match.group(1)
        ambiguous = token.upper() == "I"
        source_cells = []
        for index in range(start, stop):
            cell = cells[index]
            box = cell.rect.to_bounding_box()
            source_cells.append({
                "index": index, "text": cell.text,
                "bbox": [box.l, box.t, box.r, box.b],
                "confidence": cell.confidence,
            })
        candidates.append({
            "page": page,
            "engine": engine,
            "heading_raw": cells[start].text,
            "number_raw": token,
            "number_candidate": 1 if ambiguous else int(token),
            "title_candidate": match.group(2),
            "review_flags": ["ambiguous_I_or_1"] if ambiguous else [],
            "status": "unreviewed_candidate",
            "boundary": "next_heading" if position + 1 < len(headings) else "page_end_unverified",
            "text": "\n".join(cell["text"] for cell in source_cells[1:]),
            "source_cells": source_cells,
        })
    return candidates

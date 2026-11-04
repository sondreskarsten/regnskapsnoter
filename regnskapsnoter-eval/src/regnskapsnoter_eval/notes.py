from __future__ import annotations

import re

_HEADING = re.compile(r"^\s*Note\s+([0-9]+|I)\s*[:.)-]?\s+(\S.*)$", re.IGNORECASE)


def note_candidates(cells, *, page, engine):
    cells = list(cells)
    headings = []
    for index, cell in enumerate(cells):
        match = _HEADING.match(cell.text)
        if match:
            headings.append((index, index + 1, match.group(1), match.group(2), False))
        elif cell.text.strip().lower() == "note" and index + 2 < len(cells):
            token = cells[index + 1].text.strip()
            title = cells[index + 2].text.strip()
            if re.fullmatch(r"[0-9]{1,3}|I", token, re.IGNORECASE) and title and title[0].isalpha():
                headings.append((index, index + 3, token, title, True))
    candidates = []
    for position, (start, body_start, token, title, split) in enumerate(headings):
        stop = headings[position + 1][0] if position + 1 < len(headings) else len(cells)
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
            "heading_raw": "\n".join(cell.text for cell in cells[start:body_start]),
            "number_raw": token,
            "number_candidate": 1 if ambiguous else int(token),
            "title_candidate": title,
            "review_flags": (["ambiguous_I_or_1"] if ambiguous else []) + (["split_heading_candidate"] if split else []),
            "status": "unreviewed_candidate",
            "boundary": "next_heading" if position + 1 < len(headings) else "page_end_unverified",
            "text": "\n".join(cell["text"] for cell in source_cells[body_start - start:]),
            "source_cells": source_cells,
        })
    return candidates

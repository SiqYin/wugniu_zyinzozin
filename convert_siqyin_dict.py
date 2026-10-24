#!/usr/bin/env python3
"""将 docx去掉开头说明的部分 转换为json。（全量更新）

Usage::
    python convert_siqyin_dict.py
    python convert_siqyin_dict.py INPUT OUTPUT
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


BASE_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIRECTORY / "data" / "siqyin_dict"
DEFAULT_OUTPUT = BASE_DIRECTORY / "data" / "siqyin_dict.json"

# These source lines do not contain the usual definition separator.
HEADER_DEFINITION_OVERRIDES = {
    "幾時ci3zyu2(1X)什麼時候": ("幾時ci3zyu2(1X)", "什麼時候"),
    "傍baon6;「傍」記音，表比較eg.傍傍看": (
        "傍baon6",
        "「傍」記音，表比較eg.傍傍看",
    ),
}

# This line contains a colon between the headword list and reading list, then
# another colon before the definition.  The final reading has no written
# headword in the source, so it is retained in readings without inventing one.
RECORD_OVERRIDES: dict[str, dict[str, Any]] = {
    "實梗/尚/箇場/gan6:zeq8kan3/zan6/geq8zan2/gan6:這樣，那樣": {
        "terms": ["實梗", "尚", "箇場"],
        "readings": ["zeq8kan3", "zan6", "geq8zan2", "gan6"],
        "definition": "這樣，那樣",
    },
    # The tone digits after 唔篤 belong to the following readings, not to the
    # written headwords.
    "爾屬/唔篤6/俉篤n6toq7:你們；你的（接人）": {
        "terms": ["爾屬", "唔篤", "俉篤"],
        "readings": ["n6toq7"],
        "definition": "你們；你的（接人）",
    },
    "爾儂/唔篤1/唔倷n1toq7/n1ne6:他們": {
        "terms": ["爾儂", "唔篤", "唔倷"],
        "readings": ["n1toq7", "n1ne6"],
        "definition": "他們",
    },
}

BRACKET_PATTERN = re.compile(
    r"（([^（）]*)）|\(([^()]*)\)|\[([^\[\]]*)\]|［([^［］]*)］"
)

TONE_CLASS_PATTERN = re.compile(r"[12356]X|[78]X[ABCD]", re.IGNORECASE)
EXPLICIT_CONTOUR_PATTERN = re.compile(r"\d+\s*[-–]\s*\d+")


def split_top_level_slashes(value: str) -> list[str]:
    """Split on slashes outside brackets and parentheses."""

    opening = {"（": "）", "(": ")", "[": "]", "［": "］"}
    closing = set(opening.values())
    stack: list[str] = []
    parts: list[str] = []
    start = 0

    for position, character in enumerate(value):
        if character in opening:
            stack.append(opening[character])
        elif character in closing:
            if stack and character == stack[-1]:
                stack.pop()
        elif character == "/" and not stack:
            parts.append(value[start:position])
            start = position + 1

    parts.append(value[start:])
    return parts


def find_reading_start(value: str) -> int | None:
    """Find the first lowercase Latin letter outside annotations."""

    opening = {"（": "）", "(": ")", "[": "]", "［": "］"}
    closing = set(opening.values())
    stack: list[str] = []

    for position, character in enumerate(value):
        if character in opening:
            stack.append(opening[character])
        elif character in closing:
            if stack and character == stack[-1]:
                stack.pop()
        elif not stack and "a" <= character <= "z":
            return position
    return None


def is_cjk_character(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x9FFF
        or 0x20000 <= codepoint <= 0x323AF
        or character in "〇々〆ヶ"
    )


def is_simple_variant_group(value: str) -> bool:
    """Return whether a bracket group contains only headword alternatives."""

    compact = value.strip()
    return bool(compact) and all(
        character == "/" or is_cjk_character(character)
        for character in compact
    )


def add_unique(values: list[str], value: str) -> None:
    candidate = value.strip()
    if candidate and candidate not in values:
        values.append(candidate)


def parse_terms(expression: str, line_number: int) -> list[str]:
    """Expand slash-separated and simple bracketed headword variants."""

    terms: list[str] = []
    for raw_part in split_top_level_slashes(expression.strip()):
        part = raw_part.strip()
        if not part:
            continue

        groups = list(BRACKET_PATTERN.finditer(part))
        base = BRACKET_PATTERN.sub("", part).strip()
        add_unique(terms, base)

        for group in groups:
            content = next(
                (item for item in group.groups() if item is not None), ""
            )
            if not is_simple_variant_group(content):
                continue

            # A suffix outside the brackets belongs to each alternative:
            # ``唉（哀）場`` therefore becomes ``唉場`` and ``哀場``.
            suffix = BRACKET_PATTERN.sub("", part[group.end() :]).strip()
            for alternative in content.split("/"):
                candidate = alternative.strip() + suffix
                if base.startswith("-") and not candidate.startswith("-"):
                    candidate = "-" + candidate
                add_unique(terms, candidate)

    if not terms:
        raise ValueError(f"line {line_number}: no headword was found")
    return terms


def parse_readings(expression: str) -> list[str]:
    """Return reading alternatives, excluding tone-sandhi annotations."""

    without_annotations = BRACKET_PATTERN.sub("", expression)
    readings: list[str] = []
    for part in without_annotations.split("/"):
        # Spaces in the source separate fields rather than syllables.
        reading = re.sub(r"\s+", "", part)
        add_unique(readings, reading)
    return readings


def bracket_content(group: re.Match[str]) -> str:
    return next((item for item in group.groups() if item is not None), "")


def is_tone_annotation(value: str) -> bool:
    compact = value.strip()
    return bool(
        TONE_CLASS_PATTERN.search(compact)
        or EXPLICIT_CONTOUR_PATTERN.search(compact)
        or "變調" in compact
        or "輕聲" in compact
        or compact == "輕"
        or re.fullmatch(r"\d+變", compact)
    )


def parse_tone(header: str) -> list[str]:
    """Extract tone-related source annotations without rewriting them."""

    annotations: list[str] = []

    for group in BRACKET_PATTERN.finditer(header):
        annotation = bracket_content(group).strip()
        if not is_tone_annotation(annotation):
            continue
        add_unique(annotations, annotation)
    return annotations


def split_header_and_definition(raw: str) -> tuple[str, str]:
    override = HEADER_DEFINITION_OVERRIDES.get(raw)
    if override is not None:
        return override

    positions = [
        position
        for delimiter in (":", "：")
        if (position := raw.find(delimiter)) >= 0
    ]
    if not positions:
        # Some colour-description entries intentionally have no definition.
        return raw, ""

    position = min(positions)
    return raw[:position], raw[position + 1 :]


def parse_record(raw: str, line_number: int) -> dict[str, Any]:
    override = RECORD_OVERRIDES.get(raw)
    if override is not None:
        header, _ = split_header_and_definition(raw)
        return {
            "terms": list(override["terms"]),
            "readings": list(override["readings"]),
            "tone": parse_tone(header),
            "definition": str(override["definition"]),
            "raw": raw,
        }

    header, definition = split_header_and_definition(raw)
    reading_start = find_reading_start(header)
    if reading_start is None:
        term_expression = header
        readings: list[str] = []
    else:
        term_expression = header[:reading_start]
        readings = parse_readings(header[reading_start:])

    return {
        "terms": parse_terms(term_expression, line_number),
        "readings": readings,
        "tone": parse_tone(header),
        "definition": definition.strip(),
        "raw": raw,
    }


def convert(source_text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for line_number, source_line in enumerate(source_text.splitlines(), start=1):
        raw = source_line.strip()
        if not raw:
            continue

        # Parenthesized standalone lines are notes belonging to the preceding
        # dictionary entry, not independent headwords.
        if raw.startswith(("(", "（")):
            if not records:
                raise ValueError(
                    f"line {line_number}: continuation has no preceding record"
                )
            record = records[-1]
            record["definition"] = (
                str(record["definition"]).rstrip() + "\n" + raw
            ).lstrip()
            record["raw"] = str(record["raw"]) + "\n" + raw
            continue

        record = parse_record(raw, line_number)
        record["id"] = len(records) + 1
        # Put id first to keep the generated file easy to inspect.
        output_record = {
            "id": record["id"],
            "terms": record["terms"],
            "readings": record["readings"],
            "tone": record["tone"],
            "definition": record["definition"],
            "raw": record["raw"],
        }
        records.append(output_record)

    return records


def write_json(output_path: Path, records: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(output_path.name + ".tmp")

    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(records, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert the Siqyin text dictionary to structured JSON."
    )
    parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = parse_arguments(arguments)
    try:
        source_text = options.input.read_text(encoding="utf-8")
        records = convert(source_text)
        write_json(options.output, records)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"convert_siqyin_dict: {error}", file=sys.stderr)
        return 1

    print(f"{options.input} -> {options.output} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

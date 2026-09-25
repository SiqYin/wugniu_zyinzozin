#!/usr/bin/env python3
"""
把数据从原html转到json用的

Extract JavaScript dictionaries embedded in HTML into JSON record arrays.

With no arguments, the script reads index1.html and writes to data/. An input
file and output directory may also be given explicitly:

    python get_data.py
    python get_data.py FILE OUT_DIR

Reading files contain records shaped as:

    {"id": 1, "character": "字", "meaning": [[...], ...]}

S2T.json contains records shaped as:

    {"id": 1, "s": "简", "t": ["繁", ...]}

T2S is intentionally ignored because the application only expands simplified
characters to traditional forms.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


OUTPUT_SOURCES = (
    ("DB_suhu", "DB_suhu.json"),
    ("DB_qingmo", "DB_qingmo.json"),
    ("DB_shanghai", "DB_shanghai.json"),
    ("DB_suzhou", "DB_suzhou.json"),
    ("DB_pingtan", "DB_pingtan.json"),
    ("S2T", "S2T.json"),
)


def extract_json_object(html: str, constant_name: str) -> str:
    """Return the object assigned to a top-level const NAME = {...}."""

    declaration = re.search(
        rf"\bconst\s+{re.escape(constant_name)}\s*=\s*", html
    )
    if declaration is None:
        raise ValueError(f"{constant_name} was not found in the input file")

    start = declaration.end()
    if start >= len(html) or html[start] != "{":
        raise ValueError(f"expected JSON object after {constant_name}")

    depth = 0
    in_string = False
    escaped = False

    for position in range(start, len(html)):
        character = html[position]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return html[start : position + 1]
            if depth < 0:
                break

    raise ValueError(f"unterminated JSON object for {constant_name}")


def load_constant(html: str, constant_name: str) -> dict[str, Any]:
    raw_object = extract_json_object(html, constant_name)
    try:
        value = json.loads(raw_object)
    except json.JSONDecodeError as error:
        raise ValueError(f"{constant_name} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{constant_name} must contain a JSON object")
    return value


def make_records(
    data: dict[str, Any], constant_name: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for record_id, (character, value) in enumerate(data.items(), start=1):
        if not isinstance(value, list):
            raise ValueError(f"{constant_name}[{character!r}] must be an array")

        if constant_name == "S2T":
            if not all(isinstance(target, str) for target in value):
                raise ValueError(
                    f"S2T[{character!r}] contains a non-string target"
                )
            record = {"id": record_id, "s": character, "t": value}
        else:
            if not all(isinstance(meaning, list) for meaning in value):
                raise ValueError(
                    f"{constant_name}[{character!r}] contains an invalid meaning"
                )
            record = {
                "id": record_id,
                "character": character,
                "meaning": value,
            }

        records.append(record)

    return records


def remove_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def write_json(output_path: Path, records: list[dict[str, Any]]) -> None:
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    remove_if_present(temporary_path)

    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(records, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, output_path)
    except Exception:
        remove_if_present(temporary_path)
        raise


def parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract embedded JavaScript dictionaries to JSON records."
    )
    parser.add_argument("input", nargs="?", default="index1.html")
    parser.add_argument("output_directory", nargs="?", default="data")
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    options = parse_arguments(arguments)
    input_path = Path(options.input)
    output_directory = Path(options.output_directory)

    try:
        html = input_path.read_text(encoding="utf-8")
        output_directory.mkdir(exist_ok=True)
        if not output_directory.is_dir():
            raise NotADirectoryError(f"{output_directory} is not a directory")
    except (OSError, UnicodeError) as error:
        print(f"get_data: {error}", file=sys.stderr)
        return 1

    failed = False
    for constant_name, file_name in OUTPUT_SOURCES:
        try:
            data = load_constant(html, constant_name)
            records = make_records(data, constant_name)
            output_path = output_directory / file_name
            write_json(output_path, records)
            print(
                f"{constant_name:<12} -> "
                f"{output_path} ({len(records)} character records)"
            )
        except (OSError, ValueError) as error:
            print(f"get_data: {error}", file=sys.stderr)
            failed = True

    if failed:
        print(
            "get_data: one or more JSON files could not be generated",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

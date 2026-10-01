"""JSON-backed search logic for the Wu pronunciation site."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


DIALECTS = {
    "suhu": {
        "file": "DB_suhu.json",
        "name": "蘇滬混合腔",
        "romanization": True,
    },
    "qingmo": {
        "file": "DB_qingmo.json",
        "name": "清末蘇州話",
        "romanization": False,
    },
    "shanghai": {
        "file": "DB_shanghai.json",
        "name": "上海話",
        "romanization": False,
    },
    "suzhou": {
        "file": "DB_suzhou.json",
        "name": "蘇州話",
        "romanization": False,
    },
    "pingtan": {
        "file": "DB_pingtan.json",
        "name": "蘇州評彈音",
        "romanization": False,
    },
}

OU_TO_U_MAP = {
    "pou": "pu",
    "phou": "phu",
    "mou": "mu",
    "fou": "fu",
    "vou": "vu",
    "tou": "tu",
    "thou": "thu",
    "nou": "nu",
    "lou": "lu",
    "kou": "ku",
    "khou": "khu",
    "hou": "hu",
    "ghou": "wu",
    "ngou": "ngu",
    "tsou": "tsu",
    "tshou": "tshu",
    "sou": "su",
    "zou": "zu",
}

_TONE_AT_END = re.compile(r"[1-9]$")


class SearchService:
    """Read-only search service over the JSON pronunciation records."""

    def __init__(self, data_directory: str | Path) -> None:
        self.data_directory = Path(data_directory).resolve()
        self.variant_file = self.data_directory / "S2T.json"
        self.reading_files = {
            code: self.data_directory / str(details["file"])
            for code, details in DIALECTS.items()
        }
        self._check_files()

        variant_records = self._load_json_records(self.variant_file)
        self.variants = self._index_variants(
            variant_records, self.variant_file
        )
        self.reading_data = {
            code: self._index_readings(
                self._load_json_records(path), path
            )
            for code, path in self.reading_files.items()
        }

    def _check_files(self) -> None:
        required = [self.variant_file, *self.reading_files.values()]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "Missing JSON data file(s): " + ", ".join(missing)
            )

    @staticmethod
    def _load_json_records(path: Path) -> list[dict[str, Any]]:
        try:
            with path.open(encoding="utf-8") as source:
                data = json.load(source)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON in {path}: {error}") from error
        if not isinstance(data, list):
            raise ValueError(f"JSON root in {path} must be an array")

        records: list[dict[str, Any]] = []
        for position, record in enumerate(data, start=1):
            if not isinstance(record, dict):
                raise ValueError(
                    f"Record {position} in {path} must be an object"
                )
            records.append(record)
        return records

    @staticmethod
    def _check_record_id(
        record: dict[str, Any],
        path: Path,
        position: int,
        seen_ids: set[int],
    ) -> None:
        record_id = record.get("id")
        if isinstance(record_id, bool) or not isinstance(record_id, int):
            raise ValueError(
                f"Record {position} in {path} has an invalid id"
            )
        if record_id in seen_ids:
            raise ValueError(f"Duplicate id {record_id} in {path}")
        seen_ids.add(record_id)

    @classmethod
    def _index_readings(
        cls, records: list[dict[str, Any]], path: Path
    ) -> dict[str, list[Any]]:
        index: dict[str, list[Any]] = {}
        seen_ids: set[int] = set()

        for position, record in enumerate(records, start=1):
            cls._check_record_id(record, path, position, seen_ids)
            character = record.get("character")
            meanings = record.get("meaning")
            if not isinstance(character, str) or not character:
                raise ValueError(
                    f"Record {position} in {path} has an invalid character"
                )
            if not isinstance(meanings, list):
                raise ValueError(
                    f"Record {position} in {path} has an invalid meaning"
                )
            if character in index:
                raise ValueError(
                    f"Duplicate character {character!r} in {path}"
                )
            index[character] = meanings

        return index

    @classmethod
    def _index_variants(
        cls, records: list[dict[str, Any]], path: Path
    ) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        seen_ids: set[int] = set()

        for position, record in enumerate(records, start=1):
            cls._check_record_id(record, path, position, seen_ids)
            source = record.get("s")
            targets = record.get("t")
            if not isinstance(source, str) or not source:
                raise ValueError(
                    f"Record {position} in {path} has an invalid s value"
                )
            if not isinstance(targets, list) or not all(
                isinstance(target, str) for target in targets
            ):
                raise ValueError(
                    f"Record {position} in {path} has an invalid t value"
                )
            if source in index:
                raise ValueError(f"Duplicate s value {source!r} in {path}")
            index[source] = targets

        return index

    def _traditional_targets(self, source_character: str) -> list[str]:
        return self.variants.get(source_character, [])

    def _expand_characters(self, text: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        emitted: set[str] = set()

        for source in text:
            if source in seen:
                continue
            seen.add(source)
            targets = self._traditional_targets(source)

            if not targets:
                if source not in emitted:
                    results.append({"character": source, "source": "direct"})
                    emitted.add(source)
                continue

            for target in targets:
                if target == source:
                    if target not in emitted:
                        results.append({"character": target, "source": "direct"})
                        emitted.add(target)
                    continue
                if target in seen or target in emitted:
                    continue
                seen.add(target)
                emitted.add(target)
                results.append(
                    {
                        "character": target,
                        "source": "converted",
                        "from": source,
                    }
                )

        return results

    @staticmethod
    def _merge_readings(
        entries: Iterable[Any], has_romanization: bool
    ) -> list[dict[str, object]]:
        """Deduplicate readings within one character and one dialect."""

        groups: dict[tuple[str, ...], dict[str, object]] = {}
        expected_length = 3 if has_romanization else 2

        for entry in entries:
            if not isinstance(entry, list) or len(entry) < expected_length:
                raise ValueError("Reading data contains an invalid meaning")

            if has_romanization:
                romanization, ipa, note = entry[:3]
            else:
                romanization = None
                ipa, note = entry[:2]

            key = (
                (str(romanization or ""), str(ipa or ""))
                if has_romanization
                else (str(ipa or ""),)
            )
            group = groups.get(key)
            if group is None:
                group = {
                    "romanization": romanization,
                    "ipa": ipa,
                    "notes": [],
                }
                groups[key] = group

            if note:
                notes = group["notes"]
                if isinstance(notes, list) and str(note) not in notes:
                    notes.append(str(note))

        merged: list[dict[str, object]] = []
        for group in groups.values():
            notes = group["notes"]
            merged.append(
                {
                    "romanization": group["romanization"],
                    "ipa": group["ipa"],
                    "note": "；".join(notes) if isinstance(notes, list) else "",
                    "audio": [],
                }
            )
        return merged

    def _readings_for_character(
        self, character: str, dialect_code: str
    ) -> list[dict[str, object]]:
        entries = self.reading_data[dialect_code].get(character, [])
        return self._merge_readings(
            entries, bool(DIALECTS[dialect_code]["romanization"])
        )

    @staticmethod
    def _selected_dialects(requested: Iterable[str] | None) -> list[str]:
        if requested is None:
            return list(DIALECTS)
        requested_set = {str(code) for code in requested}
        return [code for code in DIALECTS if code in requested_set]

    def search_characters(
        self, raw_text: str, requested_dialects: Iterable[str] | None = None
    ) -> dict[str, object]:
        text = raw_text.strip()
        if not text:
            raise ValueError("Please enter at least one character.")
        if len(text) > 8:
            raise ValueError("Maximum 8 characters at a time.")

        selected = self._selected_dialects(requested_dialects)
        characters = self._expand_characters(text)
        for item in characters:
            character = item["character"]
            item["readings"] = {
                code: self._readings_for_character(character, code)
                for code in selected
            }

        return {"characters": characters, "dialects": selected}

    @staticmethod
    def normalize_pinyin(raw_pinyin: str) -> tuple[str, str, bool]:
        normalized = raw_pinyin.strip().lower()
        if not normalized:
            raise ValueError("Please enter a romanization.")

        has_tone = bool(_TONE_AT_END.search(normalized))
        tone = normalized[-1] if has_tone else ""
        base = normalized[:-1] if has_tone else normalized
        base = OU_TO_U_MAP.get(base, base)
        full = base + tone if has_tone else base
        return full, base, has_tone

    def reverse_lookup(self, raw_pinyin: str) -> dict[str, object]:
        normalized, base, has_tone = self.normalize_pinyin(raw_pinyin)
        matches: list[tuple[str, str, Any]] = []

        for character, entries in self.reading_data["suhu"].items():
            for entry in entries:
                if not isinstance(entry, list) or len(entry) < 2:
                    raise ValueError(
                        "DB_suhu.json contains an invalid meaning"
                    )
                reading = str(entry[0])
                ipa = entry[1]
                reading_lower = reading.lower()
                reading_base = _TONE_AT_END.sub("", reading_lower)

                if (
                    (has_tone and reading_lower == normalized)
                    or (not has_tone and reading_base == base)
                ):
                    matches.append((character, reading, ipa))

        matches.sort(key=lambda item: item[1].lower())

        grouped: dict[str, dict[str, object]] = {}
        for character, reading, ipa in matches:
            group = grouped.get(reading)
            if group is None:
                group = {
                    "reading": reading,
                    "ipa": ipa,
                    "characters": [],
                }
                grouped[reading] = group
            characters = group["characters"]
            if isinstance(characters, list) and character not in characters:
                characters.append(character)

        return {"query": normalized, "groups": list(grouped.values())}

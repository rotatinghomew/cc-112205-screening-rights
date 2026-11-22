"""来源资料加载器。

按资料方原格式读取（CSV、JSON Lines、只读 SQLite），原始标识保持文本。
加载器只做格式解析，不做跨表推断。
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import (
    AssetRef,
    CinemaCombo,
    CompositionRow,
    Grant,
    Handoff,
    MediaItem,
    Show,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _read_sqlite(path: Path, table: str) -> list[dict[str, str]]:
    # 来源库只读，原始标识保持文本类型。
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        return [dict(row) for row in source.execute(f'SELECT * FROM "{table}"')]


def _when(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


def load_catalog(path: Path) -> dict[AssetRef, MediaItem]:
    catalog: dict[AssetRef, MediaItem] = {}
    for row in _read_csv(path):
        ref = AssetRef(asset=row["asset"], edition=row["edition"])
        catalog[ref] = MediaItem(
            ref=ref,
            kind=row["kind"],
            format=row["format"],
            seconds=int(row["seconds"]),
        )
    return catalog


def load_composition(path: Path) -> list[CompositionRow]:
    rows: list[CompositionRow] = []
    for row in _read_csv(path):
        rows.append(
            CompositionRow(
                parent=AssetRef(row["parent"], row["parent_edition"]),
                child=AssetRef(row["child"], row["child_edition"]),
                part=row["part"],
                parent_in=int(row["parent_in"]),
                child_in=int(row["child_in"]),
                length=int(row["length"]),
            )
        )
    return rows


def load_grants(path: Path) -> list[Grant]:
    grants: list[Grant] = []
    for row in _read_jsonl(path):
        grants.append(
            Grant(
                grant=row["grant"],
                revision=row["revision"],
                city=row["city"],
                ref=AssetRef(asset=row["asset"], edition=row["edition"]),
                from_sec=int(row["from_sec"]),
                to_sec=int(row["to_sec"]),
                opens=_when(row["opens"]),
                closes=_when(row["closes"]),
                media=row["media"],
                state=row["state"],
                received=int(row["received"]),
            )
        )
    return grants


def load_cinemas(path: Path) -> list[CinemaCombo]:
    return [
        CinemaCombo(cinema=row["cinema"], city=row["city"], format=row["format"])
        for row in _read_csv(path)
    ]


def load_schedule(path: Path) -> list[Show]:
    shows: list[Show] = []
    for row in _read_sqlite(path, path.stem):
        fallbacks = tuple(
            AssetRef.parse(token)
            for token in row["fallbacks"].split(",")
            if token.strip()
        )
        shows.append(
            Show(
                show=row["show"],
                cinema=row["cinema"],
                start=_when(row["start"]),
                end=_when(row["end"]),
                main=AssetRef(row["asset"], row["edition"]),
                fallbacks=fallbacks,
            )
        )
    return shows


def load_handoffs(path: Path) -> list[Handoff]:
    return [
        Handoff(
            show=row["show"],
            package=row["package"],
            revision=row["revision"],
            status=row["status"],
            received=int(row["received"]),
        )
        for row in _read_jsonl(path)
    ]

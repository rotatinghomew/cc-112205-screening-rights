import csv
import json
from pathlib import Path
import sqlite3
import unittest


DATA = Path(__file__).resolve().parents[1] / "data"


def load(name):
    """读取资料方原格式，保留原始字段。"""
    path = DATA / name
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as source:
            return list(csv.DictReader(source))
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if path.suffix == ".db":
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
            source.row_factory = sqlite3.Row
            return [dict(row) for row in source.execute(f'SELECT * FROM "{path.stem}"')]
    if path.suffix == ".parquet":
        import duckdb

        with duckdb.connect() as source:
            result = source.execute("SELECT * FROM read_parquet(?)", [str(path)])
            names = [column[0] for column in result.description]
            return [dict(zip(names, row)) for row in result.fetchall()]
    raise ValueError(f"未知的资料格式 {path.suffix}")


class SourceContractTests(unittest.TestCase):
    def test_source_examples_are_present(self):
        checks = [('catalog.csv', 'asset', 'F-44', 3), ('grants.jsonl', 'state', 'withdraw', 1), ('handoffs.jsonl', 'show', 'EV2', 3), ('schedule.db', 'cinema', 'C01', 2)]
        for name, field, value, count in checks:
            with self.subTest(source=name, field=field):
                self.assertEqual(sum(row[field] == value for row in load(name)), count)

    def test_schedule_and_composition_reference_published_media(self):
        catalog = {(row["asset"], row["edition"]): int(row["seconds"]) for row in load("catalog.csv")}
        for part in load("composition.csv"):
            self.assertLessEqual(int(part["child_in"]) + int(part["length"]), catalog[part["child"], part["child_edition"]])
            self.assertLessEqual(int(part["parent_in"]) + int(part["length"]), catalog[part["parent"], part["parent_edition"]])
        shows = {row["show"]: row for row in load("schedule.db")}
        for receipt in load("handoffs.jsonl"):
            self.assertIn(receipt["show"], shows)
        revised = [row for row in load("grants.jsonl") if row["grant"] == "G3"]
        self.assertEqual({row["asset"] for row in revised}, {"A-410"})
        self.assertEqual({row["state"] for row in revised}, {"allow", "withdraw"})

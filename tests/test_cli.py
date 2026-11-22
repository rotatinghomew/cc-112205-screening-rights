"""命令行入口测试。"""

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from mediaware.cli import main

DATA = Path(__file__).resolve().parents[1] / "data"


def run(*argv: str):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main([*argv, "--data", str(DATA)])
    return code, json.loads(buffer.getvalue())


class CliTests(unittest.TestCase):
    def test_shows_and_query_filters(self):
        code, payload = run("shows")
        self.assertEqual(code, 0)
        self.assertEqual({row["show"] for row in payload},
                         {"EV1", "EV2", "EV3", "EV4"})

        _, payload = run("query", "--city", "临泉")
        self.assertEqual({row["show"] for row in payload}, {"EV1", "EV2"})

        _, payload = run("query", "--date", "2027-03-14")
        self.assertEqual({row["show"] for row in payload}, {"EV2", "EV3", "EV4"})

    def test_grants_exclude_withdrawn_contract(self):
        _, payload = run("grants")
        self.assertNotIn("G3", {row["grant"] for row in payload})
        self.assertIn("G7", {row["grant"] for row in payload})

    def test_as_of_snapshot_is_reproducible(self):
        _, current = run("shows")
        ev2_now = next(row for row in current if row["show"] == "EV2")
        self.assertEqual(ev2_now["action"], "suspend")

        _, snapshot = run("shows", "--as-of", "4")
        ev2_then = next(row for row in snapshot if row["show"] == "EV2")
        self.assertEqual(ev2_then["action"], "play")
        self.assertEqual(ev2_then["as_of_batch"], 4)

    def test_manifest_and_trace_are_linked(self):
        _, manifest = run("manifest", "EV2")
        self.assertEqual(manifest["confirmed"]["bound_ref"], "F-44@1")
        self.assertEqual(manifest["notices"][0]["revision"], "1")

        _, trace = run("trace", "EV1")
        self.assertTrue(trace["played"])
        self.assertEqual(trace["frozen_package"], "PK-A")


if __name__ == "__main__":
    unittest.main()

"""版权方部分撤销与合同独立性测试。"""

import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from mediaware.models import (
    STATE_WITHDRAW,
    AssetRef,
)
from mediaware.rights import USAGE_OK, evaluate_usage, resolve_grants
from mediaware.warehouse import MediaWarehouse
from mediaware.models import LeafUsage

DATA = Path(__file__).resolve().parents[1] / "data"
T0 = datetime.fromisoformat("2027-03-14T18:00:00+08:00")
T1 = datetime.fromisoformat("2027-03-14T19:00:00+08:00")


class PartialWithdrawalTests(unittest.TestCase):
    def test_withdrawing_one_right_leaves_other_evidence_intact(self):
        wh = MediaWarehouse.from_directory(DATA)
        # G3 只覆盖 A-410 一项；其撤销不应影响 V-202（G1）与 S-31（G2）。
        report = wh.report("EV4")
        by_leaf = {}
        for candidate in report.candidates:
            for verdict in candidate.usage_verdicts:
                by_leaf[(candidate.ref.key(), verdict.usage.leaf.asset)] = verdict
        self.assertEqual(
            by_leaf[("F-44@3", "V-202")].status, USAGE_OK
        )
        self.assertEqual(
            by_leaf[("F-44@3", "S-31")].status, USAGE_OK
        )
        # 其他合同号独立判断，仍然作为证据在场。
        evidence = {
            grant.grant
            for candidate in report.candidates
            for grant in candidate.evidence
        }
        self.assertIn("G1", evidence)
        self.assertIn("G2", evidence)
        self.assertNotIn("G3", evidence)

    def test_withdrawn_revision_remains_visible_at_earlier_batch(self):
        wh = MediaWarehouse.from_directory(DATA)
        # 批次 4：G3 修订 1 仍生效，支撑当时已确认的场次。
        earlier = resolve_grants(wh.grants, 4)
        g3 = next(grant for grant in earlier if grant.grant == "G3")
        self.assertEqual(g3.revision, "1")
        usage = LeafUsage(
            leaf=AssetRef("A-410", "1"), part="audio", leaf_in=0, length=80,
            root_in=0, chain=(AssetRef("A-410", "1"),),
        )
        verdict = evaluate_usage(usage, "临泉", T0, T1, earlier)
        self.assertEqual(verdict.status, USAGE_OK)
        # 批次 5 及以后：同一合同号退出，结论变为缺证而非禁用。
        later = resolve_grants(wh.grants, 5)
        self.assertNotIn("G3", {grant.grant for grant in later})
        verdict_after = evaluate_usage(usage, "临泉", T0, T1, later)
        self.assertEqual(verdict_after.status, "missing")
        self.assertEqual(verdict_after.denials, ())

    def test_other_contract_revision_is_independent(self):
        # 同一仓里 G4 与 G7 针对同一素材，一准许一禁止；撤销 G4 不影响 G7 的禁止。
        wh = MediaWarehouse.from_directory(DATA)
        g4 = next(grant for grant in wh.grants if grant.grant == "G4")
        withdrawn = replace(
            g4, revision="2", state=STATE_WITHDRAW, received=8
        )
        grants = [*wh.grants, withdrawn]
        effective = resolve_grants(grants, 8)
        ids = {grant.grant for grant in effective}
        self.assertNotIn("G4", ids)
        self.assertIn("G7", ids)


if __name__ == "__main__":
    unittest.main()

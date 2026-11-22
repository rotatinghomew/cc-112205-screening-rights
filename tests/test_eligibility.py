"""包级可用性测试：权利齐备与影院公布组合双重门槛。"""

import unittest
from pathlib import Path

from mediaware.eligibility import (
    PACKAGE_DENIED,
    PACKAGE_ELIGIBLE,
    PACKAGE_INCOMPATIBLE,
    PACKAGE_MISSING,
    evaluate_show,
)
from mediaware.models import AssetRef
from mediaware.sources import (
    load_catalog,
    load_cinemas,
    load_composition,
    load_grants,
    load_schedule,
)
from mediaware.rights import resolve_grants

DATA = Path(__file__).resolve().parents[1] / "data"


class EligibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(DATA / "catalog.csv")
        cls.rows = load_composition(DATA / "composition.csv")
        cls.grants = load_grants(DATA / "grants.jsonl")
        cls.cinemas = load_cinemas(DATA / "cinemas.csv")
        cls.shows = {row.show: row for row in load_schedule(DATA / "schedule.db")}

    def _verdicts(self, show_id):
        show = self.shows[show_id]
        return {
            item.ref.key(): item
            for item in evaluate_show(
                show, self.grants, self.catalog, self.rows, self.cinemas
            )
        }

    def test_ev4_surround_package_is_eligible_in_surround_cinema(self):
        verdicts = self._verdicts("EV4")
        self.assertEqual(verdicts["F-44@3"].status, PACKAGE_ELIGIBLE)
        self.assertTrue(verdicts["F-44@3"].compatible)
        # 证据覆盖整条使用段：A-117 只用 10..90，恰为 G5 范围。
        evidence = {grant.grant for grant in verdicts["F-44@3"].evidence}
        self.assertEqual(evidence, {"G1", "G2", "G5"})

    def test_cinema_only_accepts_published_track_caption_combos(self):
        # C02 只公布 stereo+srt-zh；F-44@3 是 surround+srt-zh，权利齐备也不能排。
        verdicts = self._verdicts("EV3")
        fallback = verdicts["F-44@3"]
        self.assertEqual(fallback.status, PACKAGE_INCOMPATIBLE)
        self.assertFalse(fallback.compatible)
        self.assertEqual(fallback.cinema_formats, ("stereo+srt-zh",))
        # 主版本的 A-410 声轨因 G3 撤销而缺证。
        main = verdicts["F-44@1"]
        self.assertEqual(main.status, PACKAGE_MISSING)
        missing = [v for v in main.usage_verdicts if v.status == "missing"]
        self.assertEqual([v.usage.leaf.asset for v in missing], ["A-410"])

    def test_deny_marks_package_denied_with_reason(self):
        # EV2 的备选 F-44@2：G4 准许整段，但 G7 明确禁止 A-681 的 20..40。
        verdicts = self._verdicts("EV2")
        fallback = verdicts["F-44@2"]
        self.assertEqual(fallback.status, PACKAGE_DENIED)
        denied = [v for v in fallback.usage_verdicts if v.status == "denied"]
        self.assertEqual(denied[0].usage.leaf.asset, "A-681")
        self.assertTrue(any("G7" in reason for reason in denied[0].reasons))

    def test_withdrawn_grant_is_not_evidence(self):
        effective = resolve_grants(self.grants, 7)
        g3 = [grant for grant in effective if grant.grant == "G3"]
        self.assertEqual(g3, [])

    def test_candidate_order_follows_schedule_recommendation(self):
        verdicts = self._verdicts("EV2")
        self.assertEqual(list(verdicts), ["F-44@1", "F-44@2"])
        self.assertIsInstance(self.shows["EV2"].fallbacks, tuple)
        self.assertEqual(self.shows["EV2"].fallbacks, (AssetRef("F-44", "2"),))


if __name__ == "__main__":
    unittest.main()

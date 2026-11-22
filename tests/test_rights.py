"""权利判定测试：修订/撤销、城市与片段范围、空档、明确禁止优先。"""

import unittest
from datetime import datetime

from mediaware.models import (
    STATE_ALLOW,
    STATE_DENY,
    STATE_WITHDRAW,
    AssetRef,
    Grant,
    LeafUsage,
    USAGE_DENIED,
    USAGE_MISSING,
    USAGE_OK,
)
from mediaware.rights import evaluate_usage, resolve_grants

T0 = datetime.fromisoformat("2027-03-14T18:00:00+08:00")
T1 = datetime.fromisoformat("2027-03-14T19:00:00+08:00")
REF = AssetRef("A-X", "1")


def usage(start=0, length=80, part="audio"):
    return LeafUsage(
        leaf=REF, part=part, leaf_in=start, length=length,
        root_in=0, chain=(REF,),
    )


def grant(state=STATE_ALLOW, city="*", seg=(0, 80), window=(T0, T1),
          gid="G1", rev="1", received=1):
    return Grant(
        grant=gid, revision=rev, city=city, ref=REF,
        from_sec=seg[0], to_sec=seg[1], opens=window[0], closes=window[1],
        media="screen", state=state, received=received,
    )


class ResolutionTests(unittest.TestCase):
    def test_higher_revision_replaces_lower_within_same_contract(self):
        rows = [grant(rev="1", received=1), grant(rev="2", received=3)]
        effective = resolve_grants(rows, 3)
        self.assertEqual([(g.grant, g.revision) for g in effective], [("G1", "2")])

    def test_withdraw_makes_contract_exit_but_others_remain(self):
        rows = [
            grant(gid="G1", rev="1", received=1),
            grant(gid="G1", rev="2", state=STATE_WITHDRAW, received=5),
            grant(gid="G2", received=2),
        ]
        effective = resolve_grants(rows, 7)
        self.assertEqual({g.grant for g in effective}, {"G2"})

    def test_future_batch_is_not_visible(self):
        rows = [grant(rev="1", received=1), grant(rev="2", received=5)]
        self.assertEqual(
            [g.revision for g in resolve_grants(rows, 1)], ["1"]
        )


class CoverageTests(unittest.TestCase):
    def test_full_allow_is_ok(self):
        verdict = evaluate_usage(usage(), "临泉", T0, T1, [grant()])
        self.assertEqual(verdict.status, USAGE_OK)
        self.assertEqual(verdict.gaps, ())

    def test_no_contract_is_missing_not_denied(self):
        verdict = evaluate_usage(usage(), "临泉", T0, T1, [])
        self.assertEqual(verdict.status, USAGE_MISSING)
        self.assertEqual(verdict.gaps, ((0, 80),))
        self.assertEqual(verdict.denials, ())

    def test_city_scoped_grant_does_not_cover_other_city(self):
        verdict = evaluate_usage(usage(), "云桥", T0, T1, [grant(city="临泉")])
        self.assertEqual(verdict.status, USAGE_MISSING)

    def test_wildcard_city_covers_listed_city(self):
        verdict = evaluate_usage(usage(), "临泉", T0, T1, [grant(city="*")])
        self.assertEqual(verdict.status, USAGE_OK)

    def test_segment_grant_only_covers_actual_subsegment(self):
        # 授权只给 10..90：使用 0..80 时 0..10 是缺证。
        verdict = evaluate_usage(usage(0, 80), "临泉", T0, T1,
                                 [grant(seg=(10, 90))])
        self.assertEqual(verdict.status, USAGE_MISSING)
        self.assertEqual(verdict.gaps, ((0, 10),))

    def test_contract_gap_cannot_be_smoothed_by_first_and_last_dates(self):
        # 两份准许在时间上留了 20 分钟空档，不能用首尾日期抹平。
        gap_grants = [
            grant(window=(T0, datetime.fromisoformat("2027-03-14T18:20:00+08:00"))),
            grant(gid="G2",
                  window=(datetime.fromisoformat("2027-03-14T18:40:00+08:00"), T1)),
        ]
        verdict = evaluate_usage(usage(), "临泉", T0, T1, gap_grants)
        self.assertEqual(verdict.status, USAGE_MISSING)

    def test_adjacent_contracts_cover_without_gap(self):
        adjacent = [
            grant(window=(T0, datetime.fromisoformat("2027-03-14T18:30:00+08:00"))),
            grant(gid="G2",
                  window=(datetime.fromisoformat("2027-03-14T18:30:00+08:00"), T1)),
        ]
        verdict = evaluate_usage(usage(), "临泉", T0, T1, adjacent)
        self.assertEqual(verdict.status, USAGE_OK)

    def test_deny_overrides_allow_and_carries_reason(self):
        rows = [
            grant(gid="G1"),
            grant(gid="G7", state=STATE_DENY,
                  seg=(20, 40),
                  window=(datetime.fromisoformat("2027-03-14T18:00:20+08:00"),
                          datetime.fromisoformat("2027-03-14T18:00:40+08:00")),
                  received=6),
        ]
        verdict = evaluate_usage(usage(), "临泉", T0, T1, rows)
        self.assertEqual(verdict.status, USAGE_DENIED)
        self.assertTrue(verdict.reasons)
        self.assertIn("G7", verdict.reasons[0])

    def test_non_screen_media_grant_does_not_count(self):
        row = grant()
        object.__setattr__(row, "media", "broadcast")
        verdict = evaluate_usage(usage(), "临泉", T0, T1, [row])
        self.assertEqual(verdict.status, USAGE_MISSING)


if __name__ == "__main__":
    unittest.main()

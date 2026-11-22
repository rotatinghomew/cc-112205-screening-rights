"""场次状态机、交接回执与双时点审计测试。"""

import unittest
from pathlib import Path

from mediaware.models import (
    ACTION_HISTORY,
    ACTION_PLAY,
    ACTION_RECONFIRM,
    ACTION_SUSPEND,
)
from mediaware.warehouse import MediaWarehouse

DATA = Path(__file__).resolve().parents[1] / "data"


class WarehouseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wh = MediaWarehouse.from_directory(DATA)

    def test_played_show_is_frozen_history_and_keeps_later_trace(self):
        report = self.wh.report("EV1")
        self.assertEqual(report.action, ACTION_HISTORY)
        self.assertEqual(report.confirmed_ref.key(), "W-07@1")
        self.assertIsNotNone(report.played_receipt)
        self.assertEqual(report.played_receipt.package, "PK-A")
        traces = [n for n in report.notices if n.kind == "trace"]
        self.assertEqual(len(traces), 1)
        self.assertIn("G3", traces[0].message)
        # 冻结快照在放映批次时仍是合格的，追查不改变原义。
        snapshot = self.wh.report("EV1", as_of=4)
        self.assertEqual(snapshot.candidates[0].status, "eligible")
        self.assertEqual(snapshot.notices, ())

    def test_evidence_trace_only_flags_contracts_inside_played_package(self):
        trace = self.wh.evidence_trace("EV1")
        self.assertTrue(trace["played"])
        details = trace["traces"][0]["details"]
        self.assertEqual(details["grant_changes"],
                         ["合同 G3 已撤销退出生效（原修订 1）"])
        # G7 针对 A-681，不在 W-07 构成中，不进本场追查。
        self.assertNotIn("G7", details["grant_changes"])
        self.assertEqual(details["usage_changes"][0]["leaf"], "A-410@1")
        self.assertEqual(details["usage_changes"][0]["before"], "ok")
        self.assertEqual(details["usage_changes"][0]["after"], "missing")

    def test_ev2_must_suspend_and_late_confirmation_does_not_clear_it(self):
        report = self.wh.report("EV2")
        self.assertEqual(report.action, ACTION_SUSPEND)
        # 批次 7 的迟到确认仍是已接受状态，但不解除暂停。
        self.assertEqual(report.latest_acceptance.status, "confirmed")
        self.assertEqual(report.confirmed_ref.key(), "F-44@1")
        suspend_notices = [n for n in report.notices if n.kind == "suspend"]
        self.assertEqual(len(suspend_notices), 1)
        self.assertEqual(suspend_notices[0].package, "PK-B")
        # 两个候选都不能用：主包缺证、备包被明确禁止。
        self.assertEqual(
            [c.status for c in report.candidates], ["missing", "denied"]
        )

    def test_ev3_suspends_for_compatibility_not_rights(self):
        report = self.wh.report("EV3")
        self.assertEqual(report.action, ACTION_SUSPEND)
        self.assertEqual(report.candidates[1].status, "incompatible")
        self.assertIn("不在影院公布组合", report.action_reason)

    def test_unconfirmed_show_with_eligible_package_can_play(self):
        report = self.wh.report("EV4")
        self.assertEqual(report.action, ACTION_PLAY)
        self.assertIsNone(report.confirmed_ref)
        self.assertTrue(report.candidates[0].eligible)

    def test_before_withdrawal_confirmed_packages_were_still_playable(self):
        # 批次 4：G3 仍生效、G7 未到达，EV2/EV3 已确认主包均可照常播放。
        for show_id in ("EV2", "EV3"):
            report = self.wh.report(show_id, as_of=4)
            self.assertEqual(report.action, ACTION_PLAY, show_id)
        # 批次 5：G3 撤销到达，主包立刻缺证；EV2 的备选 F-44@2 此时仍合格
        # （G7 批次 6 才到），进入“需影院重新确认备包”，不做静默替换。
        report = self.wh.report("EV2", as_of=5)
        self.assertEqual(report.action, ACTION_RECONFIRM)
        self.assertEqual(report.confirmed_ref.key(), "F-44@1")
        notice = next(n for n in report.notices if n.kind == "reconfirm")
        self.assertEqual(notice.details["reconfirm_ref"], "F-44@2")
        # 批次 6：G7 明确禁止到达，备选也失效，才转为暂停。
        self.assertEqual(self.wh.report("EV2", as_of=6).action, ACTION_SUSPEND)

    def test_reconfirm_path_requires_cinema_acceptance_and_never_silent_swap(self):
        # 构造一个临时仓：给 EV2 影院补一份兼容且权利齐备的第二备选，
        # 已确认主包失效时应进入 reconfirm，而不是直接换包播放。
        from mediaware.models import AssetRef, Show
        show = self.wh.schedule[1]
        upgraded = Show(
            show=show.show, cinema=show.cinema, start=show.start, end=show.end,
            main=show.main,
            fallbacks=(AssetRef("F-44", "2"), AssetRef("F-44", "3")),
        )
        # 让 F-44@3 在临泉也被公布为兼容组合，并补上市级声轨授权
        # （原 G5 只覆盖云桥），使第二备选权利齐备且兼容。
        from dataclasses import replace
        from mediaware.models import CinemaCombo
        combos = self.wh.cinemas + [CinemaCombo("C01", "临泉", "surround+srt-zh")]
        g5 = next(grant for grant in self.wh.grants if grant.grant == "G5")
        grants = self.wh.grants + [replace(g5, grant="G8", city="*")]
        wh = MediaWarehouse(
            self.wh.catalog, self.wh.composition_rows, grants,
            combos, [upgraded], self.wh.handoffs,
        )
        report = wh.report("EV2")
        self.assertEqual(report.action, ACTION_RECONFIRM)
        notice = next(n for n in report.notices if n.kind == "reconfirm")
        self.assertEqual(notice.details["confirmed_ref"], "F-44@1")
        self.assertEqual(notice.details["reconfirm_ref"], "F-44@3")
        # 已确认绑定没有被静默改写。
        self.assertEqual(report.confirmed_ref.key(), "F-44@1")

    def test_later_cure_does_not_silently_resume_suspended_show(self):
        # 批次 8 补到 A-410 的新授权：已确认主包重新合格，但暂停过的场次
        # 不能凭同名自动恢复，必须进入重新确认。
        from dataclasses import replace
        g3_withdraw = next(
            grant for grant in self.wh.grants
            if grant.grant == "G3" and grant.state == "withdraw"
        )
        cure = replace(
            g3_withdraw, grant="G9", state="allow", revision="1", received=8
        )
        wh = MediaWarehouse(
            self.wh.catalog, self.wh.composition_rows,
            [*self.wh.grants, cure], self.wh.cinemas,
            self.wh.schedule, self.wh.handoffs,
        )
        report = wh.report("EV2", as_of=8)
        self.assertEqual(report.action, ACTION_RECONFIRM)
        notice = next(n for n in report.notices if n.kind == "reconfirm")
        self.assertTrue(notice.details["cured_by_later_evidence"])
        self.assertEqual(notice.details["reconfirm_ref"], "F-44@1")
        # 绑定的确认包没有被静默改写。
        self.assertEqual(report.confirmed_ref.key(), "F-44@1")

    def test_review_queue_and_filters(self):
        review = {item.show.show for item in self.wh.review_queue()}
        self.assertEqual(review, {"EV1", "EV2", "EV3"})
        linquan = {item.show.show for item in self.wh.query(city="临泉")}
        self.assertEqual(linquan, {"EV1", "EV2"})
        day = {
            item.show.show
            for item in self.wh.query(date="2027-03-14")
        }
        self.assertEqual(day, {"EV2", "EV3", "EV4"})

    def test_offline_manifest_links_notices_to_prior_confirmation(self):
        manifest = self.wh.offline_manifest("EV2")
        self.assertEqual(manifest["confirmed"]["package"], "PK-B")
        self.assertEqual(manifest["confirmed"]["bound_ref"], "F-44@1")
        self.assertEqual(manifest["action"], ACTION_SUSPEND)
        # 清单指向确切素材与准用范围。
        candidate = next(c for c in manifest["candidates"] if c["ref"] == "F-44@2")
        usage = next(u for u in candidate["usages"] if u["leaf"] == "A-681@1")
        self.assertEqual(usage["status"], "denied")
        self.assertTrue(usage["reasons"])
        self.assertEqual(manifest["notices"][0]["package"], "PK-B")
        self.assertEqual(manifest["notices"][0]["revision"], "1")


if __name__ == "__main__":
    unittest.main()

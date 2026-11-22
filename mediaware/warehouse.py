"""媒体数据仓门面。

把六份来源资料接成同一套模型，并按到达批次提供双时点视图：

* 任意 ``as_of`` 批次只能看到当时及以前到达的授权与回执；
* 已放映场次冻结当时的确认与所据合同版本，后续证据只生成追查留痕，
  不改变已发生记录的原义；
* 未放映场次区分照常播放、需影院重新确认备包、必须暂停三类；
* 后到文件不能凭同名替换已确认包，迟到的旧确认不解除暂停。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import sources
from .eligibility import (
    PACKAGE_DENIED,
    PACKAGE_INCOMPATIBLE,
    PACKAGE_MISSING,
    CandidateVerdict,
    evaluate_candidate,
)
from .models import (
    ACTION_HISTORY,
    ACTION_PLAY,
    ACTION_RECONFIRM,
    ACTION_SUSPEND,
    ACCEPTED_STATUSES,
    AssetRef,
    CinemaCombo,
    CompositionRow,
    Grant,
    Handoff,
    LeafUsage,
    MediaItem,
    Show,
    STATUS_PLAYED,
)
from .rights import UsageVerdict, resolve_grants


@dataclass(frozen=True)
class Notice:
    """随交接包发出的一条通知，可与先前确认按场次与轮次对应。"""

    kind: str  # trace | reconfirm | suspend | play
    show: str
    package: str | None
    revision: str | None
    message: str
    details: dict

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "show": self.show,
            "package": self.package,
            "revision": self.revision,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class ShowReport:
    """一场放映在某个批次时点的完整结论。"""

    show: Show
    as_of: int
    city: str
    action: str
    action_reason: str
    candidates: tuple[CandidateVerdict, ...]
    confirmed_ref: AssetRef | None
    latest_acceptance: Handoff | None
    played_receipt: Handoff | None
    notices: tuple[Notice, ...]

    @property
    def confirmed_candidate(self) -> CandidateVerdict | None:
        if self.confirmed_ref is None:
            return None
        return next(
            (item for item in self.candidates if item.ref == self.confirmed_ref),
            None,
        )


class MediaWarehouse:
    """加载并持有全部来源资料，提供按批次的对账与查询。"""

    def __init__(
        self,
        catalog: Mapping[AssetRef, MediaItem],
        composition_rows: Sequence[CompositionRow],
        grants: Sequence[Grant],
        cinemas: Sequence[CinemaCombo],
        schedule: Sequence[Show],
        handoffs: Sequence[Handoff],
    ) -> None:
        self.catalog = dict(catalog)
        self.composition_rows = list(composition_rows)
        self.grants = list(grants)
        self.cinemas = list(cinemas)
        self.schedule = list(schedule)
        self.handoffs = list(handoffs)
        self._shows = {show.show: show for show in self.schedule}

    # ------------------------------------------------------------------ 加载
    @classmethod
    def from_directory(cls, data_dir: str | Path) -> "MediaWarehouse":
        base = Path(data_dir)
        return cls(
            catalog=sources.load_catalog(base / "catalog.csv"),
            composition_rows=sources.load_composition(base / "composition.csv"),
            grants=sources.load_grants(base / "grants.jsonl"),
            cinemas=sources.load_cinemas(base / "cinemas.csv"),
            schedule=sources.load_schedule(base / "schedule.db"),
            handoffs=sources.load_handoffs(base / "handoffs.jsonl"),
        )

    # ------------------------------------------------------------------ 工具
    @property
    def latest_batch(self) -> int:
        return max(
            [row.received for row in self.grants]
            + [row.received for row in self.handoffs],
            default=0,
        )

    def city_of(self, cinema: str) -> str:
        combo = next((row for row in self.cinemas if row.cinema == cinema), None)
        return combo.city if combo else ""

    def cinema_formats(self, cinema: str) -> tuple[str, ...]:
        return tuple(
            sorted({row.format for row in self.cinemas if row.cinema == cinema})
        )

    def handoffs_for(self, show_id: str, as_of: int | None = None) -> list[Handoff]:
        batch = self.latest_batch if as_of is None else as_of
        return [
            row
            for row in self.handoffs
            if row.show == show_id and row.received <= batch
        ]

    def expand(self, ref: AssetRef) -> list[LeafUsage]:
        from .composition import expand

        return expand(ref, self.composition_rows, self.catalog)

    def _candidate(
        self, show: Show, ref: AssetRef, as_of: int
    ) -> CandidateVerdict:
        effective = resolve_grants(self.grants, as_of)
        return evaluate_candidate(
            ref=ref,
            show=show,
            city=self.city_of(show.cinema),
            grants=effective,
            catalog=self.catalog,
            composition_rows=self.composition_rows,
            cinema_formats=self.cinema_formats(show.cinema),
        )

    # ------------------------------------------------------------ 场次状态机
    def report(self, show_id: str, as_of: int | None = None) -> ShowReport:
        show = self._shows[show_id]
        batch = self.latest_batch if as_of is None else as_of
        candidates = tuple(self._candidate(show, ref, batch) for ref in show.candidates)
        receipts = self.handoffs_for(show_id, batch)

        latest_acceptance = self._latest_acceptance(receipts)
        played = next(
            (row for row in reversed(receipts) if row.status == STATUS_PLAYED), None
        )
        confirmed_ref = self._confirmed_ref(show, receipts)

        notices: list[Notice] = []
        if played is not None:
            action, reason = ACTION_HISTORY, "场次已放映，记录按当时确认与合同版本冻结"
            notices.extend(self._history_traces(show, played, batch))
        elif latest_acceptance is None:
            action, reason = self._unconfirmed_action(candidates)
        else:
            action, reason, extra = self._confirmed_action(
                show, candidates, confirmed_ref, latest_acceptance, batch
            )
            notices.extend(extra)

        return ShowReport(
            show=show,
            as_of=batch,
            city=self.city_of(show.cinema),
            action=action,
            action_reason=reason,
            candidates=candidates,
            confirmed_ref=confirmed_ref,
            latest_acceptance=latest_acceptance,
            played_receipt=played,
            notices=tuple(notices),
        )

    def reports(self, as_of: int | None = None) -> list[ShowReport]:
        batch = self.latest_batch if as_of is None else as_of
        return [self.report(show.show, batch) for show in self.schedule]

    @staticmethod
    def _latest_acceptance(receipts: Sequence[Handoff]) -> Handoff | None:
        accepted = [row for row in receipts if row.status in ACCEPTED_STATUSES]
        return accepted[-1] if accepted else None

    @staticmethod
    def _confirmed_ref(show: Show, receipts: Sequence[Handoff]) -> AssetRef | None:
        """已确认包绑定到发包轮次对应的具体版本。

        轮次 1 对应排期主版本；影院确认的是具体放映版本和完整包，后到文件
        不能凭同名替换它，因此这里只解析轮次与版本的绑定，不做内容替换。
        """
        accepted = [row for row in receipts if row.status in ACCEPTED_STATUSES]
        if not accepted:
            return None
        revision = accepted[-1].revision
        if revision == "1":
            return show.main
        index = int(revision) - 1
        if index < len(show.candidates):
            return show.candidates[index]
        return None

    def _was_confirmed_blocked(
        self,
        show: Show,
        confirmed_ref: AssetRef | None,
        confirmed_batch: int,
        as_of: int,
    ) -> bool:
        """已确认包在确认之后的任一历史批次是否曾不可用。"""
        if confirmed_ref is None:
            return False
        for batch in range(confirmed_batch + 1, as_of):
            verdict = self._candidate(show, confirmed_ref, batch)
            if not verdict.eligible:
                return True
        return False

    @staticmethod
    def _unconfirmed_action(
        candidates: Sequence[CandidateVerdict],
    ) -> tuple[str, str]:
        if any(item.eligible for item in candidates):
            return (
                ACTION_PLAY,
                "影院尚未确认；存在权利齐备且兼容的可交接包，可发出发行单",
            )
        return ACTION_SUSPEND, _block_summary(candidates)

    def _confirmed_action(
        self,
        show: Show,
        candidates: Sequence[CandidateVerdict],
        confirmed_ref: AssetRef | None,
        acceptance: Handoff,
        as_of: int,
    ) -> tuple[str, str, list[Notice]]:
        confirmed = next(
            (item for item in candidates if item.ref == confirmed_ref), None
        )
        notices: list[Notice] = []
        # 若已确认包在首次接受之后、当前批次之前曾失效，即使后到补证使其重新
        # 合格，也不能凭同名静默恢复：影院须对当前完整包重新确认。
        first_acceptance = next(
            (row for row in self.handoffs_for(show.show, as_of)
             if row.status in ACCEPTED_STATUSES),
            None,
        )
        start_batch = (
            first_acceptance.received if first_acceptance else acceptance.received
        )
        was_blocked = self._was_confirmed_blocked(
            show, confirmed_ref, start_batch, as_of
        )
        if confirmed is not None and confirmed.eligible and not was_blocked:
            return (
                ACTION_PLAY,
                f"已确认包 {acceptance.package}（{confirmed_ref.key()}）仍可照常播放",
                notices,
            )
        if confirmed is not None and confirmed.eligible and was_blocked:
            notices.append(
                Notice(
                    kind="reconfirm",
                    show=show.show,
                    package=acceptance.package,
                    revision=acceptance.revision,
                    message=(
                        f"已确认包 {acceptance.package}（{confirmed_ref.key()}）曾因证据不足"
                        "暂停；后到补证虽使其重新合格，影院仍须重新确认当前完整包后才能恢复"
                    ),
                    details={
                        "confirmed_ref": confirmed_ref.key(),
                        "reconfirm_ref": confirmed_ref.key(),
                        "blocked": None,
                        "cured_by_later_evidence": True,
                    },
                )
            )
            return (
                ACTION_RECONFIRM,
                "已确认包经补证重新合格，但须影院重新确认，不自动恢复播放",
                notices,
            )

        # 已确认包不再成立：先找一个可交接的备选，但绝不静默替换。
        fallback = next(
            (item for item in candidates if item.eligible and item.ref != confirmed_ref),
            None,
        )
        if fallback is not None:
            notices.append(
                Notice(
                    kind="reconfirm",
                    show=show.show,
                    package=acceptance.package,
                    revision=acceptance.revision,
                    message=(
                        f"已确认包 {acceptance.package}（{confirmed_ref.key() if confirmed_ref else '?'}）"
                        f"不能继续使用；备选 {fallback.ref.key()} 权利齐备且兼容，"
                        "须由影院重新确认后才能换包，不做静默替换"
                    ),
                    details={
                        "confirmed_ref": confirmed_ref.key() if confirmed_ref else None,
                        "reconfirm_ref": fallback.ref.key(),
                        "blocked": _block_detail(confirmed) if confirmed else None,
                    },
                )
            )
            return (
                ACTION_RECONFIRM,
                "已确认包失效，已有可交接备包，等待影院重新确认",
                notices,
            )

        notices.append(
            Notice(
                kind="suspend",
                show=show.show,
                package=acceptance.package,
                revision=acceptance.revision,
                message=(
                    f"已确认包 {acceptance.package} 不能继续使用，且没有权利齐备、"
                    "兼容的备包，场次必须暂停；迟到的旧确认不解除暂停"
                ),
                details={
                    "confirmed_ref": confirmed_ref.key() if confirmed_ref else None,
                    "blocked": _block_detail(confirmed) if confirmed else _block_summary(candidates),
                },
            )
        )
        return ACTION_SUSPEND, _block_summary(candidates), notices

    # ------------------------------------------------------------ 历史追查
    def _history_traces(
        self, show: Show, played: Handoff, as_of: int
    ) -> list[Notice]:
        """比较放映时点与当前批次的权利结论，给出新证据对既往场次的追查。"""
        snapshot_batch = played.received
        if snapshot_batch >= as_of:
            return []
        old_candidates = tuple(
            self._candidate(show, ref, snapshot_batch) for ref in show.candidates
        )
        new_candidates = tuple(
            self._candidate(show, ref, as_of) for ref in show.candidates
        )
        confirmed_ref = self._confirmed_ref(
            show, self.handoffs_for(show.show, snapshot_batch)
        )

        old_verdict = next(
            (item for item in old_candidates if item.ref == confirmed_ref), None
        )
        new_verdict = next(
            (item for item in new_candidates if item.ref == confirmed_ref), None
        )
        usage_changes = _usage_drift(old_verdict, new_verdict)
        # 只把与已放映包构成相关的合同变更列为追查，无关权利方的文件不入本场留痕。
        relevant_refs = {
            verdict.usage.leaf
            for verdict in (new_verdict.usage_verdicts if new_verdict else ())
        }

        def _relevant(grant: Grant) -> bool:
            return grant.ref in relevant_refs

        old_grants = {
            row.grant: row
            for row in resolve_grants(self.grants, snapshot_batch)
            if _relevant(row)
        }
        new_grants = {
            row.grant: row
            for row in resolve_grants(self.grants, as_of)
            if _relevant(row)
        }
        changes: list[str] = []
        for grant_id in sorted(set(old_grants) | set(new_grants)):
            before, after = old_grants.get(grant_id), new_grants.get(grant_id)
            if before is None and after is not None:
                changes.append(f"新到合同 {grant_id}（{after.state}）")
            elif after is None and before is not None:
                changes.append(f"合同 {grant_id} 已撤销退出生效（原修订 {before.revision}）")
            elif before is not None and after is not None and (
                before.state != after.state or before.revision != after.revision
            ):
                changes.append(
                    f"合同 {grant_id} 由修订 {before.revision}/{before.state} "
                    f"变为修订 {after.revision}/{after.state}"
                )

        if not changes and not usage_changes:
            return []
        return [
            Notice(
                kind="trace",
                show=show.show,
                package=played.package,
                revision=played.revision,
                message=(
                    f"放映后到达的新证据对本场提出追查：{'; '.join(changes) or '合同文本变更'}；"
                    "已发生记录保持原义，原确认与所据合同版本不变"
                ),
                details={
                    "snapshot_batch": snapshot_batch,
                    "current_batch": as_of,
                    "confirmed_ref": confirmed_ref.key() if confirmed_ref else None,
                    "grant_changes": changes,
                    "usage_changes": usage_changes,
                },
            )
        ]

    def evidence_trace(self, show_id: str) -> dict:
        """供发行部查看一项新证据对既往场次提出了什么追查。"""
        show = self._shows[show_id]
        receipts = self.handoffs_for(show_id, self.latest_batch)
        played = next(
            (row for row in reversed(receipts) if row.status == STATUS_PLAYED), None
        )
        if played is None:
            return {"show": show_id, "played": False, "traces": []}
        notices = self._history_traces(show, played, self.latest_batch)
        return {
            "show": show_id,
            "played": True,
            "frozen_package": played.package,
            "frozen_revision": played.revision,
            "frozen_batch": played.received,
            "traces": [notice.to_dict() for notice in notices],
        }

    # ---------------------------------------------------------------- 查询
    def query(
        self,
        city: str | None = None,
        date: str | None = None,
        as_of: int | None = None,
    ) -> list[ShowReport]:
        """按城市及放映日查可交接版本与待复核场次。"""
        reports = self.reports(as_of)
        if city is not None:
            reports = [item for item in reports if item.city == city]
        if date is not None:
            reports = [item for item in reports if item.show.start.date().isoformat() == date]
        return reports

    def review_queue(self, as_of: int | None = None) -> list[ShowReport]:
        """待复核场次：暂停、需重新确认，以及已放映但有追查留痕的场次。"""
        return [
            report
            for report in self.reports(as_of)
            if report.action in {ACTION_SUSPEND, ACTION_RECONFIRM}
            or any(notice.kind == "trace" for notice in report.notices)
        ]

    def offline_manifest(self, show_id: str, as_of: int | None = None) -> dict:
        """影院离线交接清单：确切素材、准用范围、通知与先前确认对应。"""
        report = self.report(show_id, as_of)
        return {
            "show": report.show.show,
            "cinema": report.show.cinema,
            "city": report.city,
            "window": {
                "start": report.show.start.isoformat(),
                "end": report.show.end.isoformat(),
            },
            "as_of_batch": report.as_of,
            "action": report.action,
            "action_reason": report.action_reason,
            "confirmed": _acceptance_dict(report.latest_acceptance, report.confirmed_ref),
            "candidates": [
                candidate_to_dict(item, report.city, report.show)
                for item in report.candidates
            ],
            "notices": [notice.to_dict() for notice in report.notices],
        }


# ---------------------------------------------------------------- 序列化辅助
def _acceptance_dict(receipt: Handoff | None, ref: AssetRef | None) -> dict | None:
    if receipt is None:
        return None
    return {
        "package": receipt.package,
        "revision": receipt.revision,
        "status": receipt.status,
        "received_batch": receipt.received,
        "bound_ref": ref.key() if ref else None,
    }


def _usage_drift(
    old: CandidateVerdict | None, new: CandidateVerdict | None
) -> list[dict]:
    if old is None or new is None:
        return []
    drift: list[dict] = []
    old_map = {item.usage.leaf.key(): item for item in old.usage_verdicts}
    new_map = {item.usage.leaf.key(): item for item in new.usage_verdicts}
    for key in sorted(set(old_map) | set(new_map)):
        before, after = old_map.get(key), new_map.get(key)
        if before is None or after is None or before.status != after.status:
            drift.append(
                {
                    "leaf": key,
                    "part": (after or before).usage.part,
                    "before": before.status if before else None,
                    "after": after.status if after else None,
                    "after_reasons": after.reasons if after else (),
                }
            )
    return drift


def _block_detail(verdict: CandidateVerdict | None) -> dict | None:
    if verdict is None:
        return None
    return {
        "ref": verdict.ref.key(),
        "status": verdict.status,
        "compatible": verdict.compatible,
        "cinema_formats": list(verdict.cinema_formats),
        "package_format": verdict.package_format,
        "blocked_usages": [_usage_item(item) for item in verdict.usage_verdicts if item.status != "ok"],
    }


def _block_summary(candidates: Sequence[CandidateVerdict]) -> str:
    parts = []
    for item in candidates:
        if item.eligible:
            continue
        if item.status == PACKAGE_INCOMPATIBLE:
            parts.append(
                f"{item.ref.key()} 格式 {item.package_format} 不在影院公布组合 {list(item.cinema_formats)}"
            )
        elif item.status == PACKAGE_DENIED:
            reasons = "; ".join(reason for verdict in item.usage_verdicts for reason in verdict.reasons)
            parts.append(f"{item.ref.key()} 存在明确禁止：{reasons}")
        elif item.status == PACKAGE_MISSING:
            parts.append(f"{item.ref.key()} 存在缺证使用段，发行方需补合同")
        else:
            parts.append(f"{item.ref.key()} 无法核对：{item.error}")
    return "；".join(parts) or "没有可交接包"


def _usage_item(verdict: UsageVerdict) -> dict:
    usage = verdict.usage
    return {
        "leaf": usage.leaf.key(),
        "part": usage.part,
        "leaf_span": [usage.leaf_in, usage.leaf_out],
        "root_span": [usage.root_in, usage.root_out],
        "status": verdict.status,
        "gaps": [list(span) for span in verdict.gaps],
        "reasons": list(verdict.reasons),
        "evidence": [f"{grant.grant}@r{grant.revision}" for grant in verdict.evidence],
    }


def grant_to_dict(grant: Grant) -> dict:
    return {
        "grant": grant.grant,
        "revision": grant.revision,
        "city": grant.city,
        "asset": grant.ref.asset,
        "edition": grant.ref.edition,
        "segment": [grant.from_sec, grant.to_sec],
        "opens": grant.opens.isoformat(),
        "closes": grant.closes.isoformat(),
        "media": grant.media,
        "state": grant.state,
        "received": grant.received,
    }


def candidate_to_dict(
    verdict: CandidateVerdict, city: str, show: Show
) -> dict:
    return {
        "ref": verdict.ref.key(),
        "format": verdict.package_format,
        "compatible": verdict.compatible,
        "cinema_formats": list(verdict.cinema_formats),
        "status": verdict.status,
        "eligible": verdict.eligible,
        "error": verdict.error,
        "usages": [_usage_item(item) for item in verdict.usage_verdicts],
        "evidence": [grant_to_dict(grant) for grant in verdict.evidence],
        "screening": {
            "city": city,
            "window": [show.start.isoformat(), show.end.isoformat()],
        },
    }


def report_to_dict(report: ShowReport) -> dict:
    return {
        "show": report.show.show,
        "cinema": report.show.cinema,
        "city": report.city,
        "as_of_batch": report.as_of,
        "window": {
            "start": report.show.start.isoformat(),
            "end": report.show.end.isoformat(),
        },
        "action": report.action,
        "action_reason": report.action_reason,
        "confirmed_ref": report.confirmed_ref.key() if report.confirmed_ref else None,
        "latest_acceptance": _acceptance_dict(
            report.latest_acceptance, report.confirmed_ref
        ),
        "played": _acceptance_dict(report.played_receipt, report.confirmed_ref),
        "candidates": [
            candidate_to_dict(item, report.city, report.show)
            for item in report.candidates
        ],
        "notices": [notice.to_dict() for notice in report.notices],
    }

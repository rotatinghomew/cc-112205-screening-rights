"""权利判定。

规则：

* 只看在 ``as_of`` 批次及以前已到达的文件；同一合同号取可见的最高修订，
  最高修订为 ``withdraw`` 时该合同整体退出生效，其他合同号独立判断。
* 授权城市为 ``*`` 或具体城市；媒介须为现场放映（``screen``）。
* 时间区间半开（含起点不含终点）。一份合同只在其有效期内成立，期限有空档
  时不能用首尾日期抹平：按所有有效期边界把场次窗口切片后逐片判定。
* 素材坐标按实际使用段核对。``deny`` 是有效期与使用范围内的明确禁止，
  优先于一般准许；没有任何合同覆盖的部分是缺证（missing），与禁用不同。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .models import (
    MEDIA_SCREEN,
    STATE_ALLOW,
    STATE_DENY,
    STATE_WITHDRAW,
    Grant,
    LeafUsage,
    USAGE_DENIED,
    USAGE_MISSING,
    USAGE_OK,
)
from datetime import datetime


@dataclass(frozen=True)
class UsageVerdict:
    """一条原件使用段的权利结论。"""

    usage: LeafUsage
    status: str
    evidence: tuple[Grant, ...]
    gaps: tuple[tuple[int, int], ...]
    denials: tuple[Grant, ...]

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(_deny_reason(grant) for grant in self.denials)


def _deny_reason(grant: Grant) -> str:
    return (
        f"合同 {grant.grant}（修订 {grant.revision}）明确禁止 {grant.city} "
        f"现场放映 {grant.ref.asset}@{grant.ref.edition} 秒 {grant.from_sec}"
        f"至 {grant.to_sec}，有效期 {grant.opens.isoformat()} 至 "
        f"{grant.closes.isoformat()}"
    )


def resolve_grants(grants: Sequence[Grant], as_of: int) -> list[Grant]:
    """按到达批次解析出当前仍生效的合同行（撤销者退出，旧修订被取代）。"""
    latest: dict[str, Grant] = {}
    for grant in grants:
        if grant.received > as_of:
            continue
        current = latest.get(grant.grant)
        if current is None or _revision_key(grant.revision) > _revision_key(current.revision):
            latest[grant.grant] = grant
    return [grant for grant in latest.values() if grant.state != STATE_WITHDRAW]


def _revision_key(revision: str) -> tuple:
    # 修订号保持文本比较；数据中为整数串，按数值序处理更稳妥。
    return (0, int(revision)) if revision.isdigit() else (1, revision)


def _merge(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _gaps(
    span: tuple[int, int], covered: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    start, end = span
    missing: list[tuple[int, int]] = []
    cursor = start
    for cover_start, cover_end in _merge(covered):
        if cover_start > cursor:
            missing.append((cursor, cover_start))
        cursor = max(cursor, cover_end)
    if cursor < end:
        missing.append((cursor, end))
    return missing


def _applicable(
    grants: Sequence[Grant],
    usage: LeafUsage,
    city: str,
    time_start: datetime,
    time_end: datetime,
) -> list[Grant]:
    return [
        grant
        for grant in grants
        if grant.media == MEDIA_SCREEN
        and grant.covers_city(city)
        and grant.ref == usage.leaf
        and grant.to_sec > usage.leaf_in
        and grant.from_sec < usage.leaf_out
        and grant.closes > time_start
        and grant.opens < time_end
    ]


def evaluate_usage(
    usage: LeafUsage,
    city: str,
    time_start: datetime,
    time_end: datetime,
    grants: Sequence[Grant],
) -> UsageVerdict:
    """判定单个使用段在整场时间窗与放映地内是否权利齐备。"""
    relevant = _applicable(grants, usage, city, time_start, time_end)
    boundaries = {time_start, time_end}
    for grant in relevant:
        boundaries.add(max(grant.opens, time_start))
        boundaries.add(min(grant.closes, time_end))
    timeline = sorted(boundaries)

    span = (usage.leaf_in, usage.leaf_out)
    evidence: set[Grant] = set()
    gaps: list[tuple[int, int]] = []
    denials: list[Grant] = []

    for slice_start, slice_end in zip(timeline, timeline[1:]):
        active = [
            grant
            for grant in relevant
            if grant.opens <= slice_start and grant.closes >= slice_end
        ]
        deny_rows = [grant for grant in active if grant.state == STATE_DENY]
        allow_rows = [grant for grant in active if grant.state == STATE_ALLOW]
        for grant in deny_rows:
            overlap = (
                max(grant.from_sec, span[0]),
                min(grant.to_sec, span[1]),
            )
            if overlap[0] < overlap[1]:
                denials.append(grant)
        if deny_rows:
            # 明确禁止优先；该时间片不再以准许覆盖补缺。
            continue
        covered = _merge(
            (max(grant.from_sec, span[0]), min(grant.to_sec, span[1]))
            for grant in allow_rows
        )
        evidence.update(allow_rows)
        gaps.extend(_gaps(span, covered))

    if denials:
        status = USAGE_DENIED
    elif gaps:
        status = USAGE_MISSING
    else:
        status = USAGE_OK
    return UsageVerdict(
        usage=usage,
        status=status,
        evidence=tuple(sorted(evidence, key=lambda item: (item.grant, item.revision))),
        gaps=tuple(_merge(gaps)),
        denials=tuple(
            sorted({grant.grant: grant for grant in denials}.values(),
                   key=lambda item: (item.grant, item.revision))
        ),
    )

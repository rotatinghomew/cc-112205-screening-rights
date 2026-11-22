"""放映包（具体剪辑版本）可用性判定。

一个包可用必须同时满足：

1. 递归展开后的每条声轨、画面、字幕使用段在整场时间与放映地内权利齐备；
2. 包的格式属于该影院自己公布过的声音轨+字幕组合。

缺证（没有合同）与禁用（``deny`` 明确禁止）分别给出结论；兼容不通过时
即使权利齐备也不能排。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .composition import expand
from .models import (
    CinemaCombo,
    MediaItem,
    AssetRef,
    Show,
    USAGE_DENIED,
    USAGE_MISSING,
    USAGE_OK,
)
from .rights import UsageVerdict, evaluate_usage, resolve_grants
from .models import Grant
from .models import CompositionRow

# 包级状态
PACKAGE_ELIGIBLE = "eligible"
PACKAGE_DENIED = "denied"
PACKAGE_MISSING = "missing"
PACKAGE_INCOMPATIBLE = "incompatible"
PACKAGE_UNKNOWN = "unknown"  # 成品不在目录/构成无法闭合


@dataclass(frozen=True)
class CandidateVerdict:
    """一个候选版本（主版本或备选版本）的完整判定。"""

    ref: AssetRef
    package_format: str | None
    compatible: bool
    cinema_formats: tuple[str, ...]
    usage_verdicts: tuple[UsageVerdict, ...]
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error is not None:
            return PACKAGE_UNKNOWN
        if not self.compatible:
            return PACKAGE_INCOMPATIBLE
        if any(verdict.status == USAGE_DENIED for verdict in self.usage_verdicts):
            return PACKAGE_DENIED
        if any(verdict.status == USAGE_MISSING for verdict in self.usage_verdicts):
            return PACKAGE_MISSING
        return PACKAGE_ELIGIBLE

    @property
    def eligible(self) -> bool:
        return self.status == PACKAGE_ELIGIBLE

    @property
    def evidence(self) -> tuple[Grant, ...]:
        seen: dict[tuple[str, str], Grant] = {}
        for verdict in self.usage_verdicts:
            for grant in verdict.evidence:
                seen[(grant.grant, grant.revision)] = grant
        return tuple(sorted(seen.values(), key=lambda item: (item.grant, item.revision)))


def evaluate_candidate(
    ref: AssetRef,
    show: Show,
    city: str,
    grants: Sequence[Grant],
    catalog: Mapping[AssetRef, MediaItem],
    composition_rows: Sequence[CompositionRow],
    cinema_formats: Sequence[str],
) -> CandidateVerdict:
    """对单个候选版本做构成展开、逐段权利判定与兼容核对。"""
    formats = tuple(sorted(set(cinema_formats)))
    item = catalog.get(ref)
    if item is None:
        return CandidateVerdict(
            ref=ref,
            package_format=None,
            compatible=False,
            cinema_formats=formats,
            usage_verdicts=(),
            error=f"{ref.key()} 不在媒体目录中",
        )
    compatible = item.format in formats
    leaves = expand(ref, composition_rows, catalog)
    verdicts = tuple(
        evaluate_usage(usage, city, show.start, show.end, grants)
        for usage in leaves
    )
    return CandidateVerdict(
        ref=ref,
        package_format=item.format,
        compatible=compatible,
        cinema_formats=formats,
        usage_verdicts=verdicts,
    )


def evaluate_show(
    show: Show,
    grants: Sequence[Grant],
    catalog: Mapping[AssetRef, MediaItem],
    composition_rows: Sequence[CompositionRow],
    combos: Sequence[CinemaCombo],
) -> tuple[CandidateVerdict, ...]:
    """按排期顺序（主版本、片方推荐备选）给出各包判定。"""
    effective = resolve_grants(grants, max((row.received for row in grants), default=0))
    city = next((combo.city for combo in combos if combo.cinema == show.cinema), "")
    cinema_formats = [combo.format for combo in combos if combo.cinema == show.cinema]
    return tuple(
        evaluate_candidate(
            ref, show, city, effective, catalog, composition_rows, cinema_formats
        )
        for ref in show.candidates
    )

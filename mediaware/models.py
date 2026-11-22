"""来源资料的领域模型。

原始标识（asset、edition、show、cinema、grant、package 等）一律保持文本；
时间字段解析为带时区的 ``datetime``；素材坐标为整数秒。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# 媒介范围：现场放映
MEDIA_SCREEN = "screen"

# 授权状态
STATE_ALLOW = "allow"
STATE_DENY = "deny"
STATE_WITHDRAW = "withdraw"

# 交接回执状态
STATUS_OFFERED = "offered"
STATUS_CONFIRMED = "confirmed"
STATUS_PRELOADED = "preloaded"
STATUS_PLAYED = "played"

# 影院已接受对应剪辑的状态
ACCEPTED_STATUSES = frozenset({STATUS_CONFIRMED, STATUS_PRELOADED, STATUS_PLAYED})

# 场次处置动作
ACTION_PLAY = "play"            # 仍可照常播放
ACTION_RECONFIRM = "reconfirm"  # 需影院重新确认备包
ACTION_SUSPEND = "suspend"      # 必须暂停
ACTION_HISTORY = "history"      # 已放映，仅留痕

# 单条声轨/画面/字幕使用的判定
USAGE_OK = "ok"
USAGE_MISSING = "missing"  # 没有合同：发行方看到缺证
USAGE_DENIED = "denied"    # 明确禁止：附禁用原因


@dataclass(frozen=True)
class AssetRef:
    """目录中一份素材的对象键与版本，版本保持文本。"""

    asset: str
    edition: str

    @classmethod
    def parse(cls, raw: str) -> "AssetRef":
        """解析排期里 ``F-44@2`` 形式的素材键与版本。"""
        asset, edition = raw.split("@", 1)
        return cls(asset=asset, edition=edition)

    def key(self) -> str:
        return f"{self.asset}@{self.edition}"


@dataclass(frozen=True)
class MediaItem:
    """catalog.csv 的一行：媒体目录条目。"""

    ref: AssetRef
    kind: str
    format: str
    seconds: int


@dataclass(frozen=True)
class CompositionRow:
    """composition.csv 的一行：成品时间段与所引用素材时间段等长。"""

    parent: AssetRef
    child: AssetRef
    part: str
    parent_in: int
    child_in: int
    length: int


@dataclass(frozen=True)
class LeafUsage:
    """递归展开到原件后的一段实际使用。

    坐标分别落在原件自身时间轴（``leaf_in``/``leaf_in + length``）与
    成品根对象时间轴（``root_in``/``root_in + length``）上；``part`` 为
    声轨/画面/字幕等轨道名。
    """

    leaf: AssetRef
    part: str
    leaf_in: int
    length: int
    root_in: int
    chain: tuple[AssetRef, ...]

    @property
    def leaf_out(self) -> int:
        return self.leaf_in + self.length

    @property
    def root_out(self) -> int:
        return self.root_in + self.length


@dataclass(frozen=True)
class Grant:
    """grants.jsonl 的一行：权利方出具的授权/禁止/撤销。"""

    grant: str
    revision: str
    city: str
    ref: AssetRef
    from_sec: int
    to_sec: int
    opens: datetime
    closes: datetime
    media: str
    state: str
    received: int

    def covers_city(self, city: str) -> bool:
        return self.city == "*" or self.city == city

    def covers_segment(self, start: int, end: int) -> bool:
        return self.from_sec <= start and end <= self.to_sec


@dataclass(frozen=True)
class CinemaCombo:
    """cinemas.csv 的一行：影院公布过的一种声音轨+字幕组合。"""

    cinema: str
    city: str
    format: str


@dataclass(frozen=True)
class Show:
    """schedule.db 的一行：一场排期，含片方推荐顺序的备包。"""

    show: str
    cinema: str
    start: datetime
    end: datetime
    main: AssetRef
    fallbacks: tuple[AssetRef, ...]

    @property
    def candidates(self) -> tuple[AssetRef, ...]:
        """主版本在前、备选版本按推荐顺序在后。"""
        return (self.main, *self.fallbacks)


@dataclass(frozen=True)
class Handoff:
    """handoffs.jsonl 的一行：影院对某个交接轮次的回执。"""

    show: str
    package: str
    revision: str
    status: str
    received: int

"""剪辑构成展开。

合成目录中的素材引用按对象键与版本递归展开到原件（没有子件的对象），
声轨、画面、字幕分别登记；成品时间段与所引用素材时间段等长，坐标按
``parent_in``/``child_in`` 逐层换算。``part`` 为 ``all`` 的行表示整条引用
继承子件自身的轨道，轨道名由下一层（或原件条目）给出。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import AssetRef, CompositionRow, LeafUsage, MediaItem

PART_ALL = "all"


class CompositionError(ValueError):
    """构成表无法闭合（引用缺失、循环或越界）。"""


def _rows_by_parent(
    rows: Sequence[CompositionRow],
) -> dict[AssetRef, list[CompositionRow]]:
    grouped: dict[AssetRef, list[CompositionRow]] = {}
    for row in rows:
        grouped.setdefault(row.parent, []).append(row)
    return grouped


def expand(
    root: AssetRef,
    rows: Sequence[CompositionRow],
    catalog: Mapping[AssetRef, MediaItem],
) -> list[LeafUsage]:
    """把 ``root`` 展开为原件使用段列表，按成品时间轴排序。"""
    if root not in catalog:
        raise CompositionError(f"成品 {root.key()} 不在媒体目录中")
    grouped = _rows_by_parent(rows)
    usage: list[LeafUsage] = []

    def walk(
        ref: AssetRef,
        seg_in: int,
        seg_len: int,
        root_in: int,
        inherited_part: str | None,
        chain: tuple[AssetRef, ...],
    ) -> None:
        if ref in chain:
            raise CompositionError(f"构成出现循环引用：{' -> '.join(x.key() for x in chain)} -> {ref.key()}")
        if ref not in catalog:
            raise CompositionError(f"素材 {ref.key()} 不在媒体目录中")
        child_rows = grouped.get(ref)
        if not child_rows:
            # 原件：没有子件，直接登记实际使用的那一段。
            usage.append(
                LeafUsage(
                    leaf=ref,
                    part=inherited_part or catalog[ref].kind,
                    leaf_in=seg_in,
                    length=seg_len,
                    root_in=root_in,
                    chain=chain + (ref,),
                )
            )
            return

        seg_out = seg_in + seg_len
        for row in child_rows:
            row_out = row.parent_in + row.length
            overlap_in = max(seg_in, row.parent_in)
            overlap_out = min(seg_out, row_out)
            if overlap_in >= overlap_out:
                continue
            offset = overlap_in - row.parent_in
            child_in = row.child_in + offset
            child_len = overlap_out - overlap_in
            child_root_in = root_in + (overlap_in - seg_in)
            part = inherited_part if row.part == PART_ALL else row.part
            walk(
                row.child,
                child_in,
                child_len,
                child_root_in,
                part,
                chain + (ref,),
            )

    walk(root, 0, catalog[root].seconds, 0, None, ())
    usage.sort(key=lambda item: (item.root_in, item.part, item.leaf.key()))
    return usage

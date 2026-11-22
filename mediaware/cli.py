"""发行部命令行。

用法示例（项目根目录）::

    python3 -m mediaware query --city 临泉 --date 2027-03-14
    python3 -m mediaware review
    python3 -m mediaware manifest EV2
    python3 -m mediaware trace EV1
    python3 -m mediaware grants

``--as-of`` 可指定到达批次，复现某个时点仓内可见的事实；默认取最新批次。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .warehouse import MediaWarehouse, grant_to_dict, report_to_dict

DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data"


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", default=str(DEFAULT_DATA), help="来源资料目录")
    common.add_argument(
        "--as-of", type=int, default=None, help="只看该批次及以前到达的文件"
    )
    parser = argparse.ArgumentParser(
        prog="mediaware", description="巡展媒体数据仓对账工具", parents=[common]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    query = sub.add_parser(
        "query", help="按城市及放映日查可交接版本与待复核场次", parents=[common]
    )
    query.add_argument("--city", default=None)
    query.add_argument("--date", default=None, help="放映日 YYYY-MM-DD")

    sub.add_parser("review", help="列出待复核场次", parents=[common])
    sub.add_parser("grants", help="列出当前生效的合同（撤销者已退出）", parents=[common])

    manifest = sub.add_parser(
        "manifest", help="生成一场的离线交接清单", parents=[common]
    )
    manifest.add_argument("show")

    trace = sub.add_parser(
        "trace", help="查看新证据对既往场次的追查", parents=[common]
    )
    trace.add_argument("show")

    sub.add_parser("shows", help="列出全部场次结论", parents=[common])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    warehouse = MediaWarehouse.from_directory(args.data)

    if args.command == "query":
        reports = warehouse.query(city=args.city, date=args.date, as_of=args.as_of)
        _print([report_to_dict(item) for item in reports])
    elif args.command == "review":
        _print([report_to_dict(item) for item in warehouse.review_queue(args.as_of)])
    elif args.command == "shows":
        _print([report_to_dict(item) for item in warehouse.reports(args.as_of)])
    elif args.command == "grants":
        from .rights import resolve_grants

        effective = resolve_grants(warehouse.grants, args.as_of or warehouse.latest_batch)
        _print([grant_to_dict(grant) for grant in effective])
    elif args.command == "manifest":
        _print(warehouse.offline_manifest(args.show, args.as_of))
    elif args.command == "trace":
        _print(warehouse.evidence_trace(args.show))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# 巡展媒体

发行部与影院用这组交接单演练素材、合同和排期的对账。媒体索引只记录时间范围及格式，不包含实际可播放影片。

## 资料格式

CSV 和 JSON Lines 均为 UTF-8。SQLite 来源库只读，原始标识保持文本类型。同时交付的多行可以有相同的 `received`，这个字段表示到达批次，不用行号决定同批事实的优先级。

场次和授权的时间为带时区时间，区间包含起点且不含终点。素材的时间坐标为从本文件起始算起的整数秒，音轨、画面和字幕分别登记。构成表的成品时间段和所引用素材时间段等长。没有子件的对象是原件，合成目录中的素材引用可用对象键与版本查找。
权利源只由相应权利方出具，媒介范围 `screen` 代表现场放映。城市 `*` 适用于所有列明城市。授权版本提高时只改同一合同号，`deny` 是有效期和使用范围内的明确禁止，优先于一般准许，`withdraw` 使该合同旧版退出生效；其他合同独立判断。发行单中的 `confirmed`、`preloaded`、`played` 表示影院已接受对应剪辑，`offered` 还未接受；影院回复以发行单号和轮次对应，轮次随该场重新发包递增。兼容表写影院认可的声道和字幕组合。

- `catalog.csv`。片方媒体目录，`asset` 和 `edition` 一起标识一份素材。`format` 在影院兼容表中使用。 字段为 `asset`、`edition`、`kind`、`format`、`seconds`。
- `composition.csv`。制作方提供的剪辑构成。`parent_in` 与 `child_in` 为各自起点，`length` 为长度。 字段为 `parent`、`parent_edition`、`child`、`child_edition`、`part`、`parent_in`、`child_in`、`length`。
- `grants.jsonl`。版权方出具的授权单。`from_sec` 与 `to_sec` 指向素材可用片段，`received` 是仓可见的顺序号。 字段为 `grant`、`revision`、`city`、`asset`、`edition`、`from_sec`、`to_sec`、`opens`、`closes`、`media`、`state`、`received`。
- `cinemas.csv`。影院发布的兼容组合，一个院线可以登记多种组合。 字段为 `cinema`、`city`、`format`。
- `schedule.db`。影院排程，`fallbacks` 使用逗号分隔的素材键和版本，顺序为片方推荐顺序。 字段为 `show`、`cinema`、`start`、`end`、`asset`、`edition`、`fallbacks`。 SQLite 表名为 `schedule`。
- `handoffs.jsonl`。影院回执日志。`package` 为对侧的媒体包号，`revision` 为交接轮次。 字段为 `show`、`package`、`revision`、`status`、`received`。

## 核对交付资料

使用 Python 3.11 和标准库。
在项目根目录运行下列命令，核对原始来源键、实际文件和格式。

```sh
python3 -m unittest discover -s tests -v
```

## 媒体数据仓（`mediaware`）

来源资料通过只依赖标准库的 `mediaware` 包接成同一套对账模型，全程不改动
`data/` 中的原始文件，SQLite 仍以只读方式打开。

- `sources.py`：按原格式加载六份资料，标识保持文本，时间解析为带时区时间。
- `models.py`：素材、构成行、原件使用段、授权、影院组合、场次与回执模型。
- `composition.py`：把剪辑构成递归展开到原件，声轨、画面、字幕分别登记；
  支持多层合成与 `part=all` 整条引用，坐标按 `parent_in`/`child_in` 换算，
  只登记实际使用到的原件片段（如 `F-44@3` 只用 `A-117` 的 10–90 秒）。
- `rights.py`：按到达批次解析合同（同合同号取最高修订，`withdraw` 退出，
  其他合同独立），再按放映地、整场时间窗与素材片段判定。时间区间半开，
  有效期空档按时间切片暴露，不用首尾日期抹平；`deny` 优先于一般准许并
  附禁用原因，没有合同的部分判为缺证（`missing`），与禁用（`denied`）区分。
- `eligibility.py`：对每个候选版本同时核对逐段权利与影院公布的声音轨+字幕
  组合，任一不过即不可交接，状态为 `eligible`/`missing`/`denied`/
  `incompatible`/`unknown`。
- `warehouse.py`：仓库门面与场次状态机，`handoffs.jsonl` 的回执按发行单号
  与轮次对应；影院确认绑定具体放映版本，后到文件不能凭同名替换。
- `cli.py` / `__main__.py`：发行部命令行，支持 `--as-of 批次` 复现历史时点。

### 场次处置语义

- `play`：未确认场有合格包可发包；或已确认包在当前批次仍可照常播放。
- `reconfirm`：已确认包失效，但存在权利齐备且兼容的备选；只发重新确认
  通知，绝不静默换包，影院迟到的旧确认不改变该结论。
- `suspend`：已确认包失效且没有合格备选（缺证、禁用或兼容不过），必须暂停。
- `history`：已放映场次冻结当时的确认与所据合同版本；之后到达的证据只
  生成 `trace` 追查留痕（仅列与该包构成相关的合同），已发生记录保持原义。

### 命令行

```sh
python3 -m mediaware shows                       # 全部场次结论
python3 -m mediaware query --city 临泉 --date 2027-03-14
python3 -m mediaware review                      # 待复核场次与追查
python3 -m mediaware grants                      # 当前生效合同（撤销者已退出）
python3 -m mediaware manifest EV2                # 影院离线交接清单
python3 -m mediaware trace EV1                   # 新证据对既往场次的追查
python3 -m mediaware shows --as-of 4             # 复现第 4 批次时点的结论
```

离线交接清单指向确切素材键、原件时间坐标、准用城市与时间窗、证据合同号，
并把换包/停播通知与先前确认的包号、轮次对应起来。

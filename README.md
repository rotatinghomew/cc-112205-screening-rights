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

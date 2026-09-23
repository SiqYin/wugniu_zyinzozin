# 字音数据库结构说明

本文说明四张表和三个索引分别做什么，以及它们怎样配合完成汉字查询、拼音反查和单向的简体转繁体。

本文中的数据内容、字段对应关系和输入处理均以当前 `index.html` 为唯一依据，不从其他网站、词典或外部规范补充资料。唯一明确调整是：前向查字结果需要在同一方言内删除重复读音；查询结果不要求保持原数组顺序。

```text
dialects
  id, code, display_name, ipa, romanization

characters
  id, character

readings
  id, character_id, dialect_id
  romanization, ipa, audio, note

character_variants
  source_character, target_character, variant_type
```

整体关系是：

```text
characters 1 ───< readings >─── 1 dialects
     │
     └───< character_variants
```

- 一个汉字可以在多个方言中有读音。
- 一个方言可以收录多个汉字。
- 一个汉字在同一方言中可以有多个读音，所以 `readings` 允许多行。
- 一个简体字可能对应多个繁体字，所以 `character_variants` 也允许一对多。

## `dialects`：方言或资料集

这张表记录系统支持哪些方言、音系或资料来源，不存具体字音。

| id | code | display_name | ipa | romanization |
|---:|---|---|:---:|:---:|
| 1 | `suhu` | 蘇滬混合腔 | `TRUE` | `TRUE` |
| 2 | `qingmo` | 清末蘇州話 | `TRUE` | `FALSE` |
| 3 | `shanghai` | 上海話 | `TRUE` | `FALSE` |
| 4 | `suzhou` | 蘇州話 | `TRUE` | `FALSE` |
| 5 | `pingtan` | 蘇州評彈音 | `TRUE` | `FALSE` |

### `id`

数据库内部主键，通常使用自动递增整数。`readings.dialect_id` 通过它指向某套方言资料。

整数关联键比在每条读音中反复保存“蘇滬混合腔”等长名称更紧凑。`id` 属于内部实现，不应作为公开且永不变化的方言编号。

### `code`

稳定、供程序使用的方言代码，例如 `suhu`、`shanghai`，建议设置为唯一值。它适合用于：

- API 参数，例如 `/api/readings?dialect=suhu`；
- 前端复选框的值；
- 导入脚本和配置文件；
- 多语言翻译键。

显示名称以后即使修改，`code` 也不需要变化。

### `display_name`

展示给用户看的名称，例如“蘇滬混合腔”。它可以修改，不应用作表之间的关联键。

如果以后需要完整的多语言名称，可以另建翻译表；当前规模较小时，也可以继续由前端按照 `code` 翻译。

### `ipa`

布尔值，表示该方言资料是否提供 IPA。`TRUE` 表示提供，`FALSE` 表示不提供。

这里的 `dialects.ipa` 是“资料能力标记”，不是具体音标文本；真正的音标仍保存在 `readings.ipa`。前端可据此决定是否显示 IPA 栏，导入程序也可检查：当该值为 `FALSE` 时，对应读音记录的 `readings.ipa` 通常应为 `NULL`。

### `romanization`

布尔值，表示该方言资料是否提供罗马字或拼音。蘇滬混合腔为 `TRUE`，其他目前只有音标的资料为 `FALSE`。

这里的 `dialects.romanization` 同样是能力标记；具体拼音文本保存在 `readings.romanization`。把原来的单个类型字段拆成两个布尔值后，IPA 和罗马字成为互相独立的能力，不必再维护 `ipa`、`romanization_ipa` 等组合类型字符串。

SQLite 没有独立的布尔存储类型，通常以整数 `1`、`0` 保存 `TRUE`、`FALSE`，并通过 `CHECK` 约束只允许这两个值。

## `characters`：汉字

这张表给每个收录字一个统一身份。

| id | character |
|---:|---|
| 101 | 吳 |
| 102 | 吴 |
| 103 | 行 |

### `id`

汉字的内部主键。`readings.character_id` 通过它关联到具体汉字。

使用整数主键的好处是：

- 字符文本只在 `characters` 中保存一次；
- `readings` 只保存较小的整数；
- 联合索引更紧凑；
- 以后可以给汉字增加部首、笔画、统一码等资料，而不用改变读音表的关系。

### `character`

实际显示和查询的字符，例如“吳”。建议设置 `UNIQUE`，防止同一个字被重复创建。

该字段必须按 Unicode 文本处理，不能假定一个汉字只占一个字节或一个 UTF-16 code unit。导入程序还应统一 Unicode 规范化方式，以免视觉上相同的文本被存成不同记录。

## `readings`：具体读音

这是核心表。每一行表示：

> 某一个汉字，在某一种方言或资料集中，有一个具体读音。

例如“行”在同一资料中有多个读音时，应保存成多行，而不是把多个读音拼在一个字符串里：

| id | character_id | dialect_id | romanization | ipa | audio | note |
|---:|---:|---:|---|---|---|---|
| 9001 | 103 | 1 | `ghan2` | `ɦã²²³` | NULL | 行走 |
| 9002 | 103 | 1 | `ghan6` | `ɦã²³¹` | NULL | 行业 |
| 9003 | 103 | 3 | NULL | `ɦɑ̃²³` | NULL | 文读 |

### `id`

每条读音的主键。即使两个读音拼写相同，它们仍可因为备注、排序或资料来源不同而成为独立记录。

以后如果要给单条读音添加音频、文献出处、修订历史或审核状态，也可以通过这个 `id` 关联。

### `character_id`

外键，指向 `characters.id`，表示“这是哪个字的读音”。例如 `character_id = 103` 对应“行”。

删除汉字时，应通过外键规则阻止误删，或者明确使用级联删除该字的全部读音。

### `dialect_id`

外键，指向 `dialects.id`，表示“这是哪套方言或资料的读音”。

同一个 `character_id` 可以搭配多个 `dialect_id`，因此一次汉字查询可以列出多套方言结果。

### `romanization`

罗马字或拼音，例如 `tsy1`、`ghan2`，也是拼音反查的主要字段。

只有 IPA 的资料将它设为 `NULL`。`DB_suhu` 中的拼音按原字符串写入数据库，不在导入时改写；查询时再严格复现原 HTML 的小写转换、末尾声调数字识别和指定的 `ou → u` 兼容映射。具体规则见后文“完全按原 HTML 执行的数据规则”。

### `ipa`

保存国际音标。蘇滬混合腔可以同时保存 `romanization` 和 `ipa`；只有音标的资料则主要使用这个字段。

IPA 是 Unicode 文本。如果以后需要按音系顺序排列，应该另存专用排序字段，不能依赖数据库对 IPA 字符串的普通字典排序。

### `audio`

保存这条读音对应的音频文件地址，例如相对路径 `audio/suhu/ghan2.ogg`，或由本地后端提供的地址 `/audio/9001`。

当前尚无音频资料，所以所有记录的 `audio` 都是 `NULL`。使用 `NULL` 可以明确表示“没有音频”，不必用空字符串占位。以后加入音频时，一条读音可以直接关联一个文件地址；如果一条读音需要多个说话人、多个录音版本或更多元数据，则应另建 `reading_audio` 表，而不是在一个字段中拼接多个地址。

为了让离线版本可以移动安装目录，优先保存相对路径或后端资源标识，不建议保存某台电脑上的绝对路径。

### `note`

保存这条读音的补充说明，例如：

- 文读、白读；
- 上海又音；
- 男、女口音差异；
- 使用场景或例词；
- 原始资料备注。

`note` 是展示内容，不宜参与主要读音匹配。无备注时应统一使用 `NULL` 或空字符串中的一种。


## `character_variants`：简体到繁体映射

这张表只负责把用户输入的简体字扩展为要查询的繁体字。系统不通过繁体字反查简体字，也不保存繁体到简体的反向记录。

| source_character | target_character | variant_type |
|---|---|---|
| 吴 | 吳 | `s2t` |
| 发 | 發 | `s2t` |
| 发 | 髮 | `s2t` |

### `source_character`

用户输入的简体字。例如用户输入“发”，“发”就是源字。该列只作为简到繁查询的入口，不用于接受繁体字并寻找简体字。

### `target_character`

实际继续查询的目标字。“发”可以对应“發”和“髮”，因此同一源字可以有多行。程序不能假定简繁转换永远是一对一。

### `variant_type`

当前只允许 `s2t`，表示简体到繁体。保留这个字段可以让数据方向自解释，并防止误导入繁体到简体记录；数据库使用 `CHECK (variant_type = 's2t')` 强制执行该限制。

`S2T` 中目标字与源字相同的项目也保留。查询时通过 `target_character = source_character` 判断它是直接显示，而不是转换标签。

当前方案直接保存字符文本，与原 HTML 的 `S2T` 键和值一致。目标字的返回顺序不作保证。

按源字和目标字增加复合唯一约束：

```sql
UNIQUE (source_character, target_character)
```

它可以防止同一条简到繁映射被重复导入。

## 依据原 HTML 的数据规则

数据库迁移和后端查询以当前 `index.html` 的数据结构与行为为基础。除用户明确要求的“前向查字在同一方言内删除重复读音”外，其余规则均为对现有代码的直接整理。

### 五套资料怎样写入 `readings`

原 HTML 的五套数据按 `DBS` 中的固定顺序处理：

1. `DB_suhu`：蘇滬混合腔；
2. `DB_qingmo`：清末蘇州話；
3. `DB_shanghai`：上海話；
4. `DB_suzhou`：蘇州話；
5. `DB_pingtan`：蘇州評彈音。

其中：

- `DB_suhu` 的每个数组项为 `[romanization, ipa, note]`，分别写入同名字段；
- 其他四套资料的每个数组项为 `[ipa, note]`，写入 `readings.ipa` 和 `readings.note`，`readings.romanization` 为 `NULL`；
- 当前没有音频资料，所有 `readings.audio` 都写成 `NULL`；
- 每个数组项都写成一条独立的 `readings` 记录；
- 方言定义仍按上述 `DBS` 对应关系导入，但查询结果不要求保持数组顺序。

数据库导入仍完整保留原 HTML 数组中的每个项目，不能因为字段相同就在导入阶段删除记录；`id` 是每条原始记录的唯一身份。数据库不保存也不承诺原数组顺序。

前向查字展示时，再以“同一汉字、同一方言”为范围删除重复读音：

- 对蘇滬混合腔，以 `romanization + ipa` 的完全相等作为重复判定；
- 对其他四套只有音标的资料，以 `ipa` 的完全相等作为重复判定；
- `note` 和 `audio` 不参与判重；
- 同一拼音但 IPA 不同，或同一 IPA 但拼音不同，均视为不同读音并保留；
- 去重范围不跨汉字，也不跨方言；
- 每个重复组只生成一个读音结果，不指定由哪条原始记录代表，也不保证结果顺序；
- 同组内不同的非空 `note` 应去重后汇集到该读音结果；将来存在音频时，不同的非空 `audio` 地址也按同样方式汇集。

这个规则只影响前向查字结果，不修改数据库中的原始记录，也不改变拼音反查的分组规则。

### 拼音输入如何标准化

拼音反查只查询 `DB_suhu`，即数据库中的 `suhu` 方言。处理顺序必须与原 HTML 相同：

1. 对用户输入执行首尾空白删除，即 `trim()`；
2. 把输入转成小写，即 `toLowerCase()`；
3. 只有最后一个字符是 `1–9` 时，才把它识别为声调数字；
4. 若识别到声调，先把最后一位数字从声韵部分暂时移除；
5. 仅对下列完整声韵执行兼容转换：

```text
pou→pu      phou→phu    mou→mu      fou→fu      vou→vu
tou→tu      thou→thu    nou→nu      lou→lu
kou→ku      khou→khu    hou→hu      ghou→wu     ngou→ngu
tsou→tsu    tshou→tshu  sou→su      zou→zu
```

6. 如果原输入带声调数字，把该数字重新接到转换后的声韵末尾；
7. 带声调查询时，把处理后的完整拼音与 `readings.romanization` 的小写形式作完全相等比较；
8. 不带声调查询时，只移除每条数据库拼音末尾的一个 `1–9` 数字，再与处理后的输入作完全相等比较。

数据库迁移保留 `DB_suhu` 的原拼音字符串，拼音反查直接执行上述原 HTML 逻辑。

### 拼音反查怎样排序和去重

原 HTML 先收集所有匹配记录，再按完整 `reading` 使用 `localeCompare` 排序，然后按完整拼音字符串分组。数据库或后端应保持下列展示语义：

- 同一完整拼音只显示一个分组；
- 同一分组内，同一个汉字只显示一次；
- 汉字第一次出现的顺序保留；
- 分组的 IPA 取该拼音分组第一次出现的匹配记录；
- `note` 不参与拼音反查结果；
- 这种去重只属于拼音反查的展示层，不删除 `readings` 中的原始记录。

因此，重复处理分为三层：

1. 数据库层不判重，完整保留原 HTML 数组项目；
2. 前向查字层按上面的方言内读音键做集合去重，不指定代表记录或输出顺序；
3. 拼音反查层按原 HTML 规则，只对“同一完整拼音分组中的同一汉字”去重。

### 一简对多繁怎样展开和展示

`S2T` 是唯一的简繁转换资料来源。每个 `S2T[source]` 数组项目都写入 `character_variants`，但不保存数组位置。查询时执行以下规则：

1. 汉字输入先 `trim()`；
2. 使用 JavaScript 展开语义按 Unicode 码点计数，最多允许输入 8 个字；
3. 处理用户输入的每个字，结果顺序不作保证；
4. 整次查询使用同一个 `seen` 集合；已经处理过的输入字跳过；
5. 如果源字存在非空 `S2T` 数组，处理其中全部目标字；
6. 目标字与源字相同，标记为直接显示，不添加“简体对应”标签；
7. 目标字与源字不同且尚未出现，显示该繁体字，并标注“简体「源字」对应”；
8. 同一个目标字若此前已经作为输入字或转换结果出现，则不再生成第二张字卡；
9. 如果源字没有 `S2T` 项或对应数组为空，则直接查询并显示源字。

一简对多繁时不会选择其中一个“最佳”结果，而是展示全部未重复目标字；目标字顺序可以变化。系统不执行繁体到简体反查。
## 三个索引具体做什么

索引类似数据库维护的“快速目录”。它会占用少量磁盘空间并增加写入成本，但可以避免查询时扫描整张表。本项目读取远多于写入，因此很适合建立索引。

### `INDEX readings(character_id, dialect_id)`

完整写法：

```sql
CREATE INDEX idx_readings_character_dialect
ON readings(character_id, dialect_id);
```

它主要加速“这个字有哪些读音”：

```sql
SELECT *
FROM readings
WHERE character_id = ?;
```

也加速“这个字在指定方言中有哪些读音”：

```sql
SELECT *
FROM readings
WHERE character_id = ? AND dialect_id = ?;
```

联合索引的字段顺序很重要。因为 `character_id` 在前，它可以服务于：

- 只按 `character_id` 查询；
- 同时按 `character_id` 和 `dialect_id` 查询。

它通常不能高效服务于“只按 `dialect_id` 列出整个方言的全部读音”。若该操作很频繁，需要另建以 `dialect_id` 开头的索引。

### `INDEX readings(romanization, dialect_id)`

完整写法：

```sql
CREATE INDEX idx_readings_romanization_dialect
ON readings(romanization, dialect_id);
```

它主要加速拼音反查：

```sql
SELECT c.character, r.romanization, r.ipa, r.note
FROM readings AS r
JOIN characters AS c ON c.id = r.character_id
WHERE r.romanization = ? AND r.dialect_id = ?;
```

这可以代替当前前端逐字、逐读音扫描整套 `DB_suhu` 的方法。

它适合带声调的精确匹配，例如 `ku5`。无声调查询不另造新的拼音规则，而是像原 HTML 一样，仅去掉数据库拼音末尾的一个 `1–9` 数字后进行完全相等比较。

因为 `romanization` 在前，这个索引适合只按拼音查询，或按拼音加方言查询；它不主要用于只按 `dialect_id` 查询。

### `INDEX character_variants(source_character)`

完整写法：

```sql
CREATE INDEX idx_character_variants_source
ON character_variants(source_character);
```

它加速从输入字寻找全部目标字：

```sql
SELECT target_character
FROM character_variants
WHERE source_character = ? AND variant_type = 's2t';
```

例如输入“发”时，可以快速得到“發”“髮”，随后分别查询它们的读音。

该索引只优化简体源字到繁体目标字的方向，正好符合本项目的查询需求。因为不提供繁体到简体反查，所以不需要为 `target_character` 另建反向查询索引。

## 一次汉字查询怎样经过这些表

用户输入“吴”时，后端可以这样处理：

1. 在 `character_variants` 中查询 `source_character = '吴'`，得到“吳”；若没有映射，则直接使用原字。
2. 在 `characters` 中找到“吳”的 `id`。
3. 在 `readings` 中按 `character_id` 查询全部读音，并在每个方言内部按读音键做集合去重。
4. 关联 `dialects`，得到方言代码、显示名称，以及是否支持 IPA、罗马字的两个布尔标记。
5. 将去重后的结果返回前端，不保证方言、读音或字符结果的顺序。

查询某个规范字的示例：

```sql
SELECT
  c.character,
  d.code AS dialect_code,
  d.display_name,
  d.ipa AS supports_ipa,
  d.romanization AS supports_romanization,
  r.romanization,
  r.ipa,
  r.audio,
  r.note
FROM characters AS c
JOIN readings AS r ON r.character_id = c.id
JOIN dialects AS d ON d.id = r.dialect_id
WHERE c.character = ?;
```

## SQLite 建表示例

下面是一份可以实际执行的基础定义。字段对应、空值和重复读音处理遵循上文规则；查询结果顺序不作保证。

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE dialects (
  id           INTEGER PRIMARY KEY,
  code         TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  ipa          INTEGER NOT NULL DEFAULT 0 CHECK (ipa IN (0, 1)),
  romanization INTEGER NOT NULL DEFAULT 0 CHECK (romanization IN (0, 1))
);

CREATE TABLE characters (
  id        INTEGER PRIMARY KEY,
  character TEXT NOT NULL UNIQUE
);

CREATE TABLE readings (
  id             INTEGER PRIMARY KEY,
  character_id   INTEGER NOT NULL,
  dialect_id     INTEGER NOT NULL,
  romanization   TEXT,
  ipa            TEXT,
  audio          TEXT DEFAULT NULL,
  note           TEXT,
  FOREIGN KEY (character_id) REFERENCES characters(id),
  FOREIGN KEY (dialect_id) REFERENCES dialects(id)
);

CREATE TABLE character_variants (
  source_character TEXT NOT NULL,
  target_character TEXT NOT NULL,
  variant_type     TEXT NOT NULL DEFAULT 's2t' CHECK (variant_type = 's2t'),
  UNIQUE (source_character, target_character)
);

CREATE INDEX idx_readings_character_dialect
ON readings(character_id, dialect_id);

CREATE INDEX idx_readings_romanization_dialect
ON readings(romanization, dialect_id);

CREATE INDEX idx_character_variants_source
ON character_variants(source_character);
```

数据导入与查询以当前 `index.html` 为准：数据库保留原始读音项目，但不保存原数组顺序；前向查字按本文规则在同一方言内合并重复读音，查询结果允许任意顺序；拼音和一简对多繁按现有规则处理，不从外部资料补充或纠正数据。音频资料加入以前，所有 `readings.audio` 均保持为 `NULL`。
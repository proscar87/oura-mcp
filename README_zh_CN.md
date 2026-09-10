# oura-mcp

[![PyPI](https://img.shields.io/pypi/v/mcp-oura?label=PyPI)](https://pypi.org/project/mcp-oura/)
[![Glama score](https://glama.ai/mcp/servers/proscar87/oura-mcp/badges/score.svg)](https://glama.ai/mcp/servers/proscar87/oura-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](https://github.com/proscar87/oura-mcp/blob/main/README.md) | 简体中文 | [한국어](https://github.com/proscar87/oura-mcp/blob/main/README_ko.md) | [Español](https://github.com/proscar87/oura-mcp/blob/main/README_es.md)

<!-- Glama 徽章是实时的，不是截图：它显示那个独立索引今天给这个服务器打的分。
     一个只会往上走的徽章是装饰；一个可能掉下去的徽章才是证据。 -->

把 [Oura](https://ouraring.com) v2 API 做成 [MCP](https://modelcontextprotocol.io)
服务器。全部 19 个集合，四个工具，除了 MCP SDK 之外没有任何依赖。

### 一个本地日的心率数据是 1,231 个采样点，分布在 2 页里

不跟进 Oura `next_token` 的客户端只会拿到其中的 **1,000 个 —— 81%，看上去很完整，
而且没有任何东西提示你不完整。** 这是 2026 年 8 月 9 日对着真实 API 测出来的：
一个人，一枚戒指，24 小时。

**可以拿来检验任何 Oura MCP 服务器的标准，包括这一个：** 它是否把 `next_token`
—— 或者 `cursor`、`limit` —— 当作工具参数暴露出去？如果是，那分页就成了模型的活儿，
而一个忘了继续追问的模型，会基于残缺的数据给出一个自信满满的答案。这个服务器会先把
分页取尽再返回，并告诉你一共翻了多少页。

这只是 Oura 在不声不响中少给你东西的**四**种方式之一。四种下面都有测量数据，
四种在这里都已修正。

### 安装

从[最新发布](https://github.com/proscar87/oura-mcp/releases/latest)下载
**`oura-mcp.mcpb`** 并双击。剩下的交给 Claude Desktop —— 不需要终端，不需要
Python，不需要 Node。它开箱即用地跑在 Oura 官方的示例数据上，而且每一条示例响应都
会声明这一点，所以没有任何东西能冒充你自己的睡眠数据。

更喜欢命令行？`uvx --from mcp-oura oura-mcp`。

根本不想在机器上装 Python？

```
docker run -i --rm -e OURA_SANDBOX=1 ghcr.io/proscar87/oura-mcp
```

`-i` 不是可选项：MCP 服务器通过 stdin 和 stdout 通信，而不是通过端口。少了它，
容器就没有 stdin，握手永远不会到达，客户端只会报告说服务器没起来。

---

## 被测量出来的问题

当 Oura 给不了你要的东西时，它不会返回错误。它会返回另一样东西，形状看起来像一个
正确的响应。以下是 2026 年 8 月 9 日对着真实 API 测量时发现的四个：

### 1. 跳过分页，你拿到的只是一部分

```json
{ "data": [ ... ], "next_token": "eyJ0eXAiOi..." }
```

如果 `next_token` 回来了而你不去跟进，你收到的就是第一页，而且**没有任何警告**。
一个本地日的 `heartrate` —— 一个人，一枚戒指，24 小时 —— 是 **1,231 个采样点，
分布在 2 页里**。不分页的客户端拿到 1,231 里的 1,000 个：81%，看上去很完整。
一个月大约是 ~37,000 条。

### 2. 只请求一天，返回了零条记录

`end_date` **在各个集合之间行为并不一致**：

| 排除请求的最后一天 | 包含最后一天 |
|---|---|
| `daily_activity`, `sleep`, `workout` | `daily_sleep`, `daily_readiness`, `daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`, `sleep_time` |

除此之外，**`workout` 按 UTC 日期过滤，却按本地时间报告 `day`**：在 `-06:00` 下，
请求 7 月 16 日至 18 日返回了 15 日和 16 日的记录 —— 比请求的起始日还要*早*。

在这里，区间永远是两端都包含的。实现上会在两侧各多请求两天，然后再裁掉，
这样无论某个集合是哪种行为都是正确的 —— 而且在 Oura 改变行为之后依然正确。

### 3. `latest=true` 在不适用的地方被无视

只有 `heartrate` 和 `ring_battery_level` 会遵守它。在另外十七个集合里，Oura 不报错：
它**把整个集合返回给你**。你要的是最新的一条记录，拿到的是十条，而你以为那是一条。
在这里，这种请求在发出去之前就被拒绝了。

### 4. 不存在的字段会被静默忽略

`fields=does_not_exist` 返回的是**完整的**记录 —— 投影根本没有发生 ——
而 `fields=score,does_not_exist` 会应用好的那个、丢掉坏的那个，一声不吭。
在这里，从未出现过的字段会在 `ignored_fields` 里报告出来。

**模式永远是同一个：**你要一样东西，拿到的是另一样，而且没有任何警告。
这正是为什么这个包宁可大声嚷嚷，也不愿意悄悄地少给你东西。

## 安装

### 不用凭据先试试

```bash
pip install mcp-oura
OURA_SANDBOX=1 oura-mcp --check
```

这个沙箱是官方的 —— 它写在 Oura 的 OpenAPI 规范里，有 34 条镜像路由 ——
并且无需认证就提供合成数据。19 个集合里有 18 个在那儿能用：`personal_info` 不行，
这也说得通，因为它正是返回邮箱、年龄、体重和身高的那一个。

顺序应该是这样的：先看着服务器跑起来、摸清数据的形状，然后再去拿凭据。

### 用你自己的数据

**Oura 已于 2025 年 12 月停止发放 Personal Access Token。** 已有的仍然可用，
新的创建不了了。所以有两条路：

**a) OAuth2 —— 今天真正能走通的那条。** 在
[cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications)
注册一个应用，redirect 填 `http://localhost:9876/callback/` —— **末尾的斜杠是必须的**，
门户会用 `invalid_redirect_uri` 拒掉另一种写法。

> **如果你是在 `developer.ouraring.com` 上注册的**，那你的应用属于 Oura 更新的那个
> 门户，它的 token 端点是另一个。旧端点会在**每一次**刷新时拒绝这些应用 ——
> 于是这次注册恰好只能用一次，用到第一个 access token 过期为止，之后就永远失败，
> 而且没有任何东西解释原因。这个服务器会先试旧端点，再自动回退到新端点；
> 两种情况都不需要你配置什么。


```bash
export OURA_CLIENT_ID="…"
export OURA_CLIENT_SECRET="…"
oura-mcp --authorize             # opens the browser, waits for the callback
oura-mcp --authorize --manual    # headless machines: you paste the URL back
```

token 以 600 权限存放在 `~/.config/oura-mcp/credenciales.json` —— 或者，如果你碰巧
装了 `keyring`（它并不是这个包的依赖），就存在系统钥匙串里 —— 并且会自动刷新。
`oura-mcp --forget` 可以把它抹掉。

**b) 个人 token，如果你本来就有一个的话。**

```bash
export OURA_PAT="your-token"
oura-mcp --check
```

`--check` 是自检：它会报告你正在用哪种凭据、被授予了哪些 scope、访问权限还剩多久，
**既不返回 token，也不返回任何一个健康数值**。它报告 token 的长度，从不报告 token
本身。错误信息会被复制粘贴到聊天和 issue 里；它们没理由携带别的东西。

### 接到 Claude Code 上

装好包之后（`pip install mcp-oura`）：

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- oura-mcp
```

跑过 `oura-mcp --authorize` 之后，把 `OURA_SANDBOX` 去掉。

**如果你用 [uv](https://docs.astral.sh/uv/)**，就什么都不用永久安装：

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- uvx --from mcp-oura oura-mcp
```

`--from` 是必须的，因为发行包叫 `mcp-oura`，而可执行文件叫 `oura-mcp`。
*（这需要 `uv`；没有它，上面这条命令会以 “command not found” 失败，
那时该走的路是 `pip install`。）*

作为 Claude Code 插件：

```bash
claude plugin marketplace add proscar87/oura-mcp
claude plugin install oura@oura-mcp
```

### 接到 Claude Desktop 上

**一次点击：**从[发布页](https://github.com/proscar87/oura-mcp/releases)下载
`oura-mcp.mcpb` 并双击。Claude Desktop 会把它装上 —— 不需要终端，不需要 JSON，
不需要 Python。它默认开启示例数据，所以在你还没有任何凭据之前就能用。

等你想看自己的数据时，直接开口要就行：它会通过 Claude 打开 Oura 的授权页面，
等待回调，然后重试你刚才的请求。不需要终端。这之所以行得通，是因为 MCP 正好有一个
为此设计的模式 —— URL elicitation —— 而打开页面的是客户端。

Oura 唯一仍然要求的，是每个应用都必须注册，所以你需要去
[cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications)
拿一次 client ID 和 secret。那是 Oura 的规矩，不是这个服务器的。
`oura-mcp --authorize` 仍然保留，给用终端的人，也给那些无法展示 URL 的客户端。

**或者手动配置，**在 `~/Library/Application Support/Claude/claude_desktop_config.json` 里：

```json
{
  "mcpServers": {
    "oura": {
      "command": "/full/path/to/oura-mcp",
      "env": { "OURA_SANDBOX": "1" }
    }
  }
}
```

`which oura-mcp` 会给你完整路径。Claude Desktop 不会继承你终端的 `PATH`，
所以在那里只写一个裸名字会静默失败 —— 这是配置 MCP 服务器时最常见的错误之一。

## 这些工具

| | |
|---|---|
| `oura_collections` | 全部 19 个，每一个装的是什么，各自接受哪些参数 |
| `oura_query` | 在一个区间上完整取出一个集合，一直分页到最后 |
| `oura_today` | 昨晚的睡眠和今天的准备度，连同它们之前的那些天 |
| `oura_check` | 什么都不暴露的自检 |

**四个，不是十九个。**一个集合配一个工具的服务器，会逼着模型在还不知道任何一个装了
什么之前，先从 19 个相似的名字里挑一个。在这里，集合是一个参数，需要时再去查目录。

四个工具都声明自己是只读的，而这不只是一句承诺：整个包里没有任何 `POST`、`PUT`
或 `DELETE`，并且有一个测试会去读源码，保证它一直如此。

`oura_today` 是唯一一个为了方便、而不是为了正确性而存在的工具：「我睡得怎么样？」
这个问题需要今天的两条记录，外加足够多的历史数据来判断它们是否反常，
而这以前是四次往返、四次半途而废的机会。**它不做任何计算** —— 没有平均值，
没有差值，也没有「你的 HRV 上升了 12%」。那些天的数据原样返回，
比较发生在能够引用方法的地方。在九年的真实数据上，连续两次测量之间的变化
有四分之三落在该指标自身的正常波动范围内，所以一个不带这层背景的百分比
是在制造信号，而不是在报告信号。它只有一个参数 `days`，取值 1 到 30，默认为 7。

### `oura_query` 的参数

| | |
|---|---|
| `collection` | 19 个中的哪一个。`oura_collections` 会列出它们 |
| `day` | 单独一天。等价于 `start=end=day` 的简写 |
| `start`, `end` | 区间，**两端都包含** |
| `fields` | 只要这些字段。Oura 会在它那边先裁掉，所以传下来的更少 |
| `latest` | 最新的一条记录。仅限 `heartrate` 和 `ring_battery_level` |
| `format` | `json` 或 `csv`。节省的比例因集合而异：`heartrate` 上 55%，`daily_sleep` 上 10% |

以及当结果不干净时，响应会告诉你的东西：
`truncated` 会带上 `continue_from`，指出走到的最后一天；`pagination_cycle` 表示
Oura 重复了某个 token；还有 `ignored_fields`、`discarded_out_of_range`、
`uneven_columns`、查询结果为空时的 `empty`，以及返回内容重到值得一提时的
`large_response`。

另外四个，会告诉你一些否则你永远不会知道的事：

- **`synthetic`** —— 这是 Oura 的示例数据，不是你的。在示例模式下它会挂在每一条响应
  上，而扩展正是以这种模式分发的，所以模型不可能把编出来的数字当成你的睡眠报告出去。
- **`rate_limited`** —— Oura 用 429 拒绝过一次，重试成功了。**数据是完整的**；
  这个警告说的是*下一次*查询。Oura 在成功的响应里不发任何限流响应头，
  所以被拒绝是你唯一能得到的、说明自己已经接近上限的信号。
- **`fields_split`** —— `fields` 传过来的是 `"day,score"` 而不是
  `["day","score"]`，于是被切分了。Oura 的字段名里没有逗号，所以切分不存在歧义 ——
  但悄悄地重新解释你的输入，正是这整个包所反对的同一种错。
- **`cached`** —— 答案来自本次会话的内存，而不是来自 Oura。只有在区间结束于**今天之前**
  时才会这样，因为已经过完的一天不可能再多出记录；今天的数据从不缓存，
  因为戒指想什么时候同步就什么时候同步。空的答案也从不缓存 ——
  没有任何东西能把“没有数据”和“戒指还没同步”区分开，而把后者冻住，
  会把一个临时的缺口变成一个永久的缺口。它活在内存里，随进程一起消失：
  **任何健康数据都不会被写到磁盘上。**

最后这一条来自测量：**30 天的 `daily_activity` 是 252,000 个字符**，其中 87%
是单独一个字段 `met`，一条按分钟计的 MET 序列。用 `fields` 只要三列，
同样这 30 天就降到 5,000 个字符 —— **少了 99%**。服务器不会自作主张去裁剪 ——
那才是少给你东西 —— 但它会告诉你什么很重，以及怎么少要一点。

*（参数名是稳定的，在这里有文档，模型读到的工具描述也带着同样的信息。
它们在 0.2.0 之前一直是西班牙语；改成英文是在 0.3.0 落地的，
并作为一次破坏性变更记录在 CHANGELOG 里。）*

## 这个服务器不做的事

**它不做分析。**没有相关性，没有异常检测，没有周期对比 ——
而那恰恰是别的服务器安放自身价值的地方。

理由是：在这里算出来的一个平均值，抵达模型时只是一个数字，方法留在了外面。
在九年的真实数据上，**两次连续测量之间的变化，有四分之三落在该指标自身的正常波动
范围内**。一个直接甩给你“你的 HRV 上升了 12%”、却不说这个指标本身会晃多大的服务器，
不是在告诉你信息：它是在制造信号。

在这里你拿到的是数据。分析应该放在能够引用方法的地方 —— 比如
[cotejo](https://github.com/proscar87/cotejo)，它对血液生物标志物做的正是这个区分。

## 19 个集合

**每日汇总** —— `daily_sleep`、`daily_readiness`、`daily_activity`、
`daily_stress`、`daily_spo2`、`daily_resilience`、`daily_cardiovascular_age`、
`vO2_max`

**评分掩盖掉的细节** —— `sleep`（睡眠阶段、HRV、体温、入睡潜伏期）、
`sleep_time`、`workout`、`session`、`rest_mode_period`、`tag`、`enhanced_tag`

**高分辨率** —— `heartrate`、`ring_battery_level`

**没有区间** —— `personal_info`、`ring_configuration`

按日期区间查询的集合使用 `YYYY-MM-DD`。`heartrate` 和 `ring_battery_level`
使用带时间的 ISO 8601。

## 其他 Oura MCP 服务器

截至 2026 年 8 月已经有好几个了，把差别说清楚是值得的。
[`benngermin/oura-mcp`](https://github.com/benngermin/oura-mcp)**分页做得对**，
带一个可续取的游标。[`daveremy/oura-mcp`](https://github.com/daveremy/oura-mcp)
和我们在同一周发布了 `end_date` 的修复。
[`davidmosiah/oura-mcp`](https://github.com/davidmosiah/oura-mcp) 的 MCP 接口面
最完整。分页已经不再是谁的区分点了。

真正还构成区别的，就我们能核实的范围而言：**`workout` 的 UTC 偏移在它们任何一个里
都没有文档**，在 Oura 会无视 `latest` 的地方拒绝它也没有，对从未被应用的字段发出警告
也没有。而且它们没有一个把“不做分析”当作一种明确表态。

## 隐私政策

这一节之所以存在，是因为 Claude 的连接器目录要求有一节。它很短，
是因为实在没什么可写：服务器跑在你自己的机器上，只和一个服务说话，就是 Oura API。

**收集了什么。**我们这边什么都没收集。你请求的健康数据从 Oura API
直接到你的 MCP 客户端，不经过我们的任何服务器，因为我们根本没有服务器。

**存了什么，存在哪儿。**只有你的凭据，而且只存在你自己的机器上：

| | |
|---|---|
| OAuth2 token | `~/.config/oura-mcp/credenciales.json`，权限 `600` —— 或者，如果你装了 `keyring`，就在系统钥匙串里 |
| 个人 token | 你放在哪儿就在哪儿：`OURA_PAT`，或者 `OURA_PAT_FILE` 指向的那个文件 |

健康数据不会被写到磁盘上，而这正是缓存在设计时就绕着走的那条约束，
不是事后补上的一句声明。已经过完的那一天的答案**只保存在内存里**，
活不过进程本身，`--forget` 会把它们清掉。关于你睡眠的任何东西，
都不会在服务器退出之后留下来。

**分享给了谁。**没有任何人。唯一的外发连接是到 `api.ouraring.com`，
带上你的 token，去取你要的东西。Oura 如何使用你的数据，
由[它们的隐私政策](https://ouraring.com/privacy-policy)约束，而不是这一份。

**保留多久。**凭据保留到你删掉为止：`oura-mcp --forget`，或者直接删文件。
健康数据根本不保留 —— 它活在那一次响应里，仅此而已。

**诊断什么都不暴露。**`oura_check` 报告 token 的长度，从不报告 token 本身；
报告个人资料的字段名，从不报告它们的值。token 被包在一个类型里，
连出现在堆栈跟踪里时也不会被打印出来。

**联系方式。**[仓库 issues](https://github.com/proscar87/oura-mcp/issues)。

## 关于语言的一点说明

这个仓库是英文的：代码、代码里的注释、测试，以及内部文档（`AGENTS.md`、
`ROADMAP.md`、`CHANGELOG.md`）。你现在读的这一份，是那个英文 README 的译本。

在 0.2.0 之前，它是用西班牙语写的。工具参数在 0.3.0 里被改名 ——
一次破坏性变更，并且在 CHANGELOG 里就是这么记录的 —— 文字部分随后跟上。
现在还留着西班牙语的，都是些存储用的键名：改掉它们，就会让别人已经存好的凭据
变成孤儿，而且有一个测试点着名字把这件事说了出来。

## 许可证

MIT。

---

*本译文由机器辅助翻译。如果发现有翻译错误或不通顺的地方，欢迎通过 pull request
提交修正：[仓库 issues](https://github.com/proscar87/oura-mcp/issues)。*

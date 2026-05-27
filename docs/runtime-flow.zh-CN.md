# FanboxMonitor 运行流程与表结构

本文说明一次 `main.py` 运行时的主要流程、异常处理策略，以及 SQLite 表结构。

## 运行流程

1. 加载配置：从环境变量和 `.env` 读取 `Settings`，包括 Fanbox cookie、下载目录、数据库路径、抓取模式、限速、并发、过滤规则和通知配置。
2. 初始化运行环境：设置日志，创建下载目录，打开 SQLite 数据库并确保表结构存在。
3. 创建 Fanbox API 客户端：使用 `FANBOX_SESSION`、User-Agent、代理和请求间隔访问 Fanbox API。
4. 选择抓取来源：
   - `FANBOX_MODE_SUPPORTING=1` 时抓取赞助流。
   - `FANBOX_MODE_FOLLOWING=1` 时抓取关注流。
5. 遍历新投稿：
   - 已在 `seen_posts` 中的投稿直接跳过。
   - 对未见投稿先做价格、日期、tag、creator 规则过滤。
   - 过滤不通过的投稿会写入 `seen_posts`，避免下次重复评估。
6. 拉取投稿详情：对通过早期过滤的投稿调用 `post.info`。
7. 解析文件：把投稿详情解析成可下载的 `FileItem`，并按扩展名白名单过滤。
8. 提交下载：未在 `downloaded` 中登记的文件会进入线程池下载。
9. 收尾下载结果：
   - 成功下载或磁盘已有文件会写入 `downloaded`。
   - 投稿内所有待下载文件都成功、已存在或已登记时，才写入 `seen_posts`。
   - 只要投稿内有文件失败，该投稿不会写入 `seen_posts`，留待下次运行重试。
10. 写运行日志：把本次新增投稿数、新增文件数、错误数和摘要写入 `run_log`。
11. 发送通知：达到通知阈值或出现错误时，发送青龙 notify / Bark 通知。
12. 返回退出码：
    - `0`：无错误。
    - `1`：有普通错误。
    - `2`：Fanbox cookie 认证失败。

## 情况处理

| 情况 | 处理方式 | 是否写入 `seen_posts` | 下次是否重试 |
| --- | --- | --- | --- |
| 投稿已经在 `seen_posts` | 直接跳过 | 已经存在 | 否 |
| 价格、日期、tag、creator 规则过滤不通过 | 跳过并记录为已处理 | 是 | 否 |
| `post.info` 返回 403 且重试后仍失败 | 认为无权限或限定内容，跳过 | 是 | 否 |
| `post.info` 网络错误、5xx、JSON 错误等临时失败 | 记录错误，保留投稿 | 否 | 是 |
| 投稿没有可下载文件 | 视为已处理 | 是 | 否 |
| 文件 URL 已在 `downloaded` | 跳过该文件 | 取决于投稿整体结果 | 否 |
| 目标文件已存在但 DB 未登记 | 补写 `downloaded` | 取决于投稿整体结果 | 否 |
| 文件下载成功 | 写入 `downloaded` | 若投稿内所有文件均成功则是 | 否 |
| 文件下载失败 | 记录错误，投稿保留 | 否 | 是 |
| supporting / following 首页或分页失败 | 向上抛出，让本次 run 失败 | 已成功完成的投稿按下载结果处理 | 是 |
| Fanbox 401 | 认为 cookie 失效，发送认证失败通知，退出码 `2` | 否 | 修复 cookie 后重试 |
| Fanbox 429 | 触发限流退避并提前结束本次 run | 否 | 是 |

## 下载策略

下载器使用 `.part` 临时文件保存未完成内容：

- 目标文件已经存在时，直接返回成功，主流程会补写 `downloaded`。
- 下载中断时保留 `.part`。
- 下次重试时使用 HTTP `Range` 断点续传。
- 下载完成后用 `.part` 原子替换目标文件。
- 403/404 时，如果存在 `retry_url`，会降级下载备用 URL。
- 5xx 会退避重试，最多重试 10 次。

## 单帖下载脚本

`download_post.py` 用于按 Fanbox 投稿 URL 或纯 post id 单独下载某个投稿，不需要等待定时监控扫描到该投稿。

示例：

```bash
python download_post.py https://www.fanbox.cc/@creator/posts/123456
python download_post.py https://creator.fanbox.cc/posts/123456
python download_post.py 123456
```

默认行为：

- 复用 `.env` / 环境变量中的 `FANBOX_SESSION`、下载目录、数据库路径、命名规则、扩展名白名单和代理配置。
- 调用 `post.info` 拉取该投稿详情。
- 只下载通过扩展名白名单的真实文件。
- 下载成功或目标文件已存在时，写入 `downloaded`。
- 默认不写入 `seen_posts`，避免手动下载影响定时监控的增量状态。

可选参数：

| 参数 | 含义 |
| --- | --- |
| `--force` | 忽略 `downloaded` 表记录，尝试重新下载；如果目标文件已存在，下载器仍会跳过并补登记。 |
| `--mark-seen` | 下载无错误时把该投稿写入 `seen_posts`。适合明确不希望定时任务以后再处理该投稿的场景。 |

## SQLite 表结构

### `seen_posts`

记录已经处理完成或明确跳过的投稿。进入此表的投稿，下次运行不会再次处理。

| 字段 | 类型 | 约束 | 含义 |
| --- | --- | --- | --- |
| `post_id` | `TEXT` | `PRIMARY KEY` | Fanbox 投稿 ID |
| `creator_id` | `TEXT` | `NOT NULL` | 创作者 ID |
| `published_dt` | `TEXT` | `NOT NULL` | 投稿发布时间 |
| `fee` | `INTEGER` | `NOT NULL` | 投稿所需费用 |
| `title` | `TEXT` | 可空 | 投稿标题 |
| `first_seen_at` | `INTEGER` | `NOT NULL` | 首次标记为 seen 的 Unix 时间戳 |

索引：

| 索引 | 字段 | 用途 |
| --- | --- | --- |
| `idx_seen_creator_dt` | `creator_id, published_dt DESC` | 按创作者和发布时间查询已见投稿 |

### `downloaded`

记录已成功下载或已在磁盘存在并完成补登记的文件。

| 字段 | 类型 | 约束 | 含义 |
| --- | --- | --- | --- |
| `url` | `TEXT` | `PRIMARY KEY` | 文件 URL，也是文件级去重键 |
| `post_id` | `TEXT` | `NOT NULL` | 所属投稿 ID |
| `local_path` | `TEXT` | `NOT NULL` | 本地保存路径 |
| `size` | `INTEGER` | 可空 | 文件大小，无法获取时为空 |
| `downloaded_at` | `INTEGER` | `NOT NULL` | 下载或补登记的 Unix 时间戳 |

索引：

| 索引 | 字段 | 用途 |
| --- | --- | --- |
| `idx_dl_post` | `post_id` | 按投稿查询已下载文件 |

### `cursor`

记录每个抓取范围最近扫描到的 checkpoint。目前主要用于观测和后续扩展，实际增量去重以 `seen_posts` 为主。

| 字段 | 类型 | 约束 | 含义 |
| --- | --- | --- | --- |
| `scope` | `TEXT` | `PRIMARY KEY` | 抓取范围，例如 `supporting` 或 `following:{creator_id}` |
| `max_published_dt` | `TEXT` | 可空 | 最近扫描到的最大发布时间 |
| `max_id` | `TEXT` | 可空 | 最近扫描到的投稿 ID |
| `updated_at` | `INTEGER` | `NOT NULL` | cursor 更新时间戳 |

### `run_log`

记录每次运行的摘要。

| 字段 | 类型 | 约束 | 含义 |
| --- | --- | --- | --- |
| `run_id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | 运行日志 ID |
| `started_at` | `INTEGER` | `NOT NULL` | 本次运行开始 Unix 时间戳 |
| `ended_at` | `INTEGER` | `NOT NULL` | 本次运行结束 Unix 时间戳 |
| `new_posts` | `INTEGER` | `NOT NULL DEFAULT 0` | 本次发现并处理的新增投稿数 |
| `new_files` | `INTEGER` | `NOT NULL DEFAULT 0` | 本次新增下载文件数 |
| `errors` | `INTEGER` | `NOT NULL DEFAULT 0` | 本次错误数 |
| `summary` | `TEXT` | 可空 | 通知和日志使用的运行摘要 |

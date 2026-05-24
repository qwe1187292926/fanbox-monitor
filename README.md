# FanboxMonitor

Pixiv Fanbox 自动监控下载器，部署在青龙面板（Qinglong）作为定时任务，自动检测关注/赞助的创作者的新投稿并下载，运行结束后通过青龙 notify 通道推送汇总。

源项目 [PixivFanboxDownloader](../PixivFanboxDownloader) 是 Chrome 扩展，本项目把核心抓取-过滤-下载逻辑移植成 Python 服务端版本。

## 特性

- 关注（Following）+ 赞助（Supporting）两种来源独立开关
- per-creator 最小金额阈值（例如 A 创作者低于 ¥2000 的投稿不下载）
- 全局过滤：扩展名白名单、费用区间、日期范围
- SQLite 三表持久化：去重、增量游标、运行日志
- 失败自动重试 + retry_url（缩略图）降级
- 429 限流时长退避（5-6 分钟）
- 青龙 notify 多渠道推送（Telegram/Bark/微信/PushPlus 等）
- 使用 `curl_cffi` chrome 指纹绕过 fanbox 反爬

## 部署到青龙

1. 把项目放到 `/ql/data/FanboxMonitor`（或者用青龙的"订阅管理"拉取仓库）
2. 在青龙的"环境变量"里配置 `FANBOX_*` 变量（参考 `.env.example`）
3. 关键变量：`FANBOX_SESSION`（必填，浏览器登录后 F12 复制 FANBOXSESSID cookie 值）
4. 可选：`config/creators.yaml`（参考 `creators.yaml.example`）放 per-creator 规则
5. 在青龙的"定时任务"里添加：
   ```
   命令: python3 /ql/data/FanboxMonitor/main.py
   定时规则: 0 */6 * * *     # 每 6 小时
   ```
6. 首次运行手动触发，看日志确认 cookie 有效

## 本地调试

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env       # 编辑填上 FANBOX_SESSION
cp config/creators.yaml.example config/creators.yaml

python main.py
```

## 目录结构

```
api/             FanboxClient + 端点 wrapper + 异常
crawler/         supporting / following 流编排、限速、增量游标
parser/          PostBody → FileItem，文件名渲染，过滤
downloader/      实际 HTTP 下载（curl_cffi）+ 重试 + retry_url
storage/         SQLite schema + CRUD
notify/          青龙 notify 桥接
models/          TypedDict 类型定义
config/          per-creator 规则
data/            SQLite 数据库与下载文件（运行时生成）
main.py          入口
```

## 配置参考

完整环境变量见 [`.env.example`](.env.example)。per-creator 规则见 [`config/creators.yaml.example`](config/creators.yaml.example)。

## 实现说明

详细架构与设计决策参见 plan 文件（项目外部）。
关键源码对照：从 `../PixivFanboxDownloader/src/ts/` 的 `API.ts`、`SaveData.ts`、`FileName.ts`、`Filter.ts`、`CrawlInterval.ts`、`InitHomePage.ts`、`DownloadControl.ts`、`download/DownloadRecord.ts` 移植而来。
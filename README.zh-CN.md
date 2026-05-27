# FanboxMonitor

<div align="center">

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Qinglong%20Panel-orange.svg)
![Last Commit](https://img.shields.io/github/last-commit/qwe1187292926/fanbox-monitor.svg)
![Issues](https://img.shields.io/github/issues/qwe1187292926/fanbox-monitor.svg)
![Stars](https://img.shields.io/github/stars/qwe1187292926/fanbox-monitor.svg?style=social)

**Pixiv Fanbox 自动化监控下载器**

[English](README.md) | [中文](README.zh-CN.md) | [日本語](README.ja-JP.md)

</div>

---

### If it helpful, please give me a star ~ ⭐

---

## 📖 项目简介

FanboxMonitor 是一款生产级的 Pixiv Fanbox 内容自动化监控与下载解决方案。作为基于 Python 的服务端应用，它与青龙面板无缝集成，通过定时任务自动检测并下载已关注和赞助的创作者的新投稿内容。

本项目完整移植了 Chrome 扩展 [PixivFanboxDownloader](../PixivFanboxDownloader) 的核心抓取、过滤和下载逻辑，针对无头服务器部署进行了优化，具备企业级的可靠性和稳定性。

## ✨ 核心特性

- **双源监控**：关注（Following）和赞助（Supporting）创作者流独立开关控制
- **创作者级别阈值**：可配置的最小金额过滤（例如：跳过特定创作者低于 ¥2000 的投稿）
- **高级过滤系统**：扩展名白名单、价格区间过滤、日期范围约束
- **SQLite 持久化**：记录已处理投稿、已下载文件、扫描 checkpoint 和执行日志
- **智能重试机制**：自动重试配合 `retry_url` 降级策略处理缩略图失效
- **限流处理**：429 响应智能退避策略（5-6 分钟），避免 IP 封禁
- **多渠道通知**：集成青龙 notify，支持 Telegram、Bark、微信、PushPlus 等推送渠道
- **反检测能力**：使用 `curl_cffi` 模拟 Chrome 指纹，绕过 Fanbox 反爬机制

## 🚀 快速开始

### 前置要求

- Python 3.9 或更高版本
- 青龙面板（生产环境推荐）
- 拥有活跃订阅的 Pixiv Fanbox 账号

### 青龙面板部署

#### 步骤 1：仓库设置

将代码克隆到青龙服务器：

```bash
# 方式 A：手动部署
cd /ql/data
git clone https://github.com/qwe1187292926/fanbox-monitor.git

# 方式 B：使用青龙订阅管理
# 在青龙面板 → 订阅管理中添加仓库 URL
```

#### 步骤 2：环境变量配置

进入青龙面板 → 环境变量，配置以下变量（参考 [`.env.example`](.env.example)）：

**必需变量：**
- `FANBOX_SESSION`：Fanbox 会话 Cookie（提取方法见下方说明）

**可选变量：**
- `FANBOX_DOWNLOAD_DIR`：下载目录（默认：`./data`）
- `FANBOX_LOG_LEVEL`：日志级别（默认：`INFO`）
- 其他变量详见 `.env.example`

**如何提取 FANBOX_SESSION：**
1. 在 Chrome/Firefox 浏览器中登录 [Pixiv Fanbox](https://www.fanbox.cc/)
2. 按 `F12` 打开开发者工具
3. 切换到 **Application** 标签 → **Cookies** → `https://www.fanbox.cc`
4. 复制 `FANBOXSESSID` cookie 的值
5. 将此值粘贴到青龙环境变量中的 `FANBOX_SESSION`

#### 步骤 3：创作者配置（可选）

复制并编辑创作者专属配置文件：

```bash
cp config/creators.yaml.example config/creators.yaml
```

编辑 [`config/creators.yaml`](config/creators.yaml) 设置每个创作者的阈值和过滤规则（语法参考 [`creators.yaml.example`](config/creators.yaml.example)）。

#### 步骤 4：创建定时任务

在青龙面板 → 定时任务中创建新任务：

- **命令**：`python3 /ql/data/FanboxMonitor/main.py`
- **定时规则**：`0 */6 * * *`（每 6 小时执行一次）
- **任务名称**：`FanboxMonitor`（或自定义名称）

#### 步骤 5：首次运行与验证

手动触发任务进行首次运行，并监控日志输出：

```bash
# 手动执行
python3 /ql/data/FanboxMonitor/main.py

# 在青龙面板 → 定时任务 → 日志中查看执行结果
```

验证以下内容：
- ✅ 会话认证成功
- ✅ 检测到创作者投稿
- ✅ 文件下载到指定目录
- ✅ 完成后发送通知

---

### 本地开发与调试

用于本地测试和开发：

```bash
# 1. 创建虚拟环境
python3 -m venv venv

# 2. 激活虚拟环境
# Linux/macOS：
source venv/bin/activate
# Windows：
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境
cp .env.example .env
# 编辑 .env 文件，填入 FANBOX_SESSION

cp config/creators.yaml.example config/creators.yaml

# 5. 运行应用
python main.py
```

**调试技巧：**
- 设置 `FANBOX_LOG_LEVEL=DEBUG` 启用详细日志
- 检查 `data/Fanbox.db` 查看 SQLite 数据库内容
- 在青龙设置中审查通知渠道配置

## 📁 项目结构

```
FanboxMonitor/
├── api/                  # Fanbox API 客户端、端点封装、异常处理
│   ├── client.py         # 集成 curl_cffi 的 HTTP 客户端
│   ├── endpoints.py      # API 端点定义
│   └── exceptions.py     # 自定义异常类
├── crawler/              # 赞助/关注流的爬取编排
│   ├── following.py      # 关注创作者爬虫
│   ├── supporting.py     # 赞助创作者爬虫
│   ├── incremental.py    # 增量爬取逻辑
│   └── interval.py       # 速率限制和间隔管理
├── parser/               # 帖子解析、文件名生成、过滤
│   ├── post_parser.py    # PostBody → FileItem 转换
│   ├── filename.py       # 文件名渲染逻辑
│   └── filter.py         # 全局和创作者级别过滤器
├── downloader/           # HTTP 下载实现
│   └── http_downloader.py # 带重试和 retry_url 降级的下载器
├── storage/              # SQLite 数据库层
│   ├── db.py             # 数据库架构和连接管理
│   └── repo.py           # 三表架构的 CRUD 操作
├── notify/               # 青龙通知桥接
│   └── push.py           # 多渠道通知分发器
├── models/               # TypedDict 类型定义
│   └── types.py          # 数据模型定义
├── config/               # 创作者配置文件
│   ├── creators.yaml     # 活动配置（已加入 gitignore）
│   └── creators.yaml.example # 配置模板
├── data/                 # 运行时生成的数据（已加入 gitignore）
│   ├── Fanbox.db         # SQLite 数据库
│   └── [downloads]       # 下载的内容文件
├── main.py               # 应用入口点
├── config.py             # 配置加载器
├── requirements.txt      # Python 依赖
├── .env                  # 环境变量（已加入 gitignore）
└── .env.example          # 环境变量模板
```

## ⚙️ 配置参考

### 环境变量

完整的环境变量参考：[`.env.example`](.env.example)

**关键变量：**
- `FANBOX_SESSION`：用于身份验证的会话 Cookie（必需）
- `FANBOX_DOWNLOAD_DIR`：下载目标目录
- `FANBOX_LOG_LEVEL`：日志详细程度（DEBUG/INFO/WARNING/ERROR）

### 创作者规则

创作者配置语法和示例：[`config/creators.yaml.example`](config/creators.yaml.example)

**支持的规则：**
- `min_price`：最低投稿价格阈值
- `extensions`：允许的文件扩展名白名单
- `date_range`：日期范围约束
- 每个创作者 ID 的自定义过滤器

## 🏗️ 架构与实现

### 设计理念

FanboxMonitor 采用模块化、管道化的架构设计：

1. **爬虫层**：协调从 Fanbox API 获取数据，实施速率限制
2. **解析层**：将原始 API 响应转换为结构化的 FileItem 对象
3. **过滤层**：应用全局和创作者级别的过滤规则
4. **下载层**：处理文件下载，具备智能重试逻辑
5. **存储层**：维护持久化状态，实现去重和增量更新
6. **通知层**：通过青龙通知渠道发送完成摘要

### 关键技术决策

- **curl_cffi 集成**：通过 Chrome 指纹模拟绕过 Fanbox 反爬机制
- **SQLite 持久化**：四表架构（seen_posts、downloaded、cursor、run_log）记录去重状态、下载结果、最近扫描 checkpoint 和执行日志
- **指数退避**：429 响应时 5-6 分钟退避，防止 IP 封禁
- **Retry URL 降级**：主 URL 失败时使用缩略图 URL 优雅降级

### 源码对照

本项目完整移植了 [PixivFanboxDownloader](../PixivFanboxDownloader) Chrome 扩展的核心逻辑。关键源码模块映射：

| 原始 TypeScript 模块 | Python 等价模块 |
|---------------------|----------------|
| `API.ts` | `api/client.py`, `api/endpoints.py` |
| `SaveData.ts` | `storage/db.py`, `storage/repo.py` |
| `FileName.ts` | `parser/filename.py` |
| `Filter.ts` | `parser/filter.py` |
| `CrawlInterval.ts` | `crawler/interval.py` |
| `InitHomePage.ts` | `main.py` |
| `DownloadControl.ts` | `downloader/http_downloader.py` |
| `download/DownloadRecord.ts` | `storage/repo.py` |

详细的架构决策和设计模式记录在外部 plan 文件中。

## 🤝 贡献指南

欢迎贡献！请随时提交 issue 和 pull request。

1. Fork 本仓库
2. 创建特性分支（`git checkout -b feature/amazing-feature`）
3. 提交更改（`git commit -m '添加精彩功能'`）
4. 推送到分支（`git push origin feature/amazing-feature`）
5. 开启 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- 原始 [PixivFanboxDownloader](../PixivFanboxDownloader) Chrome 扩展作者
- Pixiv Fanbox 平台
- 青龙面板社区
- 所有本项目的贡献者和用户

---

<div align="center">

**如果这个项目对您有帮助，请考虑给它一个 ⭐️ Star！**

由 Hoyoung 用 ❤️ 制作

</div>

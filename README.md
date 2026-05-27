# FanboxMonitor

<div align="center">

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Qinglong%20Panel-orange.svg)
![Last Commit](https://img.shields.io/github/last-commit/qwe1187292926/fanbox-monitor.svg)
![Issues](https://img.shields.io/github/issues/qwe1187292926/fanbox-monitor.svg)
![Stars](https://img.shields.io/github/stars/qwe1187292926/fanbox-monitor.svg?style=social)

**Automated Pixiv Fanbox Content Monitor & Downloader**

[English](README.md) | [中文](README.zh-CN.md) | [日本語](README.ja-JP.md)

</div>

---

### If it helpful, please give me a star ~ ⭐

---

## 📖 Overview

FanboxMonitor is a production-ready automated monitoring and downloading solution for Pixiv Fanbox content. Designed as a Python-based server-side application, it seamlessly integrates with Qinglong Panel for scheduled execution, automatically detecting and downloading new posts from followed and supported creators.

This project represents a complete Python port of the core crawling, filtering, and downloading logic from the Chrome extension [PixivFanboxDownloader](../PixivFanboxDownloader), optimized for headless server deployment with enterprise-grade reliability.

## ✨ Key Features

- **Dual Source Monitoring**: Independent toggles for Following and Supporting creator streams
- **Per-Creator Thresholds**: Configurable minimum price filters (e.g., skip posts under ¥2000 from specific creators)
- **Advanced Filtering**: Extension whitelisting, price range filtering, date range constraints
- **SQLite Persistence**: Records processed posts, downloaded files, scan checkpoints, and execution logs
- **Intelligent Retry System**: Automatic retry with `retry_url` fallback for thumbnail degradation
- **Rate Limit Handling**: Smart backoff strategy (5-6 minutes) for 429 responses
- **Multi-Channel Notifications**: Qinglong notify integration supporting Telegram, Bark, WeChat, PushPlus, and more
- **Anti-Detection**: `curl_cffi` with Chrome fingerprint bypasses Fanbox anti-scraping mechanisms

## 🚀 Quick Start

### Prerequisites

- Python 3.9 or higher
- Qinglong Panel (recommended for production)
- Pixiv Fanbox account with active subscriptions

### Deployment on Qinglong Panel

#### Step 1: Repository Setup

Clone the repository to your Qinglong server:

```bash
# Option A: Manual deployment
cd /ql/data
git clone https://github.com/qwe1187292926/fanbox-monitor.git

# Option B: Use Qinglong's Subscription Management
# Add repository URL in Qinglong Dashboard → Subscription Management
```

#### Step 2: Environment Configuration

Navigate to Qinglong Dashboard → Environment Variables and configure the following variables (refer to [`.env.example`](.env.example)):

**Required Variables:**
- `FANBOX_SESSION`: Your Fanbox session cookie (see extraction instructions below)

**Optional Variables:**
- `FANBOX_DOWNLOAD_DIR`: Download directory (default: `./data`)
- `FANBOX_LOG_LEVEL`: Log level (default: `INFO`)
- Additional variables as documented in `.env.example`

**How to Extract FANBOX_SESSION:**
1. Log in to [Pixiv Fanbox](https://www.fanbox.cc/) in Chrome/Firefox
2. Press `F12` to open Developer Tools
3. Navigate to **Application** tab → **Cookies** → `https://www.fanbox.cc`
4. Copy the value of `FANBOXSESSID` cookie
5. Paste this value as `FANBOX_SESSION` in Qinglong environment variables

#### Step 3: Per-Creator Configuration (Optional)

Customize creator-specific rules by copying and editing the configuration file:

```bash
cp config/creators.yaml.example config/creators.yaml
```

Edit [`config/creators.yaml`](config/creators.yaml) to set per-creator thresholds and filters (see [`creators.yaml.example`](config/creators.yaml.example) for syntax).

#### Step 4: Schedule Task Creation

In Qinglong Dashboard → Scheduled Tasks, create a new task:

- **Command**: `python3 /ql/data/FanboxMonitor/main.py`
- **Schedule**: `0 */6 * * *` (every 6 hours)
- **Name**: `FanboxMonitor` (or your preferred name)

#### Step 5: Initial Execution & Verification

Manually trigger the task for the first run and monitor the logs:

```bash
# Execute manually
python3 /ql/data/FanboxMonitor/main.py

# Check logs in Qinglong Dashboard → Scheduled Tasks → Logs
```

Verify that:
- ✅ Session authentication succeeds
- ✅ Creator posts are detected
- ✅ Files download to the configured directory
- ✅ Notifications are sent upon completion

---

### Local Development & Debugging

For local testing and development:

```bash
# 1. Create virtual environment
python3 -m venv venv

# 2. Activate virtual environment
# Linux/macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your FANBOX_SESSION

cp config/creators.yaml.example config/creators.yaml

# 5. Run the application
python main.py
```

**Debugging Tips:**
- Set `FANBOX_LOG_LEVEL=DEBUG` for verbose logging
- Check `data/Fanbox.db` for SQLite database contents
- Review notification channel configurations in Qinglong settings

## 📁 Project Structure

```
FanboxMonitor/
├── api/                  # Fanbox API client, endpoint wrappers, exception handling
│   ├── client.py         # HTTP client with curl_cffi integration
│   ├── endpoints.py      # API endpoint definitions
│   └── exceptions.py     # Custom exception classes
├── crawler/              # Crawling orchestration for supporting/following streams
│   ├── following.py      # Following creator crawler
│   ├── supporting.py     # Supporting creator crawler
│   ├── incremental.py    # Incremental crawling logic
│   └── interval.py       # Rate limiting and interval management
├── parser/               # Post parsing, filename generation, filtering
│   ├── post_parser.py    # PostBody → FileItem transformation
│   ├── filename.py       # Filename rendering logic
│   └── filter.py         # Global and per-creator filters
├── downloader/           # HTTP download implementation
│   └── http_downloader.py # Download with retry + retry_url fallback
├── storage/              # SQLite database layer
│   ├── db.py             # Database schema and connection management
│   └── repo.py           # CRUD operations for SQLite runtime state
├── notify/               # Notification bridge to Qinglong notify
│   └── push.py           # Multi-channel notification dispatcher
├── models/               # TypedDict type definitions
│   └── types.py          # Data model definitions
├── config/               # Per-creator configuration files
│   ├── creators.yaml     # Active configuration (gitignored)
│   └── creators.yaml.example # Template configuration
├── data/                 # Runtime-generated data (gitignored)
│   ├── Fanbox.db         # SQLite database
│   └── [downloads]       # Downloaded content files
├── main.py               # Application entry point
├── config.py             # Configuration loader
├── requirements.txt      # Python dependencies
├── .env                  # Environment variables (gitignored)
└── .env.example          # Environment variable template
```

## ⚙️ Configuration Reference

### Environment Variables

Complete environment variable reference: [`.env.example`](.env.example)

**Critical Variables:**
- `FANBOX_SESSION`: Session cookie for authentication (required)
- `FANBOX_DOWNLOAD_DIR`: Download destination directory
- `FANBOX_LOG_LEVEL`: Logging verbosity (DEBUG/INFO/WARNING/ERROR)

### Per-Creator Rules

Per-creator configuration syntax and examples: [`config/creators.yaml.example`](config/creators.yaml.example)

**Supported Rules:**
- `min_price`: Minimum post price threshold
- `extensions`: Allowed file extensions whitelist
- `date_range`: Date range constraints
- Custom filters per creator ID

## 🏗️ Architecture & Implementation

### Design Philosophy

FanboxMonitor follows a modular, pipeline-based architecture:

1. **Crawler Layer**: Orchestrates data fetching from Fanbox API with rate limiting
2. **Parser Layer**: Transforms raw API responses into structured FileItem objects
3. **Filter Layer**: Applies global and per-creator filtering rules
4. **Downloader Layer**: Handles file downloads with intelligent retry logic
5. **Storage Layer**: Maintains persistent state for deduplication and incremental updates
6. **Notification Layer**: Dispatches completion summaries via Qinglong notify channels

### Key Technical Decisions

- **curl_cffi Integration**: Bypasses Fanbox anti-scraping through Chrome fingerprint emulation
- **SQLite Persistence**: Four-table schema (`seen_posts`, `downloaded`, `cursor`, `run_log`) records deduplication state, download results, latest scan checkpoints, and execution logs
- **Exponential Backoff**: 5-6 minute backoff on 429 responses prevents IP bans
- **Retry URL Fallback**: Graceful degradation using thumbnail URLs when primary URLs fail

### Source Attribution

This project is a complete Python port of the core logic from [PixivFanboxDownloader](../PixivFanboxDownloader) Chrome extension. Key source modules mapped:

| Original TypeScript Module | Python Equivalent |
|---------------------------|-------------------|
| `API.ts` | `api/client.py`, `api/endpoints.py` |
| `SaveData.ts` | `storage/db.py`, `storage/repo.py` |
| `FileName.ts` | `parser/filename.py` |
| `Filter.ts` | `parser/filter.py` |
| `CrawlInterval.ts` | `crawler/interval.py` |
| `InitHomePage.ts` | `main.py` |
| `DownloadControl.ts` | `downloader/http_downloader.py` |
| `download/DownloadRecord.ts` | `storage/repo.py` |

Detailed architectural decisions and design patterns are documented in the external plan file.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Original [PixivFanboxDownloader](../PixivFanboxDownloader) Chrome extension authors
- Pixiv Fanbox platform
- Qinglong Panel community
- All contributors and users of this project

---

<div align="center">

**If this project helps you, please consider giving it a ⭐️ Star!**

Made with ❤️ by Hoyoung

</div>

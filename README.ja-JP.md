# FanboxMonitor

<div align="center">

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Qinglong%20Panel-orange.svg)
![Last Commit](https://img.shields.io/github/last-commit/qwe1187292926/fanbox-monitor.svg)
![Issues](https://img.shields.io/github/issues/qwe1187292926/fanbox-monitor.svg)
![Stars](https://img.shields.io/github/stars/qwe1187292926/fanbox-monitor.svg?style=social)

**Pixiv Fanbox 自動化モニタリング＆ダウンローダー**

[English](README.md) | [中文](README.zh-CN.md) | [日本語](README.ja-JP.md)

</div>

---

### If it helpful, please give me a star ~ ⭐

---

## 📖 プロジェクト概要

FanboxMonitor は、Pixiv Fanbox コンテンツのための本番環境対応の自動化モニタリングおよびダウンロードソリューションです。Python ベースのサーバーサイドアプリケーションとして設計され、Qinglong パネルとシームレスに統合し、スケジュールされた実行でフォロー中および支援中のクリエイターの新しい投稿を自動的に検出してダウンロードします。

このプロジェクトは、Chrome 拡張機能 [PixivFanboxDownloader](../PixivFanboxDownloader) のコアなクロール、フィルタリング、ダウンロードロジックを完全に Python に移植したもので、エンタープライズグレードの信頼性を実現し、ヘッドレスサーバーデプロイメントに最適化されています。

## ✨ 主な機能

- **デュアルソースモニタリング**：フォロー（Following）と支援（Supporting）クリエイターストリームの独立したトグル制御
- **クリエイター別しきい値**：設定可能な最低価格フィルター（例：特定のクリエイターの¥2000未満の投稿をスキップ）
- **高度なフィルタリング**：拡張子ホワイトリスト、価格範囲フィルター、日付範囲制約
- **SQLite 永続化**：重複排除、増分カーソル、実行ログのための3テーブルスキーマ
- **インテリジェントリトライシステム**：サムネイル劣化に対する `retry_url` フェイルバック付き自動リトライ
- **レート制限処理**：429 レスポンスに対するスマートバックオフ戦略（5-6分）
- **マルチチャネル通知**：Telegram、Bark、WeChat、PushPlus などをサポートする Qinglong notify 統合
- **アンチディテクション**：Chrome フィンガープリントで Fanbox のアンチスクレイピングを回避する `curl_cffi`

## 🚀 クイックスタート

### 前提条件

- Python 3.9 以上
- Qinglong パネル（本番環境推奨）
- アクティブなサブスクリプションを持つ Pixiv Fanbox アカウント

### Qinglong パネルへのデプロイ

#### ステップ 1：リポジトリ設定

リポジトリを Qinglong サーバーにクローンします：

```bash
# オプション A：手動デプロイ
cd /ql/data
git clone https://github.com/qwe1187292926/fanbox-monitor.git

# オプション B：Qinglong のサブスクリプション管理を使用
# Qinglong ダッシュボード → サブスクリプション管理でリポジトリ URL を追加
```

#### ステップ 2：環境変数の設定

Qinglong ダッシュボード → 環境変数に移動し、以下の変数を設定します（[`.env.example`](.env.example) を参照）：

**必須変数：**
- `FANBOX_SESSION`：Fanbox セッション Cookie（以下の抽出方法を参照）

**オプション変数：**
- `FANBOX_DOWNLOAD_DIR`：ダウンロードディレクトリ（デフォルト：`./data`）
- `FANBOX_LOG_LEVEL`：ログレベル（デフォルト：`INFO`）
- その他の変数は `.env.example` で確認可能

**FANBOX_SESSION の抽出方法：**
1. Chrome/Firefox ブラウザで [Pixiv Fanbox](https://www.fanbox.cc/) にログイン
2. `F12` を押して開発者ツールを開く
3. **Application** タブ → **Cookies** → `https://www.fanbox.cc` に移動
4. `FANBOXSESSID` Cookie の値をコピー
5. この値を Qinglong 環境変数の `FANBOX_SESSION` として貼り付け

#### ステップ 3：クリエイター別設定（オプション）

クリエイター固有のルールをカスタマイズするには、設定ファイルをコピーして編集します：

```bash
cp config/creators.yaml.example config/creators.yaml
```

[`config/creators.yaml`](config/creators.yaml) を編集して、クリエイター別のしきい値とフィルターを設定します（構文は [`creators.yaml.example`](config/creators.yaml.example) を参照）。

#### ステップ 4：スケジュールタスクの作成

Qinglong ダッシュボード → スケジュールタスクで新しいタスクを作成します：

- **コマンド**：`python3 /ql/data/FanboxMonitor/main.py`
- **スケジュール**：`0 */6 * * *`（6時間ごと）
- **名前**：`FanboxMonitor`（または任意の名前）

#### ステップ 5：初回実行と検証

初回実行のためにタスクを手動でトリガーし、ログを監視します：

```bash
# 手動で実行
python3 /ql/data/FanboxMonitor/main.py

# Qinglong ダッシュボード → スケジュールタスク → ログで確認
```

以下を検証します：
- ✅ セッション認証が成功する
- ✅ クリエイターの投稿が検出される
- ✅ ファイルが設定されたディレクトリにダウンロードされる
- ✅ 完了時に通知が送信される

---

### ローカル開発とデバッグ

ローカルテストおよび開発用：

```bash
# 1. 仮想環境を作成
python3 -m venv venv

# 2. 仮想環境を有効化
# Linux/macOS：
source venv/bin/activate
# Windows：
venv\Scripts\activate

# 3. 依存関係をインストール
pip install -r requirements.txt

# 4. 環境を設定
cp .env.example .env
# .env を編集して FANBOX_SESSION を追加

cp config/creators.yaml.example config/creators.yaml

# 5. アプリケーションを実行
python main.py
```

**デバッグのヒント：**
- 詳細ログには `FANBOX_LOG_LEVEL=DEBUG` を設定
- SQLite データベースの内容を確認するには `data/Fanbox.db` をチェック
- Qinglong 設定で通知チャネルの設定を確認

## 📁 プロジェクト構造

```
FanboxMonitor/
├── api/                  # Fanbox API クライアント、エンドポイントラッパー、例外処理
│   ├── client.py         # curl_cffi 統合 HTTP クライアント
│   ├── endpoints.py      # API エンドポイント定義
│   └── exceptions.py     # カスタム例外クラス
├── crawler/              # 支援/フォロー ストリームのクロールオーケストレーション
│   ├── following.py      # フォロー中クリエイター クローラー
│   ├── supporting.py     # 支援中クリエイター クローラー
│   ├── incremental.py    # 増分クロールロジック
│   └── interval.py       # レート制限と間隔管理
├── parser/               # 投稿解析、ファイル名生成、フィルタリング
│   ├── post_parser.py    # PostBody → FileItem 変換
│   ├── filename.py       # ファイル名レンダリングロジック
│   └── filter.py         # グローバルおよびクリエイター別フィルター
├── downloader/           # HTTP ダウンロード実装
│   └── http_downloader.py # リトライ + retry_url フェイルバック付きダウンローダー
├── storage/              # SQLite データベース層
│   ├── db.py             # データベーススキーマと接続管理
│   └── repo.py           # 3テーブルスキーマの CRUD 操作
├── notify/               # Qinglong notify への通知ブリッジ
│   └── push.py           # マルチチャネル通知ディスパッチャー
├── models/               # TypedDict 型定義
│   └── types.py          # データモデル定義
├── config/               # クリエイター別設定ファイル
│   ├── creators.yaml     # アクティブ設定（gitignore 対象）
│   └── creators.yaml.example # テンプレート設定
├── data/                 # ランタイム生成データ（gitignore 対象）
│   ├── Fanbox.db         # SQLite データベース
│   └── [downloads]       # ダウンロードされたコンテンツファイル
├── main.py               # アプリケーションエントリーポイント
├── config.py             # 設定ローダー
├── requirements.txt      # Python 依存関係
├── .env                  # 環境変数（gitignore 対象）
└── .env.example          # 環境変数テンプレート
```

## ⚙️ 設定リファレンス

### 環境変数

完全な環境変数リファレンス：[`.env.example`](.env.example)

**重要な変数：**
- `FANBOX_SESSION`：認証用セッション Cookie（必須）
- `FANBOX_DOWNLOAD_DIR`：ダウンロード先ディレクトリ
- `FANBOX_LOG_LEVEL`：ログの詳細度（DEBUG/INFO/WARNING/ERROR）

### クリエイター別ルール

クリエイター別設定の構文と例：[`config/creators.yaml.example`](config/creators.yaml.example)

**サポートされているルール：**
- `min_price`：最低投稿価格しきい値
- `extensions`：許可されるファイル拡張子のホワイトリスト
- `date_range`：日付範囲制約
- クリエイター ID ごとのカスタムフィルター

## 🏗️ アーキテクチャと実装

### 設計思想

FanboxMonitor はモジュラーでパイプラインベースのアーキテクチャに従います：

1. **クロール層**：レート制限付きで Fanbox API からのデータ取得をオーケストレーション
2. **解析層**：生の API レスポンスを構造化された FileItem オブジェクトに変換
3. **フィルター層**：グローバルおよびクリエイター別のフィルタリングルールを適用
4. **ダウンロード層**：インテリジェントなリトライロジックでファイルダウンロードを処理
5. **ストレージ層**：重複排除と増分更新のための永続状態を維持
6. **通知層**：Qinglong notify チャネル経由で完了サマリーを送信

### 主要な技術的決定

- **curl_cffi 統合**：Chrome フィンガープリントエミュレーションで Fanbox のアンチスクレイピングを回避
- **SQLite 永続化**：3テーブルスキーマ（posts、cursors、logs）で冪等な実行を保証
- **指数バックオフ**：429 レスポンス時に 5-6 分のバックオフで IP バンを防止
- **Retry URL フェイルバック**：プライマリ URL が失敗した場合にサムネイル URL を使用したグレースフルデグラデーション

### ソース属性

このプロジェクトは、[PixivFanboxDownloader](../PixivFanboxDownloader) Chrome 拡張機能のコアロジックを完全に Python に移植したものです。主要なソースモジュールのマッピング：

| 元の TypeScript モジュール | Python 同等モジュール |
|--------------------------|---------------------|
| `API.ts` | `api/client.py`, `api/endpoints.py` |
| `SaveData.ts` | `storage/db.py`, `storage/repo.py` |
| `FileName.ts` | `parser/filename.py` |
| `Filter.ts` | `parser/filter.py` |
| `CrawlInterval.ts` | `crawler/interval.py` |
| `InitHomePage.ts` | `main.py` |
| `DownloadControl.ts` | `downloader/http_downloader.py` |
| `download/DownloadRecord.ts` | `storage/repo.py` |

詳細なアーキテクチャの決定と設計パターンは、外部 plan ファイルに記載されています。

## 🤝 貢献ガイド

貢献を歓迎します！issue や pull request をお気軽にご提出ください。

1. リポジトリをフォーク
2. 機能ブランチを作成（`git checkout -b feature/amazing-feature`）
3. 変更をコミット（`git commit -m '素晴らしい機能を追加'`）
4. ブランチにプッシュ（`git push origin feature/amazing-feature`）
5. Pull Request をオープン

## 📄 ライセンス

このプロジェクトは MIT ライセンスの下でライセンスされています - 詳細は [LICENSE](LICENSE) ファイルをご覧ください。

## 🙏 謝辞

- 元の [PixivFanboxDownloader](../PixivFanboxDownloader) Chrome 拡張機能の作者
- Pixiv Fanbox プラットフォーム
- Qinglong パネルコミュニティ
- このプロジェクトのすべての貢献者とユーザー

---

<div align="center">

**このプロジェクトが役に立った場合は、⭐️ Star をつけていただけると嬉しいです！**

Hoyoung によって ❤️ を込めて作成

</div>

"""Compact, user-facing explanations for common runtime failures."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from i18n import normalize_lang


@dataclass(frozen=True)
class ErrorExplanation:
    title: str
    cause: str
    clue: str
    matched: bool

    def format(self, lang: str = "zh-CN") -> str:
        labels = _labels(lang)
        lines = [self.title]
        if self.cause:
            lines.append(f"{labels['cause']}: {self.cause}")
        if self.clue:
            lines.append(f"{labels['clue']}: {self.clue}")
        return "\n".join(lines)


_LABELS = {
    "zh-CN": {"cause": "可能原因", "clue": "线索"},
    "ja-JP": {"cause": "考えられる原因", "clue": "手がかり"},
    "en-US": {"cause": "Possible cause", "clue": "Clue"},
}

_MESSAGES = {
    "zh-CN": {
        "tls": (
            "网络/TLS 连接失败",
            "代理不可达、代理协议不匹配，或服务器/容器出站 HTTPS 被代理拦截",
        ),
        "proxy": (
            "代理连接失败",
            "FANBOX_PROXY 地址、端口、协议或代理监听范围配置不正确",
        ),
        "dns": ("DNS 解析失败", "服务器 DNS 不可用，或当前网络无法解析目标域名"),
        "timeout": (
            "网络请求超时",
            "Fanbox 或代理响应太慢，服务器出站网络不稳定，或当前线路被阻断",
        ),
        "auth": ("认证失败", "FANBOX_SESSION cookie 失效、填错，或账号登录状态已过期"),
        "forbidden": (
            "资源无权访问",
            "当前账号未赞助对应档位、内容受限，或 cookie 对该资源没有权限",
        ),
        "rate": ("Fanbox 限流", "请求过快或短时间内重试过多，等待后再运行"),
        "server": ("Fanbox 服务端错误", "Fanbox/CDN 临时异常，通常稍后重试即可"),
        "json": ("响应格式异常", "Fanbox 返回了非 JSON 内容，可能是风控页、代理错误页或临时页面"),
        "disk": ("磁盘空间不足", "下载目录所在磁盘已满，需要清理空间或更换目录"),
        "permission": ("文件权限不足", "下载目录或数据库文件没有读写权限"),
        "detail": ("投稿详情拉取失败", "网络异常、Fanbox 临时错误，或该投稿暂时不可访问"),
        "submit": ("下载任务提交失败", "线程池已关闭、系统资源不足，或本次运行正在退出"),
        "network": ("网络请求失败", "服务器出站网络、代理或 Fanbox 连接链路异常"),
        "generic": ("运行异常", "请查看线索中的原始错误关键字"),
    },
    "ja-JP": {
        "tls": (
            "ネットワーク/TLS 接続に失敗しました",
            "プロキシに到達できない、プロキシ方式が違う、またはサーバー/コンテナの HTTPS が遮断されています",
        ),
        "proxy": (
            "プロキシ接続に失敗しました",
            "FANBOX_PROXY のアドレス、ポート、方式、または待受範囲が正しくない可能性があります",
        ),
        "dns": ("DNS 解決に失敗しました", "サーバーの DNS または現在のネットワークで対象ドメインを解決できません"),
        "timeout": (
            "ネットワークリクエストがタイムアウトしました",
            "Fanbox またはプロキシの応答が遅い、ネットワークが不安定、または経路が遮断されています",
        ),
        "auth": ("認証に失敗しました", "FANBOX_SESSION cookie が期限切れ、誤設定、またはログイン状態が失効しています"),
        "forbidden": (
            "リソースにアクセスできません",
            "支援プラン不足、限定コンテンツ、または cookie にこのリソースの権限がありません",
        ),
        "rate": ("Fanbox レート制限", "短時間のリクエストまたは再試行が多すぎます。待ってから再実行してください"),
        "server": ("Fanbox サーバーエラー", "Fanbox/CDN の一時的な異常です。通常は後で再試行できます"),
        "json": ("レスポンス形式が異常です", "JSON ではなく、制限ページ、プロキシエラー、または一時ページが返った可能性があります"),
        "disk": ("ディスク容量不足", "ダウンロード先のディスク容量を空けるか、保存先を変更してください"),
        "permission": ("ファイル権限不足", "ダウンロード先または DB ファイルに読み書き権限がありません"),
        "detail": ("投稿詳細の取得に失敗しました", "ネットワーク異常、Fanbox の一時エラー、または投稿が一時的にアクセス不可です"),
        "submit": ("ダウンロードタスク投入失敗", "スレッドプール終了、システムリソース不足、または実行終了中の可能性があります"),
        "network": ("ネットワークリクエストに失敗しました", "サーバーの外向き通信、プロキシ、または Fanbox への経路に問題があります"),
        "generic": ("実行時エラー", "手がかりの元エラーキーワードを確認してください"),
    },
    "en-US": {
        "tls": (
            "Network/TLS connection failed",
            "Proxy is unreachable, proxy scheme is wrong, or outbound HTTPS from the server/container is being intercepted",
        ),
        "proxy": (
            "Proxy connection failed",
            "FANBOX_PROXY address, port, scheme, or proxy bind/listen settings are incorrect",
        ),
        "dns": ("DNS lookup failed", "Server DNS is unavailable or the current network cannot resolve the target host"),
        "timeout": (
            "Network request timed out",
            "Fanbox or the proxy is slow, outbound network is unstable, or the route is blocked",
        ),
        "auth": ("Authentication failed", "FANBOX_SESSION cookie is expired, wrong, or the account login state has expired"),
        "forbidden": (
            "Resource is not accessible",
            "Current account may not support the required plan, content is restricted, or the cookie lacks permission",
        ),
        "rate": ("Fanbox rate limited the run", "Requests or retries were too frequent; wait before running again"),
        "server": ("Fanbox server error", "Fanbox/CDN is temporarily failing; retrying later usually works"),
        "json": ("Unexpected response format", "Fanbox returned non-JSON content, possibly a risk page, proxy error page, or temporary page"),
        "disk": ("Disk is full", "Free space on the download volume or change the download directory"),
        "permission": ("File permission denied", "Download directory or database file is not writable"),
        "detail": ("Post detail fetch failed", "Network issue, temporary Fanbox error, or the post is temporarily inaccessible"),
        "submit": ("Download task submit failed", "Thread pool is closed, system resources are low, or the run is shutting down"),
        "network": ("Network request failed", "Outbound network, proxy, or Fanbox connection path is failing"),
        "generic": ("Runtime error", "Check the raw error keywords in the clue"),
    },
}


def simplify_error(error: Any, lang: str = "zh-CN") -> str:
    explanation = explain_error(error, lang)
    if not explanation.matched:
        return _trim(_exception_text(error), 300)
    return explanation.format(lang)


def is_common_error(error: Any) -> bool:
    return explain_error(error).matched


def explain_error(error: Any, lang: str = "zh-CN") -> ErrorExplanation:
    lang = normalize_lang(lang)
    raw = _exception_text(error)
    if _already_explained(raw):
        return ErrorExplanation(raw, "", "", True)

    lowered = raw.lower()
    key = _classify(lowered)
    title, cause = _MESSAGES.get(lang, _MESSAGES["zh-CN"])[key]
    clue = _clue(raw, lowered)
    return ErrorExplanation(title, cause, clue, key != "generic")


def _labels(lang: str) -> dict[str, str]:
    return _LABELS.get(normalize_lang(lang), _LABELS["zh-CN"])


def _exception_text(error: Any) -> str:
    if isinstance(error, BaseException):
        parts: list[str] = []
        seen: set[int] = set()
        current: BaseException | None = error
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            text = str(current).strip()
            if text:
                parts.append(text)
            current = current.__cause__ or current.__context__
        return _collapse(" | ".join(parts))
    return _collapse(str(error))


def _already_explained(raw: str) -> bool:
    markers = (
        "可能原因:",
        "考えられる原因:",
        "Possible cause:",
    )
    return any(marker in raw for marker in markers)


def _classify(lowered: str) -> str:
    if "rate_limit" in lowered or "429" in lowered or "too many requests" in lowered:
        return "rate"
    if "401" in lowered or "fanbox_session" in lowered or "cookie" in lowered and "expired" in lowered:
        return "auth"
    if "403" in lowered or "forbidden" in lowered:
        return "forbidden"
    if (
        "tls connect error" in lowered
        or "openssl_internal" in lowered
        or "curl: (35)" in lowered
        or "sslerror" in lowered
        or "ssleoferror" in lowered
        or "certificate verify failed" in lowered
    ):
        return "tls"
    if (
        "proxy" in lowered
        or "socks" in lowered
        or "connect tunnel" in lowered
    ):
        return "proxy"
    if (
        "could not resolve host" in lowered
        or "nameresolutionerror" in lowered
        or "getaddrinfo" in lowered
        or "temporary failure in name resolution" in lowered
    ):
        return "dns"
    if "timed out" in lowered or "timeout" in lowered or "operation timed out" in lowered:
        return "timeout"
    if re.search(r"\b50[0-9]\b", lowered):
        return "server"
    if "invalid_json" in lowered or "not valid json" in lowered or "响应不是合法 json" in lowered:
        return "json"
    if "no space left on device" in lowered or "disk full" in lowered:
        return "disk"
    if "permission denied" in lowered or "access is denied" in lowered:
        return "permission"
    if "detail_fetch_failed" in lowered:
        return "detail"
    if "submit_failed" in lowered:
        return "submit"
    if (
        "curl:" in lowered
        or "connectionerror" in lowered
        or "connection refused" in lowered
        or "failed to connect" in lowered
        or "network" in lowered
        or "请求失败" in lowered
    ):
        return "network"
    return "generic"


def _clue(raw: str, lowered: str) -> str:
    clues: list[str] = []

    url = _first_match(r"https?://[^\s)\],;]+", raw)
    if url:
        clues.append(url.rstrip("."))

    curl_code = _first_match(r"curl:\s*\((\d+)\)", raw, group=1)
    if curl_code:
        clues.append(f"curl {curl_code}")

    status = _first_match(r"\b([45][0-9]{2})\b", raw, group=1)
    if status and f"HTTP {status}" not in clues:
        clues.append(f"HTTP {status}")

    if "tls connect error" in lowered:
        clues.append("TLS connect error")
    elif "timed out" in lowered or "timeout" in lowered:
        clues.append("timeout")
    elif "could not resolve host" in lowered or "getaddrinfo" in lowered:
        clues.append("DNS")

    if not clues:
        clues.append(_trim(raw, 140))

    return "; ".join(clues[:4])


def _first_match(pattern: str, text: str, group: int = 0) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return ""
    return match.group(group)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _trim(text: str, limit: int) -> str:
    text = _collapse(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."

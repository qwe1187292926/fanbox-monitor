"""Fanbox API 相关异常。"""


class FanboxError(Exception):
    """所有 Fanbox API 错误的基类。"""


class FanboxAuthError(FanboxError):
    """401：认证失败，cookie 已失效。run 应立即中止。"""


class FanboxForbiddenError(FanboxError):
    """403：对该资源没访问权限（付费等级不足 / 限定级别内容）。

    仅影响单条资源，run 应跳过该条继续。
    """


class FanboxRateLimitError(FanboxError):
    """触发了 fanbox 的限流（429）。需要长时间退避。"""


class FanboxAPIError(FanboxError):
    """其他 HTTP / JSON 错误。"""

"""Short-lived, loopback-only browser login. Credentials never enter MCP results."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from aiohttp import web

FLOW_TTL = 600.0
SMS_COOLDOWN = 60.0
MAX_CAPTCHA_ATTEMPTS = 3
MAX_BODY_BYTES = 8192
REQUEST_TIMEOUT = 30.0
_STATIC = Path(__file__).with_name("static")
_MOBILE = re.compile(r"1[3-9][0-9]{9}\Z")
_CODE = re.compile(r"[0-9]{6}\Z")
_CAPTCHA = re.compile(r"[A-Za-z0-9]{1,16}\Z")
_CAPTCHA_IMAGE = re.compile(r"data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+\Z")
_HTTP_LOGGER = logging.Logger("meiju_mcp.login.http")
_HTTP_LOGGER.disabled = True

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}


class LoginClient(Protocol):
    def auth_status(self) -> dict[str, Any]: ...

    async def request_sms(self, mobile: str, captcha: str | None = None) -> dict[str, Any]: ...

    async def verify_sms(self, mobile: str, code: str) -> dict[str, Any]: ...

    async def logout(self) -> None: ...


@dataclass
class _Flow:
    secret: str
    expires_at: float
    sms_mobile: str | None = None
    captcha_mobile: str | None = None
    captcha_attempts: int = 0


def _error(code: str, message: str, status: int = 400, **extra: Any) -> web.Response:
    return web.json_response({"status": "error", "code": code, "message": message, **extra}, status=status)


class LoginPortal:
    """One process-local login flow, created lazily by ``start_login``.

    ``invalidate`` revokes links without closing the listener; ``close`` releases
    the listener too. The caller owns the client and its logout/close lifecycle.
    """

    def __init__(self, client: LoginClient):
        self._client = client
        self._flow: _Flow | None = None
        self._runner: web.AppRunner | None = None
        self._origin: str | None = None
        self._host: str | None = None
        self._lock = asyncio.Lock()
        self._sms_not_before = 0.0

    async def start_login(self) -> dict[str, Any]:
        async with self._lock:
            if self._client.auth_status().get("authenticated"):
                self._flow = None
                return {"status": "authenticated"}
            if self._runner is None:
                await self._listen()
            now = time.monotonic()
            if self._flow is None or self._flow.expires_at <= now:
                self._flow = _Flow(secrets.token_urlsafe(32), now + FLOW_TTL)
            return {
                "status": "login_required",
                "login_url": f"{self._origin}/#flow={self._flow.secret}",
                "expires_in": max(0, int(self._flow.expires_at - now)),
            }

    async def invalidate(self) -> None:
        async with self._lock:
            self._flow = None

    async def close(self) -> None:
        async with self._lock:
            self._flow = None
            runner, self._runner = self._runner, None
            self._origin = self._host = None
        if runner is not None:
            await runner.cleanup()

    async def _listen(self) -> None:
        app = web.Application(client_max_size=MAX_BODY_BYTES, middlewares=[self._security])
        app.router.add_get("/", self._index)
        app.router.add_get("/login.css", self._stylesheet)
        app.router.add_get("/login.js", self._javascript)
        app.router.add_post("/api/sms", self._request_sms)
        app.router.add_post("/api/login", self._verify_sms)
        runner = web.AppRunner(app, access_log=None, logger=_HTTP_LOGGER)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", 0))
            sock.setblocking(False)
            self._host = f"127.0.0.1:{sock.getsockname()[1]}"
            self._origin = f"http://{self._host}"
            await runner.setup()
            await web.SockSite(runner, sock).start()
        except BaseException:
            sock.close()
            await runner.cleanup()
            self._origin = self._host = None
            raise
        self._runner = runner

    @web.middleware
    async def _security(self, request: web.Request, handler: Any) -> web.StreamResponse:
        hosts = request.headers.getall("Host", [])
        origins = request.headers.getall("Origin", [])
        site = request.headers.get("Sec-Fetch-Site", "")
        # A remote chat may link to this read-only page. Only a top-level document
        # navigation may be cross-site; every API request still requires origin.
        navigation = (
            request.method == "GET"
            and request.path == "/"
            and request.headers.get("Sec-Fetch-Mode") == "navigate"
            and request.headers.get("Sec-Fetch-Dest") == "document"
            and not origins
        )
        if hosts != [self._host]:
            response = _error("invalid_host", "请使用登录工具返回的本机链接。", 403)
        elif origins and origins != [self._origin]:
            response = _error("invalid_origin", "登录请求来源无效，请重新打开登录链接。", 403)
        elif site in {"cross-site", "same-site"} and not navigation:
            response = _error("invalid_origin", "登录请求来源无效，请重新打开登录链接。", 403)
        elif request.method == "POST" and origins != [self._origin]:
            response = _error("invalid_origin", "登录请求来源无效，请重新打开登录链接。", 403)
        else:
            try:
                response = await handler(request)
            except web.HTTPRequestEntityTooLarge:
                response = _error("invalid_input", "输入内容过长，请检查后重试。", 413)
            except web.HTTPException as exc:
                response = _error("invalid_request", "请求无效，请重新打开登录链接。", exc.status)
            except Exception:
                # Never serialize/log an exception: upstream text can contain
                # phone numbers, OTPs, passwords, tokens, or response payloads.
                response = _error("service_unavailable", "暂时无法连接登录服务，请稍后重试。", 503)
        response.headers.update(_SECURITY_HEADERS)
        return response

    async def _index(self, request: web.Request) -> web.Response:
        return web.Response(text=(_STATIC / "index.html").read_text(), content_type="text/html")

    async def _stylesheet(self, request: web.Request) -> web.Response:
        return web.Response(text=(_STATIC / "login.css").read_text(), content_type="text/css")

    async def _javascript(self, request: web.Request) -> web.Response:
        return web.Response(text=(_STATIC / "login.js").read_text(), content_type="text/javascript")

    def _authorize(self, request: web.Request) -> _Flow | web.Response:
        flow = self._flow
        if flow is None or flow.expires_at <= time.monotonic():
            self._flow = None
            return _error("flow_expired", "登录链接已失效，请返回 AI 客户端重新发起登录。", 410)
        supplied = request.headers.getall("X-Meiju-Flow", [])
        if (
            len(supplied) != 1
            or not supplied[0].isascii()
            or not secrets.compare_digest(supplied[0], flow.secret)
        ):
            return _error("invalid_flow", "登录链接无效，请重新发起登录。", 403)
        if self._client.auth_status().get("authenticated"):
            self._flow = None
            return _error("already_authenticated", "美居已登录，请关闭此页面。", 409)
        return flow

    async def _body(self, request: web.Request, allowed: set[str]) -> dict[str, str] | web.Response:
        if request.content_type != "application/json":
            return _error("invalid_input", "请通过此登录页面提交。", 415)
        try:
            async with asyncio.timeout(5):
                body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return _error("invalid_input", "输入格式有误，请检查后重试。")
        if (
            not isinstance(body, dict)
            or set(body) - allowed
            or any(not isinstance(v, str) for v in body.values())
        ):
            return _error("invalid_input", "输入格式有误，请检查后重试。")
        return body

    async def _request_sms(self, request: web.Request) -> web.Response:
        async with self._lock:
            flow = self._authorize(request)
            if isinstance(flow, web.Response):
                return flow
            body = await self._body(request, {"mobile", "captcha"})
            if isinstance(body, web.Response):
                return body
            flow = self._authorize(request)
            if isinstance(flow, web.Response):
                return flow
            mobile, captcha = body.get("mobile", ""), body.get("captcha")
            if not _MOBILE.fullmatch(mobile) or (captcha is not None and not _CAPTCHA.fullmatch(captcha)):
                return _error("invalid_input", "请输入有效手机号和图形验证码。")
            now = time.monotonic()
            followup = (
                captcha is not None
                and flow.captcha_mobile == mobile
                and flow.captcha_attempts < MAX_CAPTCHA_ATTEMPTS
            )
            if now < self._sms_not_before and not followup:
                return _error(
                    "sms_cooldown",
                    "请稍后再发送验证码。",
                    429,
                    retry_after=max(1, int(self._sms_not_before - now + 0.999)),
                )
            if captcha is not None and not followup:
                return _error("captcha_expired", "图形验证已失效，请稍后重新发送验证码。")
            if followup:
                flow.captcha_attempts += 1
            else:
                self._sms_not_before = now + SMS_COOLDOWN
                flow.captcha_attempts = 0
                flow.captcha_mobile = None
                flow.sms_mobile = None
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    result = await self._client.request_sms(mobile, captcha)
            except Exception as exc:
                return self._client_error(exc, **self._abandon_captcha(flow))
            if flow.expires_at <= time.monotonic():
                self._flow = None
                return _error("flow_expired", "登录链接已失效，请返回 AI 客户端重新发起登录。", 410)
            if result.get("status") == "captcha_required":
                data_url = result.get("captcha_data_url", "")
                if (
                    not isinstance(data_url, str)
                    or len(data_url) > 1_500_000
                    or not _CAPTCHA_IMAGE.fullmatch(data_url)
                ):
                    return _error(
                        "service_unavailable",
                        "无法显示图形验证码，请稍后重试。",
                        503,
                        **self._abandon_captcha(flow),
                    )
                flow.captcha_mobile = mobile
                return web.json_response({"status": "captcha_required", "captcha_data_url": data_url})
            if result.get("status") == "sms_sent":
                flow.sms_mobile = mobile
                flow.captcha_mobile = None
                self._sms_not_before = time.monotonic() + SMS_COOLDOWN
                return web.json_response({"status": "sms_sent", "retry_after": int(SMS_COOLDOWN)})
            return _error(
                "service_unavailable",
                "暂时无法发送验证码，请稍后重试。",
                503,
                **self._abandon_captcha(flow),
            )

    def _abandon_captcha(self, flow: _Flow) -> dict[str, Any]:
        # The cloud consumes a challenge before attempting the SMS call. A failed
        # call cannot safely reuse its token; let the user restart after cooldown.
        flow.captcha_mobile = None
        return {
            "reset_captcha": True,
            "retry_after": max(0, int(self._sms_not_before - time.monotonic() + 0.999)),
        }

    async def _verify_sms(self, request: web.Request) -> web.Response:
        async with self._lock:
            flow = self._authorize(request)
            if isinstance(flow, web.Response):
                return flow
            body = await self._body(request, {"mobile", "code"})
            if isinstance(body, web.Response):
                return body
            flow = self._authorize(request)
            if isinstance(flow, web.Response):
                return flow
            mobile, code = body.get("mobile", ""), body.get("code", "")
            if not _MOBILE.fullmatch(mobile) or not _CODE.fullmatch(code):
                return _error("invalid_input", "请输入有效手机号和短信验证码。")
            if flow.sms_mobile != mobile:
                return _error("sms_required", "请先为此手机号发送短信验证码。")
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    await self._client.verify_sms(mobile, code)
            except Exception as exc:
                return self._client_error(exc)
            if flow.expires_at <= time.monotonic():
                self._flow = None
                await self._client.logout()
                return _error("flow_expired", "登录链接已失效，请返回 AI 客户端重新发起登录。", 410)
            if not self._client.auth_status().get("authenticated"):
                return _error("login_failed", "登录未完成，请检查验证码后重试。", 401)
            self._flow = None
            return web.json_response({"status": "authenticated", "message": "美居登录成功，可以关闭此页面。"})

    @staticmethod
    def _client_error(exc: Exception, **extra: Any) -> web.Response:
        # Deliberately map only machine codes; never trust raw upstream messages.
        code = getattr(exc, "code", "")
        messages = {
            "invalid_code": "验证码有误或已过期，请检查后重试。",
            "invalid_sms_code": "短信验证码有误或已过期，请检查后重试。",
            "invalid_mobile": "请输入有效的美居账号手机号。",
            "captcha_invalid": "图形验证码有误，请检查后重试。",
            "invalid_captcha": "图形验证码有误，请检查后重试。",
            "rate_limited": "请求过于频繁，请稍后重试。",
            "login_failed": "登录未完成，请检查验证码后重试。",
            "account_not_found": "请使用已有美居账号，并先在美居 App 中绑定设备。",
            "registration_required": "请先在美居 App 中完成账号注册，再使用此页面登录。",
            "account_recovery_required": "请先在美居 App 中处理账号问题，再重新登录。",
            "captcha_unavailable": "暂时无法加载图形验证码，请稍后重试。",
            "sms_not_requested": "请先发送短信验证码，再登录。",
            "session_changed": "账号状态已变更，请返回 AI 客户端重新发起登录。",
            "session_expired": "登录状态已过期，请返回 AI 客户端重新发起登录。",
        }
        if isinstance(code, str) and code in messages:
            return _error(code, messages[code], 400, **extra)
        uncertain = getattr(exc, "uncertain", False) is True or isinstance(exc, TimeoutError)
        message = (
            "服务响应超时，结果暂未确认；请稍后重试。"
            if uncertain or isinstance(exc, TimeoutError)
            else "暂时无法连接美居服务，请稍后重试。"
        )
        return _error("service_unavailable", message, 503, uncertain=uncertain, **extra)

"""Narrow Meiju application protocol, with no network or credential persistence.

Protocol reference: https://github.com/sususweet/midea_auto_cloud (Apache-2.0).
The application constants below are public protocol identifiers, not user secrets.
Signing and SMS payloads were cross-checked against the companion Swift client.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import platform
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

BASE_URL = "https://mp-prod.smartmidea.net/mas/v5/app/proxy"
SMS = "/mj/user/getSmsCode"
LOGIN = "/v6/mj/user/register"
HOMES = "/v2/homegroup/list/get"
DEVICES = "/v1/appliance/home/list/get"
STATUS = "/mjl/v1/device/status/lua/get"
CONTROL = "/mjl/v1/device/lua/control"
ALLOWED_ALIASES = frozenset({SMS, LOGIN, HOMES, DEVICES, STATUS, CONTROL})

# Public application constants: midea_auto_cloud/core/cloud.py, clouds["美的美居"].
# MUC_APP_KEY = app_key; IOT_SECRET = decoded iot_key; MAS_KEY = decoded hmac_key.
# See NOTICE for the public source URL and verification date.
MAS_KEY = "PROD_VnoClJI9aikS8dyy"
IOT_SECRET = "prod_secret123@muc"
MUC_APP_KEY = "46579c15"
APP_VERSION = "11.7.10"


@dataclass(frozen=True)
class RequestContext:
    random: str
    stamp: str
    inner_request_id: str
    outer_request_id: str

    @classmethod
    def now(cls) -> RequestContext:
        return cls(
            str(time.time_ns() // 1_000_000),
            datetime.now().strftime("%Y%m%d%H%M%S"),
            uuid.uuid4().hex,
            uuid.uuid4().hex,
        )


def json_bytes(body: dict[str, Any]) -> bytes:
    """The returned exact bytes must be both signed and transmitted."""
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def signature(
    body: bytes,
    random: str,
    query_items: list[tuple[str, str | None]] | None = None,
    *,
    mas_key: str = MAS_KEY,
    iot_secret: str = IOT_SECRET,
) -> str:
    """SignUtils semantics: omit alias, first duplicate wins, Java UTF-16 order."""
    query: dict[str, str] = {}
    for key, value in query_items or []:
        if key != "alias" and key not in query:
            query[key] = "null" if value is None else value
    message = iot_secret.encode("utf-8") + body
    for key in sorted(query, key=lambda value: value.encode("utf-16-be")):
        message += (key + query[key]).encode("utf-8")
    message += random.encode("utf-8")
    return hmac.new(mas_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def auth_body(data: dict[str, Any], iot_data: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return {
        "data": data,
        "iotData": {**iot_data, "reqId": context.inner_request_id, "stamp": context.stamp},
        "timestamp": context.stamp,
        "reqId": context.outer_request_id,
        "stamp": context.stamp,
    }


def signed_request(
    alias: str, body: dict[str, Any], *, context: RequestContext, access_token: str | None = None
) -> httpx.Request:
    if alias not in ALLOWED_ALIASES:
        raise ValueError("Request endpoint is not allowed.")
    raw = json_bytes(body)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "secretVersion": "1",
        "random": context.random,
        "sign": signature(raw, context.random, [("alias", alias)]),
        "version": APP_VERSION,
        "systemVersion": platform.system() or "Python",
        "platform": "0",
        "Accept-Encoding": "identity",
        "terminalId": "900-android",
        "appId": "900",
    }
    if access_token is not None:
        if not access_token or len(access_token) > 4096 or not all(33 <= ord(c) <= 126 for c in access_token):
            raise ValueError("Invalid in-memory session.")
        headers["accessToken"] = access_token
    # Construct directly: do not merge an injected client's cookies, auth or default headers.
    request = httpx.Request("POST", BASE_URL, params={"alias": alias}, headers=headers, content=raw)
    request.extensions["timeout"] = httpx.Timeout(30.0, connect=10.0).as_dict()
    return request

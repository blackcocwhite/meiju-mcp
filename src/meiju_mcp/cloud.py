"""Account-scoped, memory-only Meiju client. All requests are explicitly initiated.

Protocol reference: https://github.com/sususweet/midea_auto_cloud (Apache-2.0).
This implementation deliberately has no registration, recovery, retry or LAN path.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from . import profiles, protocol

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SUCCESS = {"0", "0000", "200"}
_STOP = {
    "1105": "registration_required",
    "1405": "account_recovery_required",
    "1407": "account_recovery_required",
    "1129": "rate_limited",
    "40429": "rate_limited",
}
# Community reference cloud.py, _is_token_invalid_response: explicit codes only.
# These are not inferred from localized server messages or proof of live validation.
_EXPIRED_SESSION_CODES = {"7400", "40002"}


class MeijuError(Exception):
    """Safe errors only: never construct with a server message or raw exception."""

    def __init__(self, code: str, message: str, uncertain: bool = False):
        self.code = code
        self.message = message
        self.uncertain = uncertain
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "uncertain": self.uncertain}


def _malformed() -> MeijuError:
    return MeijuError("malformed_response", "The cloud response did not match the supported protocol.")


def _identifier(value: object) -> str:
    # Never coerce bool/float IDs: cloud IDs can exceed IEEE-754 integer precision.
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 33 for c in value):
        raise _malformed()
    return value


def _display(value: object, fallback: str | None = None) -> str | None:
    if not isinstance(value, str):
        return fallback
    value = "".join(c for c in value.strip() if c.isprintable())[:128]
    return value or fallback


def _server_code(envelope: dict[str, Any]) -> str:
    value = envelope.get("code")
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        return value
    raise _malformed()


def _rejection(code: str) -> MeijuError:
    safe = code if re.fullmatch(r"-?[0-9]{1,15}", code) else "unknown"
    return MeijuError("server_rejected", f"The cloud rejected the request (code {safe}); no automatic retry.")


@dataclass(repr=False, frozen=True)
class _Device:
    server_id: str
    is_air_conditioner: bool
    public: dict[str, Any]

    def __repr__(self) -> str:
        return "_Device(<private identifiers>)"


class MeijuClient:
    """One local account and one serialized request stream.

    An optional http_client is a trusted transport injection for offline testing.
    Normal clients use verified TLS, no environment proxies and no retries.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(
            verify=True,
            trust_env=False,
            follow_redirects=False,
            transport=httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0),
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self._lock = asyncio.Lock()
        self._generation = 0
        self._closed = False
        self._access_token: str | None = None
        self._sms_issued_to: str | None = None
        self._pending_captcha: tuple[str, str] | None = None
        self._client_device_id = uuid.uuid4().hex
        self._devices: dict[str, _Device] = {}
        self._device_ids: dict[str, str] = {}

    def __repr__(self) -> str:
        return f"MeijuClient(authenticated={self._access_token is not None})"

    def auth_status(self) -> dict[str, Any]:
        return {"authenticated": self._access_token is not None}

    def _clear(self) -> None:
        self._access_token = None
        self._sms_issued_to = None
        self._pending_captcha = None
        self._devices.clear()
        self._device_ids.clear()

    def _check_generation(self, generation: int, *, uncertain: bool = False) -> None:
        if self._closed or generation != self._generation:
            raise MeijuError("session_changed", "The local session changed; start a new request.", uncertain)

    def _require_auth(self) -> str:
        if self._access_token is None:
            raise MeijuError("not_authenticated", "Sign in through the local login page first.")
        return self._access_token

    async def logout(self) -> dict[str, Any]:
        # Invalidate before waiting for the lock: an in-flight login cannot resurrect a session.
        self._generation += 1
        self._clear()
        async with self._lock:
            self._http.cookies.clear()
        return {"status": "logged_out", "authenticated": False}

    async def aclose(self) -> None:
        self._generation += 1
        self._clear()
        self._closed = True
        async with self._lock:
            self._http.cookies.clear()
            if self._owns_http:
                await self._http.aclose()

    async def _request(
        self,
        alias: str,
        body: dict[str, Any],
        context: protocol.RequestContext,
        *,
        authenticated: bool = False,
        write: bool = False,
    ) -> dict[str, Any]:
        generation = self._generation
        self._check_generation(generation)
        try:
            request = protocol.signed_request(
                alias, body, context=context, access_token=self._require_auth() if authenticated else None
            )
        except ValueError:
            raise MeijuError("invalid_request", "The local request is not valid.") from None
        response: httpx.Response | None = None
        self._http.cookies.clear()
        try:
            response = await self._http.send(request, auth=None, follow_redirects=False, stream=True)
            self._check_generation(generation, uncertain=write)
            if response.status_code < 200 or response.status_code >= 300:
                raise MeijuError(
                    "http_error", f"The cloud returned HTTP {response.status_code}; no retry.", write
                )
            if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                raise MeijuError("unsupported_encoding", "The cloud returned an unsupported encoding.", write)
            size_header = response.headers.get("content-length")
            if size_header and (not size_header.isdecimal() or int(size_header) > MAX_RESPONSE_BYTES):
                raise MeijuError(
                    "response_too_large", "The cloud response exceeded the local size limit.", write
                )
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise MeijuError(
                        "response_too_large", "The cloud response exceeded the local size limit.", write
                    )
                data.extend(chunk)
            self._check_generation(generation, uncertain=write)
            try:
                envelope = json.loads(data, parse_constant=lambda _: None)
                if not isinstance(envelope, dict):
                    raise ValueError
                _server_code(envelope)
            except (ValueError, UnicodeError, RecursionError, MeijuError):
                raise MeijuError(
                    "malformed_response", "The cloud response was not valid protocol JSON.", write
                ) from None
            return envelope
        except MeijuError:
            raise
        except asyncio.CancelledError:
            if write:
                raise MeijuError(
                    "write_uncertain", "The write was interrupted; read status before trying again.", True
                ) from None
            raise
        except Exception:
            raise MeijuError(
                "write_uncertain" if write else "transport_error",
                "The request failed; no automatic retry. Its outcome may be unknown."
                if write
                else "The request failed; no automatic retry.",
                write,
            ) from None
        finally:
            self._http.cookies.clear()
            if response is not None:
                try:
                    await response.aclose()
                except asyncio.CancelledError:
                    if write:
                        raise MeijuError(
                            "write_uncertain",
                            "The write was interrupted; read status before trying again.",
                            True,
                        ) from None
                    raise
                except Exception:
                    pass
            # Closing a streamed connection can itself yield to logout. Check after
            # the final await, before any caller can commit a login or device list.
            self._check_generation(generation, uncertain=write)

    def _payload(self, envelope: dict[str, Any]) -> dict[str, Any]:
        code = _server_code(envelope)
        if code not in _SUCCESS:
            self._invalidate_expired_session(code)
            raise _rejection(code)
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise _malformed()
        return data

    def _invalidate_expired_session(self, code: str) -> None:
        if code in _EXPIRED_SESSION_CODES:
            self._generation += 1
            self._clear()
            raise MeijuError("session_expired", "The cloud session expired; sign in locally again.")

    @staticmethod
    def _mobile(mobile: str) -> None:
        if not isinstance(mobile, str) or re.fullmatch(r"1[0-9]{10}", mobile) is None:
            raise MeijuError("invalid_mobile", "Enter an 11-digit mainland China mobile number.")

    def _auth_stop(self, code: str) -> None:
        if code in _STOP:
            self._sms_issued_to = None
            self._pending_captcha = None
            raise MeijuError(
                _STOP[code], "Login stopped. Use the official Meiju app for this account condition."
            )

    async def request_sms(self, mobile: str, captcha: str | None = None) -> dict[str, Any]:
        generation = self._generation
        async with self._lock:
            self._check_generation(generation)
            if self._access_token is not None:
                return {"status": "authenticated", "authenticated": True}
            self._mobile(mobile)
            data: dict[str, Any] = {"deviceId": self._client_device_id, "imgCode": ""}
            if captcha is not None:
                if not isinstance(captcha, str) or not captcha.strip() or len(captcha) > 64:
                    raise MeijuError("invalid_captcha", "Enter the displayed image code manually.")
                if self._pending_captcha is None or self._pending_captcha[0] != mobile:
                    raise MeijuError(
                        "captcha_unavailable", "Request an image challenge for this login first."
                    )
                data.update(imgCode=captcha, randomToken=self._pending_captcha[1])
            self._sms_issued_to = None
            self._pending_captcha = None
            context = protocol.RequestContext.now()
            envelope = await self._request(
                protocol.SMS,
                protocol.auth_body(data, {"type": 9, "mobile": mobile, "iotAppId": "900"}, context),
                context,
            )
            code = _server_code(envelope)
            self._auth_stop(code)
            if code == "65011":
                image, token = self._captcha(envelope)
                self._pending_captcha = (mobile, token)
                return {"status": "captcha_required", "captcha_data_url": image}
            if code not in _SUCCESS:
                raise _rejection(code)
            self._sms_issued_to = mobile
            return {"status": "sms_sent"}

    @staticmethod
    def _captcha(envelope: dict[str, Any]) -> tuple[str, str]:
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise _malformed()
        encoded, token = data.get("imgCode"), data.get("randomToken")
        if not isinstance(encoded, str) or not isinstance(token, str) or not token or len(token) > 4096:
            raise _malformed()
        if encoded.startswith("data:"):
            match = re.fullmatch(r"data:image/(?:png|jpeg|gif|webp);base64,(.*)", encoded, re.DOTALL)
            if not match:
                raise _malformed()
            encoded = match[1]
        try:
            raw = base64.b64decode("".join(encoded.split()), validate=True)
        except (ValueError, binascii.Error):
            raise _malformed() from None
        mime = None
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "png"
        elif raw.startswith(b"\xff\xd8\xff"):
            mime = "jpeg"
        elif raw.startswith((b"GIF87a", b"GIF89a")):
            mime = "gif"
        elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            mime = "webp"
        if mime is None or len(raw) > 512 * 1024:
            raise _malformed()
        return f"data:image/{mime};base64,{base64.b64encode(raw).decode('ascii')}", token

    async def verify_sms(self, mobile: str, code: str) -> dict[str, Any]:
        generation = self._generation
        async with self._lock:
            self._check_generation(generation)
            if self._access_token is not None:
                return {"status": "authenticated", "authenticated": True}
            self._mobile(mobile)
            if self._sms_issued_to != mobile:
                raise MeijuError(
                    "sms_not_requested", "Request an SMS for this login before entering its code."
                )
            if not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None:
                raise MeijuError("invalid_sms_code", "Enter the six-digit SMS code.")
            context = protocol.RequestContext.now()
            envelope = await self._request(
                protocol.LOGIN,
                protocol.auth_body(
                    {
                        "appKey": protocol.MUC_APP_KEY,
                        "appVersion": protocol.APP_VERSION,
                        "deviceId": self._client_device_id,
                        "deviceName": "Meiju MCP Python",
                        "osVersion": "Python",
                        "platform": 2,
                    },
                    {
                        "mobile": mobile,
                        "smsCode": code,
                        "iotAppId": "900",
                        "appVersion": protocol.APP_VERSION,
                        "deviceId": self._client_device_id,
                        "loginType": 0,
                    },
                    context,
                ),
                context,
            )
            self._auth_stop(_server_code(envelope))
            payload = self._payload(envelope)
            mdata = payload.get("mdata")
            token = mdata.get("accessToken") if isinstance(mdata, dict) else None
            if (
                not isinstance(token, str)
                or not token
                or len(token) > 4096
                or not all(33 <= ord(c) <= 126 for c in token)
            ):
                raise _malformed()
            self._access_token = token
            self._sms_issued_to = None
            self._pending_captcha = None
            return {"status": "authenticated", "authenticated": True}

    async def _read(self, alias: str, fields: dict[str, Any]) -> dict[str, Any]:
        context = protocol.RequestContext.now()
        return self._payload(
            await self._request(
                alias,
                {**fields, "reqId": context.outer_request_id, "stamp": context.stamp},
                context,
                authenticated=True,
            )
        )

    async def list_devices(self) -> dict[str, Any]:
        generation = self._generation
        async with self._lock:
            self._check_generation(generation)
            self._require_auth()
            return await self._refresh_devices()

    async def _refresh_devices(self) -> dict[str, Any]:
        # Commit a new authority set only after every permitted home was successfully parsed.
        self._devices.clear()
        payload = await self._read(protocol.HOMES, {"devicePermissions": True})
        homes = payload.get("homeList")
        if not isinstance(homes, list):
            raise _malformed()
        home_ids = [
            _identifier(home.get("homegroupId")) if isinstance(home, dict) else _identifier(None)
            for home in homes
        ]
        if len(home_ids) != len(set(home_ids)):
            raise _malformed()
        home_names = {home_id: _display(home.get("name")) for home_id, home in zip(home_ids, homes)}
        refreshed: dict[str, _Device] = {}
        seen: set[str] = set()
        for home_id in home_ids:
            result = await self._read(protocol.DEVICES, {"homegroupId": home_id})
            returned_homes = result.get("homeList")
            if not isinstance(returned_homes, list):
                raise _malformed()
            matching = []
            for home in returned_homes:
                if not isinstance(home, dict):
                    raise _malformed()
                if _identifier(home.get("homegroupId")) == home_id:
                    matching.append(home)
            if len(matching) != 1 or not isinstance(matching[0].get("roomList"), list):
                raise _malformed()
            for room in matching[0]["roomList"]:
                if not isinstance(room, dict):
                    raise _malformed()
                appliances = room.get("applianceList", [])
                if appliances is None:
                    appliances = []
                if not isinstance(appliances, list):
                    raise _malformed()
                for appliance in appliances:
                    if not isinstance(appliance, dict):
                        raise _malformed()
                    server_id = _identifier(appliance.get("applianceCode"))
                    if server_id in seen:
                        raise _malformed()
                    seen.add(server_id)
                    opaque = self._device_ids.setdefault(server_id, "dev_" + uuid.uuid4().hex)
                    raw_type = appliance.get("type")
                    air_conditioner = profiles.is_ac(raw_type)
                    device_type = "0xAC" if air_conditioner else _display(raw_type)
                    sn8 = appliance.get("sn8")
                    if type(sn8) is int:
                        sn8 = str(sn8)
                    if not isinstance(sn8, str) or re.fullmatch(r"[a-zA-Z0-9]{8}", sn8) is None:
                        sn8 = None
                    online = appliance.get("onlineStatus")
                    public = {
                        "device_id": opaque,
                        "name": _display(appliance.get("name"), "Unnamed device"),
                        "home_name": home_names[home_id],
                        "room_name": _display(room.get("name")),
                        "model": _display(appliance.get("productModel")),
                        "type": device_type,
                        "sn8": sn8,
                        "online": True
                        if type(online) in {str, int} and online in {"1", 1}
                        else False
                        if type(online) in {str, int} and online in {"0", 0}
                        else None,
                        "profile": profiles.PROFILE_ID if air_conditioner else None,
                    }
                    refreshed[opaque] = _Device(server_id, air_conditioner, public)
        self._devices = refreshed
        return {"devices": [dict(device.public) for device in refreshed.values()]}

    def _device(self, device_id: str) -> _Device:
        self._require_auth()
        if not isinstance(device_id, str) or device_id not in self._devices:
            raise MeijuError("device_not_available", "Select a device from a fresh account device list.")
        device = self._devices[device_id]
        if not device.is_air_conditioner:
            raise MeijuError(
                "unsupported_device_type", "Only experimental 0xAC air-conditioner controls are available."
            )
        return device

    async def _state(self, device_id: str) -> dict[str, Any]:
        device = self._device(device_id)
        payload = await self._read(
            protocol.STATUS, {"applianceCode": device.server_id, "command": {"query": {}}}
        )
        if not payload:
            raise MeijuError("empty_status", "The cloud returned no state fields.")
        return {
            "device_id": device_id,
            **profiles.parse_state(payload),
            "source": "cloud",
            "freshness": "unknown",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "execution_verified": False,
        }

    async def get_status(self, device_id: str) -> dict[str, Any]:
        generation = self._generation
        async with self._lock:
            self._check_generation(generation)
            return await self._state(device_id)

    async def get_capabilities(self, device_id: str) -> dict[str, Any]:
        generation = self._generation
        async with self._lock:
            self._check_generation(generation)
            state = await self._state(device_id)
            return {"device_id": device_id, **profiles.capabilities(state)}

    async def control(
        self,
        device_id: str,
        *,
        power: bool | None = None,
        target_temperature: float | None = None,
        mode: str | None = None,
        fan_speed: str | None = None,
    ) -> dict[str, Any]:
        generation = self._generation
        async with self._lock:
            self._check_generation(generation)
            try:
                changes = profiles.validate_changes(
                    power=power, target_temperature=target_temperature, mode=mode, fan_speed=fan_speed
                )
            except ValueError:
                raise MeijuError(
                    "invalid_control",
                    "Supply valid candidate controls: temperature 17–30°C in 0.5°C steps, "
                    "power boolean, a listed mode or fan speed; at least one field is required.",
                ) from None
            self._device(device_id)
            await self._refresh_devices()
            device = self._device(device_id)
            state = await self._state(device_id)
            if any(state.get(field) is None for field in changes):
                raise MeijuError(
                    "unobserved_field",
                    "A requested field is unrecognized in the fresh cloud state; no write sent.",
                )
            context = protocol.RequestContext.now()
            envelope = await self._request(
                protocol.CONTROL,
                {
                    "applianceCode": device.server_id,
                    "command": {"control": profiles.control_fields(changes)},
                    "reqId": context.outer_request_id,
                    "stamp": context.stamp,
                },
                context,
                authenticated=True,
                write=True,
            )
            code = _server_code(envelope)
            # Unlike read/login, the write contract accepts only numerical zero.
            if re.fullmatch(r"[+-]?[0-9]{1,16}", code) is None:
                raise MeijuError(
                    "write_uncertain",
                    "The write acknowledgement was malformed; read status before retrying.",
                    True,
                )
            if int(code) != 0:
                self._invalidate_expired_session(code)
                raise _rejection(code)
            if "data" in envelope and envelope["data"] is None:
                raise MeijuError(
                    "write_uncertain",
                    "The write acknowledgement was malformed; read status before retrying.",
                    True,
                )
            try:
                readback = await self._state(device_id)
                matches = [
                    None if readback.get(field) is None else readback[field] == value
                    for field, value in changes.items()
                ]
                verification = (
                    "unavailable" if None in matches else "cloud_match" if all(matches) else "cloud_differs"
                )
                readback_error = None
            except MeijuError as error:
                readback, verification, readback_error = None, "unavailable", error.as_dict()
            except asyncio.CancelledError:
                raise MeijuError(
                    "write_uncertain", "The write was acknowledged but its readback was interrupted.", True
                ) from None
            return {
                "device_id": device_id,
                "acknowledged": True,
                "requested": changes,
                "verification": verification,
                "readback": readback,
                "readback_error": readback_error,
                "execution_verified": False,
                "message": "A cloud ACK and possibly cached readback do not verify physical device execution.",
            }

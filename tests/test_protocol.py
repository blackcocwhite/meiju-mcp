import hashlib
import hmac
import json

import pytest

from meiju_mcp import protocol


def test_signature_independent_golden_vector_and_query_semantics():
    body = b'{"data":{"deviceId":"synthetic"},"iotData":{"type":9}}'
    digest = protocol.signature(
        body,
        "1791849600123",
        [
            ("z", "last"),
            ("alias", "/ignored"),
            ("a", "first"),
            ("b", None),
            ("a", "duplicate must be ignored"),
        ],
        mas_key="test-mas-key",
        iot_secret="test-iot-secret",
    )
    assert digest == "5d055f4f62fd1f7413f12271751d18fedf45832ecf1b0e0fd5e2ff2e3771d3d8"


def test_signed_bytes_are_exact_sent_utf8_and_alias_does_not_change_sign():
    context = protocol.RequestContext("1791849600123", "20261013000000", "a" * 32, "b" * 32)
    body = {"name": "卧室/空调", "devicePermissions": True}
    req = protocol.signed_request(protocol.HOMES, body, context=context, access_token="synthetic-token")
    expected = hmac.new(
        protocol.MAS_KEY.encode(),
        protocol.IOT_SECRET.encode() + req.content + context.random.encode(),
        hashlib.sha256,
    ).hexdigest()
    assert req.headers["sign"] == expected
    assert json.loads(req.content) == body
    assert "卧室/空调".encode() in req.content
    assert req.url.scheme == "https" and req.url.host == "mp-prod.smartmidea.net"
    assert req.url.path == "/mas/v5/app/proxy"
    assert list(req.url.params.multi_items()) == [("alias", protocol.HOMES)]
    assert req.headers["accessToken"] == "synthetic-token"
    assert req.headers["accept-encoding"] == "identity"
    assert "cookie" not in req.headers and "authorization" not in req.headers


@pytest.mark.parametrize("alias", ["/arbitrary", "https://evil.invalid", protocol.STATUS + "?x=1"])
def test_protocol_rejects_any_seventh_endpoint(alias):
    with pytest.raises(ValueError):
        protocol.signed_request(alias, {}, context=protocol.RequestContext.now())
    assert len(protocol.ALLOWED_ALIASES) == 6


@pytest.mark.parametrize("token", ["", "a\r\nb", "令牌", " " * 2, "a" * 4097])
def test_header_tokens_cannot_inject_headers(token):
    with pytest.raises(ValueError):
        protocol.signed_request(
            protocol.STATUS, {}, context=protocol.RequestContext.now(), access_token=token
        )


def test_java_utf16_query_order():
    # Java places the supplementary-plane key's leading surrogate before U+E000.
    expected = hmac.new(b"k", b"s{}" + "\U00010000a\ue000b".encode() + b"1", hashlib.sha256).hexdigest()
    assert (
        protocol.signature(b"{}", "1", [("\ue000", "b"), ("\U00010000", "a")], mas_key="k", iot_secret="s")
        == expected
    )


def test_json_refuses_nonfinite_values():
    with pytest.raises(ValueError):
        protocol.json_bytes({"bad": float("nan")})

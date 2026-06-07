"""OpenClaw device identity — load ~/.openclaw/identity and sign connect challenges."""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path


_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
_DEVICE_AUTH_PAYLOAD_VERSION = "v3"


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    public_key_pem: str
    private_key_pem: str


@dataclass(frozen=True)
class DeviceAuthToken:
    token: str
    role: str
    scopes: list[str]


def openclaw_state_dir() -> Path:
    return Path.home() / ".openclaw"


def load_device_identity(state_dir: Path | None = None) -> DeviceIdentity | None:
    root = state_dir or openclaw_state_dir()
    path = root / "identity" / "device.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        device_id = str(data.get("deviceId", "")).strip()
        public_pem = str(data.get("publicKeyPem", "")).strip()
        private_pem = str(data.get("privateKeyPem", "")).strip()
        if not device_id or not public_pem or not private_pem:
            return None
        return DeviceIdentity(
            device_id=device_id,
            public_key_pem=public_pem,
            private_key_pem=private_pem,
        )
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def load_device_auth_token(
    role: str = "operator",
    *,
    state_dir: Path | None = None,
) -> DeviceAuthToken | None:
    root = state_dir or openclaw_state_dir()
    path = root / "identity" / "device-auth.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        device_id = str(data.get("deviceId", "")).strip()
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
        entry = tokens.get(role) if isinstance(tokens, dict) else None
        if not isinstance(entry, dict):
            return None
        token = str(entry.get("token", "")).strip()
        if not token:
            return None
        scopes_raw = entry.get("scopes")
        scopes = (
            [str(s) for s in scopes_raw if isinstance(s, str)]
            if isinstance(scopes_raw, list)
            else []
        )
        identity = load_device_identity(root)
        if identity and device_id and identity.device_id != device_id:
            return None
        return DeviceAuthToken(token=token, role=role, scopes=scopes)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _base64url_decode(data: str) -> bytes:
    padded = data + "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _normalize_device_metadata(value: str | None) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    if not trimmed:
        return ""
    return re.sub(r"[A-Z]", lambda m: m.group(0).lower(), trimmed)


def _public_key_raw_from_pem(public_key_pem: str) -> bytes:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    spki = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if (
        len(spki) == len(_ED25519_SPKI_PREFIX) + 32
        and spki.startswith(_ED25519_SPKI_PREFIX)
    ):
        return spki[len(_ED25519_SPKI_PREFIX) :]
    return spki


def public_key_raw_base64url(public_key_pem: str) -> str:
    return _base64url_encode(_public_key_raw_from_pem(public_key_pem))


def build_device_auth_payload_v3(
    *,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    token: str | None,
    nonce: str,
    platform: str = "",
    device_family: str = "",
) -> str:
    return "|".join(
        [
            _DEVICE_AUTH_PAYLOAD_VERSION,
            device_id,
            client_id,
            client_mode,
            role,
            ",".join(scopes),
            str(signed_at_ms),
            token or "",
            nonce,
            _normalize_device_metadata(platform),
            _normalize_device_metadata(device_family),
        ]
    )


def sign_device_payload(private_key_pem: str, payload: str) -> str:
    from cryptography.hazmat.primitives import serialization

    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None,
    )
    signature = private_key.sign(payload.encode("utf-8"))
    return _base64url_encode(signature)


def build_device_connect_params(
    identity: DeviceIdentity,
    *,
    nonce: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signature_token: str | None,
    platform: str = "python",
    device_family: str = "",
) -> dict[str, str | int]:
    signed_at_ms = int(time.time() * 1000)
    payload = build_device_auth_payload_v3(
        device_id=identity.device_id,
        client_id=client_id,
        client_mode=client_mode,
        role=role,
        scopes=scopes,
        signed_at_ms=signed_at_ms,
        token=signature_token,
        nonce=nonce,
        platform=platform,
        device_family=device_family,
    )
    return {
        "id": identity.device_id,
        "publicKey": public_key_raw_base64url(identity.public_key_pem),
        "signature": sign_device_payload(identity.private_key_pem, payload),
        "signedAt": signed_at_ms,
        "nonce": nonce,
    }


def resolve_connect_auth(
    *,
    gateway_token: str | None,
    device_auth: DeviceAuthToken | None,
) -> tuple[dict[str, str], str | None, list[str] | None]:
    """
    Return (auth dict, signature_token, preferred_scopes).
    Mirrors OpenClaw gateway-client precedence: gateway token first, device token fallback.
    """
    auth: dict[str, str] = {}
    signature_token: str | None = None
    preferred_scopes: list[str] | None = None

    gateway_token = (gateway_token or "").strip() or None
    device_token = device_auth.token if device_auth else None

    if gateway_token:
        auth["token"] = gateway_token
        signature_token = gateway_token
    elif device_token:
        auth["deviceToken"] = device_token
        signature_token = device_token
        preferred_scopes = device_auth.scopes if device_auth else None

    if gateway_token and device_token:
        auth["deviceToken"] = device_token
        if device_auth and device_auth.scopes:
            preferred_scopes = device_auth.scopes

    return auth, signature_token, preferred_scopes


def ensure_device_identity_available() -> DeviceIdentity:
    from xhaus.core.connector.gateway_ws import GatewayWsError

    identity = load_device_identity()
    if identity is None:
        raise GatewayWsError(
            "未找到 OpenClaw 设备身份 (~/.openclaw/identity/device.json)。"
            "请先在本机运行 openclaw 完成配对。"
        )
    return identity

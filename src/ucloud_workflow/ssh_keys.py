from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .client import UCloudClient
from .resources import ManagementError, browse_all, management_call, recorded_create
from .settings import Settings


def key_material(public_key: str) -> tuple[str, bytes]:
    if not isinstance(public_key, str) or "PRIVATE KEY" in public_key or "-----BEGIN" in public_key:
        raise ValueError("Only an OpenSSH public key is accepted; private keys must never be uploaded")
    lines = public_key.strip().splitlines()
    if len(lines) != 1:
        raise ValueError("Supply exactly one OpenSSH public key")
    fields = lines[0].split()
    if len(fields) < 2 or fields[0] not in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}:
        raise ValueError("Unsupported OpenSSH public-key format")
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid public-key encoding") from None
    algorithm = fields[0].encode("ascii")
    if len(blob) < 4 or int.from_bytes(blob[:4], "big") != len(algorithm) or blob[4:4 + len(algorithm)] != algorithm:
        raise ValueError("Public-key algorithm does not match its encoded data")
    return fields[0], blob


def key_fingerprint(public_key: str) -> str:
    _, blob = key_material(public_key)
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def read_public_key(path: Path) -> str:
    if path.suffix != ".pub":
        raise ValueError("Select a .pub file, never a private-key file")
    if path.stat().st_size > 65536:
        raise ValueError("Public-key file exceeds the size limit")
    public_key = path.read_text(encoding="utf-8").strip()
    validate_public_key(public_key)
    return public_key


def validate_public_key(public_key: str) -> None:
    key_material(public_key)
    with tempfile.TemporaryDirectory(prefix="ucloud-public-key-") as temporary:
        public_file = Path(temporary) / "key.pub"
        public_file.write_text(public_key + "\n", encoding="utf-8")
        try:
            result = subprocess.run(["ssh-keygen", "-l", "-f", str(public_file)], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            raise ManagementError("Public-key validation could not complete using ssh-keygen") from None
        if result.returncode:
            raise ValueError("ssh-keygen rejected the public key")


def list_ssh_keys(client: UCloudClient) -> list[dict[str, Any]]:
    return browse_all(client.browse_ssh_keys)


def ssh_key_summary(key: dict[str, Any]) -> dict[str, Any]:
    specification = key.get("specification") or {}
    try:
        fingerprint = key_fingerprint(specification.get("key", ""))
    except ValueError:
        fingerprint = None
    return {"id": key.get("id"), "title": specification.get("title"), "created_at": key.get("createdAt"), "fingerprint": fingerprint}


def check_ssh_key(client: UCloudClient, settings: Settings, public_key_path: Path | None = None) -> dict[str, Any]:
    if public_key_path is not None:
        paths = [public_key_path]
    else:
        paths = [identity.with_name(identity.name + ".pub") for identity in settings.resolved_ssh_identity_files()]
        paths = [path for path in paths if path.is_file()]
    if not paths:
        return {"state": "UNVERIFIABLE", "matches": [], "reason": "No public-key file found; SSH-agent authentication may still work"}
    local = [read_public_key(path) for path in paths]
    registered = list_ssh_keys(client)
    local_material = {key_material(value) for value in local}
    matches = []
    for key in registered:
        try:
            material = key_material((key.get("specification") or {}).get("key", ""))
        except ValueError:
            continue
        if material in local_material:
            matches.append(ssh_key_summary(key))
    return {"state": "MATCHED" if matches else "NOT_REGISTERED", "matches": matches}


def register_public_key(client: UCloudClient, title: str, public_key: str, *, operation_dir: Path = Path("artifacts/resource-operations")) -> dict[str, Any]:
    validate_public_key(public_key)
    material = key_material(public_key)
    if not title.strip():
        raise ValueError("Key title must not be empty")
    for key in list_ssh_keys(client):
        try:
            existing = key_material((key.get("specification") or {}).get("key", ""))
        except ValueError:
            continue
        if existing == material:
            return {**ssh_key_summary(key), "already_registered": True}
    result = recorded_create(lambda: client.register_ssh_key(title.strip(), public_key), namespace="ssh", project=None,
                             operation_dir=operation_dir)
    return {**result, "fingerprint": key_fingerprint(public_key), "already_registered": False}


def delete_public_key(client: UCloudClient, key_id: str) -> dict[str, Any]:
    if not key_id or not any(str(key.get("id")) == key_id for key in list_ssh_keys(client)):
        raise ManagementError("SSH key is not registered to the authenticated account")
    management_call(client.delete_ssh_key, key_id)
    return {"id": key_id, "deleted": True}

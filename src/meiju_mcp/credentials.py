"""Bounded, allowlisted OS credential access in a short-lived helper process.

Only a random encryption key crosses this pipe. Never place secrets in argv,
logging, environment variables, or exception messages. No backend auto-discovery.
"""

from __future__ import annotations

import json
import subprocess
import sys


class CredentialUnavailable(Exception):
    def __init__(self):
        super().__init__("The operating system credential store is unavailable or locked.")


class SystemVault:
    def call(self, action: str, service: str, value: str | None = None) -> str | None:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "meiju_mcp.credentials"],
                input=json.dumps({"action": action, "service": service, "value": value}),
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=12,
                check=False,
            )
            data = json.loads(result.stdout)
            if result.returncode != 0 or data.get("ok") is not True:
                raise ValueError
            answer = data.get("value")
            if answer is not None and (not isinstance(answer, str) or len(answer) > 128):
                raise ValueError
            return answer
        except Exception:
            raise CredentialUnavailable() from None


def _backend():
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring

        # SecItemAdd generic-password items are non-synchronizing by default.
        # keyring 25's keychain-path option is ignored, so do not pretend to set it.
        return Keyring()
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring

        backend = WinVaultKeyring()
        backend.persist = 2  # CRED_PERSIST_LOCAL_MACHINE, still current-user scoped.
        return backend
    if sys.platform.startswith("linux"):
        from keyring.backends.SecretService import Keyring

        return Keyring()
    raise CredentialUnavailable()


def main():
    try:
        data = json.loads(sys.stdin.read(4096))
        service = data["service"]
        if not isinstance(service, str) or not service.startswith("meiju-mcp.local.") or len(service) > 128:
            raise ValueError
        backend = _backend()
        action = data["action"]
        result = None
        if action == "get":
            result = backend.get_password(service, "encryption-key")
        elif action == "set":
            value = data["value"]
            if not isinstance(value, str) or len(value) != 44:
                raise ValueError
            backend.set_password(service, "encryption-key", value)
        elif action == "delete":
            if backend.get_password(service, "encryption-key") is not None:
                backend.delete_password(service, "encryption-key")
        else:
            raise ValueError
        print(json.dumps({"ok": True, "value": result}))
    except BaseException:
        # Backend exceptions can include identifying metadata; never print them.
        print('{"ok":false}')
        sys.exit(1)


if __name__ == "__main__":
    main()

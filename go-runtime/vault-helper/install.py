"""Create-only fixed-helper installation. Default is a read-only plan; no Keychain APIs."""

import argparse
import ctypes
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--install", action="store_true")
args = parser.parse_args()
repo = pathlib.Path(__file__).resolve().parents[2]
source = repo / ".cache/vault-helper-stage"
destination = pathlib.Path.home() / "Library/Application Support/MeijuMCP/VaultHelper"
manifest = json.loads((source / "installation.json").read_text())
app = source / "MeijuVaultHelper.app"
binary = app / "Contents/MacOS/MeijuVaultHelper"
assert manifest["identifier"] == "local.meiju.mcp.vault-helper" and manifest["backend"] == "meiju-vault-v1"
assert hashlib.sha256(binary.read_bytes()).hexdigest() == manifest["sha256"]
assert not any(p.is_symlink() for p in app.rglob("*"))
subprocess.run(
    [
        "/usr/bin/codesign",
        "--verify",
        "--strict",
        "-R",
        '=identifier "local.meiju.mcp.vault-helper"',
        str(app),
    ],
    check=True,
)
print(
    json.dumps(
        {
            "source": str(source),
            "destination": str(destination),
            "sha256": manifest["sha256"],
            "will_access_keychain": False,
            "mode": "install" if args.install else "plan",
        },
        ensure_ascii=False,
    )
)
if not args.install:
    raise SystemExit(0)
if destination.exists() or destination.is_symlink():
    raise SystemExit("Refusing to replace an installed helper or change its pinned identity.")
for parent in destination.parents:
    if parent.is_symlink():
        raise SystemExit("Refusing a redirected installation path.")
destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
if destination.parent.stat().st_uid != os.getuid() or destination.parent.stat().st_mode & 0o077:
    raise SystemExit("Installation parent is not private and user-owned; refusing to change its permissions.")
with tempfile.TemporaryDirectory(prefix=".vault-stage-", dir=destination.parent) as temp:
    staging = pathlib.Path(temp) / "VaultHelper"
    staging.mkdir(mode=0o700)
    shutil.copytree(app, staging / app.name)
    (staging / app.name / "Contents/MacOS/MeijuVaultHelper").chmod(0o700)
    (staging / "installation.json").write_text(json.dumps(manifest, indent=2))
    (staging / "installation.json").chmod(0o600)
    subprocess.run(
        [
            "/usr/bin/codesign",
            "--verify",
            "--strict",
            "-R",
            '=identifier "local.meiju.mcp.vault-helper"',
            str(staging / app.name),
        ],
        check=True,
    )
    # macOS RENAME_EXCL is atomic: even an empty directory created by another
    # installer must not be replaced between an existence check and rename.
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    rename = libc.renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(os.fsencode(staging), os.fsencode(destination), 0x00000004) != 0:
        raise OSError(ctypes.get_errno(), "Create-only helper installation failed")
print("Fixed helper files installed. No credential was read, created, deleted, or authorized.")

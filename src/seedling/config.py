from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import paths

# Every key seedling understands, with a description shown by `seed config`.
# Anything else in settings.json is preserved but flagged as unknown.
KNOWN_KEYS: dict[str, str] = {
    "default_base": (
        "Base Python tag `seed venv` builds from when --python isn't given "
        "(e.g. \"312\"). Set automatically by the first `seed python` install."),
    "default_venv": (
        "Venv name every new shell auto-activates on startup. Empty/null "
        "means no auto-activation."),
    "auto_activate": (
        "Whether new shells auto-activate `default_venv` at startup. "
        "true/false (default true). Toggle with `seed auto-activate "
        "True|False`; when false, a default_venv is left set but not "
        "activated automatically."),
    "update_source": (
        "Where `seed update-commands` fetches seedling's own source from: a "
        "git URL (including self-hosted GitHub/GitLab on another network) "
        "OR a plain directory path (e.g. a mounted network drive holding a "
        "copy of the repo). Recorded automatically at install time. "
        "Empty/null means updates can only reinstall the existing copy."),
    "venv_default_packages": (
        "Packages installed into every new venv (list). Skip per-venv with "
        "`seed venv <name> --no-default-packages`."),
    "python_mirror": (
        "Where `seed python` downloads interpreter builds from, instead of "
        "the internet: a URL or a directory of python-build-standalone "
        "archives (e.g. a network share). Applied to every uv call as "
        "UV_PYTHON_INSTALL_MIRROR. Empty/null means the internet."),
    "package_index": (
        "Where packages install from, instead of pypi.org: an index URL "
        "(Artifactory/Nexus/devpi), or a plain directory of wheels (e.g. a "
        "network share -- becomes the one and only package source, with "
        "the internet index disabled). Empty/null means pypi.org."),
    "native_tls": (
        "Use the operating system's certificate trust store for HTTPS "
        "instead of the bundled one -- for internal mirrors/indexes whose "
        "corporate CA is installed machine-wide by IT. true/false."),
    "ca_cert": (
        "Path to a PEM CA bundle trusted for HTTPS (uv downloads, git "
        "clones, and seedling's own downloads). Normally installed "
        "automatically from vendor/certs/ in the distributed repo copy."),
    "shared_root": (
        "The directory holding per-user seedling homes, recorded at install "
        "time when SEEDLING_HOME_DIR used a {user} token. Only set for "
        "shared multi-user installs; enables the admin-* commands."),
    "vscode_flavor": (
        "Which editor build `seed vscode` installs: \"microsoft\" (the "
        "official VS Code build, Microsoft's proprietary licence) or "
        "\"vscodium\" (the MIT-licensed community build, freely "
        "redistributable and preconfigured for the Open VSX registry). "
        "Changing this only affects the NEXT install -- rerun "
        "`seed vscode --reinstall` to switch an existing one."),
    "extension_gallery": (
        "Where the editor installs extensions from, instead of its build's "
        "default registry: a base URL (e.g. \"https://open-vsx.org/vscode\", "
        "or an internal Open VSX mirror). Empty/null means the flavor's own "
        "default -- Microsoft Marketplace for \"microsoft\", Open VSX for "
        "\"vscodium\"."),
    "vscode_extensions": (
        "Extensions installed into a fresh editor (list). Empty/null means "
        "the built-in starter kit for the configured flavor. Set to an empty "
        "list to install none at all."),
    "profile": (
        "Path to the deployment profile `seed apply` uses by default -- the "
        "TOML file describing the interpreters, venvs, packages and repos "
        "this deployment expects. Recorded at install time from "
        "SEEDLING_PROFILE. Empty/null means `seed apply` looks for "
        "seedling-profile.toml in the current directory instead."),
}

_DEFAULTS: dict[str, Any] = {
    "default_base": None,
    "default_venv": None,
    "auto_activate": True,
    "update_source": None,
    "venv_default_packages": ["ipython", "ruff", "ipykernel"],
    "python_mirror": None,
    "package_index": None,
    "native_tls": None,
    "ca_cert": None,
    "shared_root": None,
    "vscode_flavor": "microsoft",
    "extension_gallery": None,
    "vscode_extensions": None,
    "profile": None,
}


def apply_runtime_env() -> None:
    """Translate the TLS settings into THIS process's environment, once per
    invocation (cli calls it before dispatching any command). Process-wide
    rather than per-subprocess because three different consumers read the
    same variables: uv (child process), git (child process), and seedling's
    own urllib downloads (this process). Values already present in the
    user's environment always win."""
    ca_cert = get("ca_cert")
    if ca_cert and Path(str(ca_cert)).expanduser().is_file():
        os.environ.setdefault("SSL_CERT_FILE", str(ca_cert))
        os.environ.setdefault("GIT_SSL_CAINFO", str(ca_cert))
    if get("native_tls"):
        os.environ.setdefault("UV_NATIVE_TLS", "1")


def load() -> dict[str, Any]:
    paths.ensure_layout()
    if not paths.CONFIG_FILE.exists():
        return dict(_DEFAULTS)
    try:
        # utf-8-sig, not utf-8: install.ps1 seeds settings.json via PowerShell
        # 5.1's `Set-Content -Encoding UTF8`, which writes a UTF-8 BOM. Reading
        # that as plain utf-8 leaves a leading BOM that makes json.loads fail
        # ("Expecting value: line 1 column 1"), silently discarding every
        # conf-seeded setting. utf-8-sig strips a BOM and is a no-op without one.
        data = json.loads(paths.CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        data = {}
    merged = dict(_DEFAULTS)
    merged.update(data)
    return merged


def save(data: dict[str, Any]) -> None:
    paths.ensure_layout()
    paths.CONFIG_FILE.write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def get(key: str) -> Any:
    return load().get(key)


def set_value(key: str, value: Any) -> None:
    data = load()
    data[key] = value
    save(data)


def unset(key: str) -> None:
    """Reset a key back to its built-in default."""
    data = load()
    data[key] = _DEFAULTS.get(key)
    save(data)


def default_of(key: str) -> Any:
    return _DEFAULTS.get(key)


def is_multi_user() -> bool:
    """True when this is a shared multi-user install -- i.e. SEEDLING_HOME_DIR
    used a {user} token, so `shared_root` was recorded at install time.
    Deliberately side-effect-free (reads the file directly, never creates
    the layout) so it's safe to call from the help path."""
    try:
        if not paths.CONFIG_FILE.exists():
            return False
        return bool(json.loads(
            paths.CONFIG_FILE.read_text(encoding="utf-8-sig")).get("shared_root"))
    except (json.JSONDecodeError, OSError):
        return False


def set_default_base(tag: str) -> None:
    set_value("default_base", tag)


def get_default_base() -> str | None:
    return load().get("default_base")

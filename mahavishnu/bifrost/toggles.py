"""Single toggle state machine for Bifrost client harnesses.

req: REQ-BIFROST-025, REQ-BIFROST-026, REQ-BIFROST-027, REQ-BIFROST-028, REQ-BIFROST-029

Replaces the separate ``scripts/bifrost-toggle-claude-url`` and
``scripts/bifrost-toggle-qwen-url`` with one implementation parameterised by a
:class:`~mahavishnu.bifrost.models.HarnessDescriptor`.

Two defects in the retired scripts are fixed here:

1. Neither wrote a credential -- only a base URL. Because Bifrost reads the
   virtual key exclusively from the ``x-bf-vk`` header, both harnesses
   reached the gateway and were rejected with ``401 virtual key is required``.
2. The gate ``BIFROST_CTL_NO_CC_URL_REWRITE`` lived only in the shell wrapper
   ``scripts/bifrost-ctl``, leaving this Python path as an unguarded side door
   around the operator's own opt-out. It is enforced here now.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import typer

from .models import VIRTUAL_KEY_ENV, VIRTUAL_KEY_HEADER, HarnessDescriptor
from .paths import DEFAULT_BIFROST_HOST, DEFAULT_BIFROST_PORT

GATE_ENV = "BIFROST_CTL_NO_CC_URL_REWRITE"

CC_CUSTOM_HEADERS_VAR = "ANTHROPIC_CUSTOM_HEADERS"

#: Bifrost serves each wire protocol at a distinct path. A Qwen model bound
#: to the ``anthropic`` provider must be pointed at the Anthropic-compatible
#: endpoint, not the OpenAI-compatible one -- the two are not interchangeable
#: and a mismatch 404s every completion.
_BIFROST_PATH_BY_PROVIDER: dict[str, str] = {"anthropic": "/anthropic", "openai": "/v1"}

#: Upstream each provider entry pointed at before the toggle ran, restored on
#: ``qwen-url direct``. These are the endpoints Qwen Code ships with for the
#: providers this deployment uses; a provider with no entry here is left
#: holding its Bifrost URL and reported, so nothing is silently invented.
_BIFROST_UPSTREAMS: dict[str, str] = {
    "anthropic": "https://api.minimax.io/anthropic",
    "openai": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

EXIT_OK = 0
EXIT_ERROR = 2


# --------------------------------------------------------------------------
# model-provider resolution (Qwen Code)
# --------------------------------------------------------------------------


def _active_provider(settings: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Locate the ``modelProviders`` entry backing the active model.

    Qwen Code resolves ``model.name`` against ``modelProviders`` before it
    consults ``model.generationConfig``. When a provider entry matches, the
    generic ``generationConfig`` block is **ignored** -- it emits

        Warning: model.generationConfig.customHeaders is ignored for
        provider model "MiniMax-M3" from modelProviders.anthropic. Move
        this field to modelProviders.anthropic[].generationConfig

    so a toggle that writes only the generic block reports success while the
    harness keeps talking straight to the upstream provider. Verified
    end-to-end: with only the generic block written, Qwen answered but
    Bifrost logged no row; repointing the matching provider entry produced
    two ``success`` rows on the virtual key.

    Returns ``(provider_key, entry)`` for the match, or ``(None, None)`` when
    the active model is a bare string or matches no provider -- the case the
    generic block does serve.
    """
    model = settings.get("model")
    if not isinstance(model, dict):
        return None, None
    name = model.get("name")
    providers = settings.get("modelProviders")
    if not isinstance(name, str) or not isinstance(providers, dict):
        return None, None
    for provider_key, entries in providers.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("name") == name:
                return provider_key, entry
    return None, None


def provider_bifrost_url(settings: dict[str, Any], host: str, port: int) -> str | None:
    """Bifrost URL matching the active model's wire protocol, or ``None``.

    ``None`` means the active model has no provider entry, so the caller
    should fall back to the harness's generic endpoint.
    """
    provider_key, _ = _active_provider(settings)
    if provider_key is None:
        return None
    suffix = _BIFROST_PATH_BY_PROVIDER.get(provider_key)
    if suffix is None:
        return None
    return f"http://{host}:{port}{suffix}"


# --------------------------------------------------------------------------
# settings.json I/O
# --------------------------------------------------------------------------


def _read_settings(path: Path) -> dict[str, Any]:
    """Load a harness settings file, treating absence as empty."""
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        typer.echo(f"error: {path} is not valid JSON: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc
    return loaded if isinstance(loaded, dict) else {}


def _write_settings(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def _env_block(settings: dict[str, Any]) -> dict[str, Any]:
    """Return ``settings["env"]``, creating or repairing it as a dict."""
    env = settings.setdefault("env", {})
    if not isinstance(env, dict):
        typer.echo("error: settings 'env' is not an object", err=True)
        raise typer.Exit(EXIT_ERROR)
    return env


def _get_url(settings: dict[str, Any], harness: HarnessDescriptor) -> str | None:
    _, entry = _active_provider(settings)
    if entry is not None:
        value = entry.get("baseUrl")
        return value if isinstance(value, str) else None
    value = _env_block(settings).get(harness.url_env_var)
    return value if isinstance(value, str) else None


def _set_url(settings: dict[str, Any], harness: HarnessDescriptor, url: str) -> None:
    _, entry = _active_provider(settings)
    if entry is not None:
        entry["baseUrl"] = url
        return
    _env_block(settings)[harness.url_env_var] = url


def _pop_url(settings: dict[str, Any], harness: HarnessDescriptor) -> None:
    _, entry = _active_provider(settings)
    if entry is not None:
        # Delete rather than blank: the caller may have a prior URL to
        # restore, and ``_get_url`` treats a missing key as "unset" while an
        # empty string would read as a configured-but-empty endpoint.
        entry.pop("baseUrl", None)
        return
    _env_block(settings).pop(harness.url_env_var, None)
    if not _env_block(settings):
        settings.pop("env", None)


# --------------------------------------------------------------------------
# credential sinks -- req: REQ-BIFROST-026 / REQ-BIFROST-027
# --------------------------------------------------------------------------


def _upsert_header_line(raw: str | None, header: str, value: str) -> str:
    """Return ``raw`` with ``header`` set to ``value``, preserving other lines.

    ``ANTHROPIC_CUSTOM_HEADERS`` is a newline-separated list, so appending is
    not safe either -- a prior ``x-bf-vk`` line must be dropped first or the
    header would be sent twice.
    """
    prefix = f"{header}:"
    kept = [
        line
        for line in (raw or "").splitlines()
        if line.strip() and not line.strip().startswith(prefix)
    ]
    kept.append(f"{header}: {value}")
    return "\n".join(kept)


def _set_credential(settings: dict[str, Any], harness: HarnessDescriptor, virtual_key: str) -> None:
    """Write the ``x-bf-vk`` header to the sink this harness actually reads.

    Claude Code takes ``ANTHROPIC_CUSTOM_HEADERS`` in ``Name: Value`` form
    (requires >= 2.1.227). Qwen Code takes ``customHeaders`` under
    ``model.generationConfig`` -- but only for a runtime model with **no**
    matching ``modelProviders`` entry. When the active model resolves to a
    provider, Qwen ignores that block and reads the header from the matching
    provider's own ``generationConfig``, so the header is written there. See
    :func:`_active_provider`.
    """
    if harness.credential_sink == "env":
        env = _env_block(settings)
        existing = env.get(CC_CUSTOM_HEADERS_VAR)
        env[CC_CUSTOM_HEADERS_VAR] = _upsert_header_line(
            existing if isinstance(existing, str) else None,
            VIRTUAL_KEY_HEADER,
            virtual_key,
        )
        return

    model = settings.setdefault("model", {})
    if not isinstance(model, dict):
        typer.echo("error: settings 'model' is not an object", err=True)
        raise typer.Exit(EXIT_ERROR)

    _, entry = _active_provider(settings)
    target = entry if entry is not None else model
    generation = target.setdefault("generationConfig", {})
    headers = generation.setdefault("customHeaders", {})
    headers[VIRTUAL_KEY_HEADER] = virtual_key


def _read_credential(settings: dict[str, Any], harness: HarnessDescriptor) -> str | None:
    """Return the currently-configured virtual key for ``harness``, if any."""
    if harness.credential_sink == "env":
        raw = _env_block(settings).get(CC_CUSTOM_HEADERS_VAR)
        if not isinstance(raw, str):
            return None
        prefix = f"{VIRTUAL_KEY_HEADER}:"
        for line in raw.splitlines():
            if line.strip().startswith(prefix):
                return line.strip()[len(prefix) :].strip()
        return None

    model = settings.get("model")
    if not isinstance(model, dict):
        return None
    _, entry = _active_provider(settings)
    target = entry if entry is not None else model
    generation = target.get("generationConfig")
    if not isinstance(generation, dict):
        return None
    headers = generation.get("customHeaders")
    if not isinstance(headers, dict):
        return None
    value = headers.get(VIRTUAL_KEY_HEADER)
    return value if isinstance(value, str) else None


def _pop_credential(settings: dict[str, Any], harness: HarnessDescriptor) -> None:
    """Remove only our header, leaving any other custom headers intact."""
    if harness.credential_sink == "env":
        env = _env_block(settings)
        raw = env.get(CC_CUSTOM_HEADERS_VAR)
        if isinstance(raw, str):
            kept = [
                ln for ln in raw.splitlines() if not ln.strip().startswith(f"{VIRTUAL_KEY_HEADER}:")
            ]
            if kept:
                env[CC_CUSTOM_HEADERS_VAR] = "\n".join(kept)
            else:
                env.pop(CC_CUSTOM_HEADERS_VAR, None)
        return

    model = settings.get("model")
    if not isinstance(model, dict):
        return
    _, entry = _active_provider(settings)
    target = entry if entry is not None else model
    generation = target.get("generationConfig")
    if not isinstance(generation, dict):
        return
    headers = generation.get("customHeaders")
    if not isinstance(headers, dict):
        return
    headers.pop(VIRTUAL_KEY_HEADER, None)
    if not headers:
        generation.pop("customHeaders", None)


# --------------------------------------------------------------------------
# backup -- tolerates the legacy plain-URL format written by the old scripts
# --------------------------------------------------------------------------


def _save_backup(
    harness: HarnessDescriptor,
    url: str | None,
    credential_present: bool,
    dry_run: bool,
) -> None:
    """Persist the pre-toggle URL and whether a key was already configured.

    The virtual key value is deliberately **never** written here. A backup
    file is plaintext, long-lived, and world-readable by default; parking a
    credential in it would leave a copy on disk after the toggle completes.
    Only the boolean is recorded, so ``direct`` can tell "there was nothing
    here" from "we overwrote something we deliberately do not back up".
    """
    payload: dict[str, Any] = {"url": url, "credential_present": credential_present}
    serialized = json.dumps(payload, indent=2)
    if dry_run:
        typer.echo(f"[dry-run] would save prior state to {harness.backup_path}")
        return
    harness.backup_path.parent.mkdir(parents=True, exist_ok=True)
    harness.backup_path.write_text(serialized + "\n", encoding="utf-8")
    harness.backup_path.chmod(0o600)
    typer.echo(f"saved prior {harness.label} state to {harness.backup_path}")


def _load_backup(harness: HarnessDescriptor) -> dict[str, str]:
    """Load the backup, accepting both JSON and the legacy bare-URL format."""
    if not harness.backup_path.exists():
        return {}
    raw = harness.backup_path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"url": raw}
    if not isinstance(data, dict):
        return {"url": raw}
    # Legacy backups written before the credential fix stored a secret under
    # "credential". Drop it on read so it does not linger in memory or get
    # copied forward; the file itself is rewritten by the next toggle.
    present = data.get("credential_present")
    if present is None:
        present = "true" if isinstance(data.get("credential"), str) else "false"
    return {"url": data.get("url"), "credential_present": str(bool(present)).lower()}


# --------------------------------------------------------------------------
# gate -- req: REQ-BIFROST-029
# --------------------------------------------------------------------------


def gate_blocks(action: str) -> bool:
    """True when the operator opted out of harness URL rewrites.

    Reads the *environment* first, then falls back to sourcing-aware shells.
    ``~/.zshenv`` historically carried this as a shell-local assignment
    (``BIFROST_CTL_NO_CC_URL_REWRITE=1`` with no ``export``), which a zsh
    script sees after sourcing but ``os.environ`` never does. Checking
    ``os.environ`` alone therefore silently ignored the gate for any
    non-zsh caller -- including this Typer app and the retired Python
    helpers -- letting them rewrite settings the operator had opted out of.
    """
    if os.environ.get(GATE_ENV, ""):
        return True

    for shell in ("/bin/zsh", "/bin/bash", "/bin/sh"):
        if not Path(shell).exists():
            continue
        try:
            # The shell expands $GATE_ENV itself; only the default is
            # substituted here so bash and zsh both parse it.
            probe = subprocess.run(
                [shell, "-c", 'printf %s "${' + GATE_ENV + ':-}"'],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except OSError, subprocess.SubprocessError:
            continue
        if probe.stdout.strip():
            return True
    return False


def _resolve_virtual_key(key_file: Path | None) -> str | None:
    """Resolve the virtual key from a file, then the environment.

    req: REQ-BIFROST-028 -- never hardcoded, never logged.

    There is deliberately **no** ``--virtual-key`` CLI option: argv is
    visible to any local user via ``ps``, and lands in shell history and
    terminal scrollback. The env var and a file are the only supported
    inputs.
    """
    if key_file and key_file.exists():
        text = key_file.read_text(encoding="utf-8").strip()
        return text or None
    env_value = os.environ.get(VIRTUAL_KEY_ENV, "").strip()
    return env_value or None


# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------


def _action_bifrost(
    harness: HarnessDescriptor,
    host: str,
    port: int,
    virtual_key: str | None,
    dry_run: bool,
    force: bool,
) -> None:
    settings = _read_settings(harness.settings_path)
    # A Qwen model bound to a provider must be repointed at the Bifrost
    # endpoint for that provider's wire protocol, not the harness default.
    provider_url = provider_bifrost_url(settings, host, port)
    url = provider_url or harness.bifrost_url(host, port)
    existing = _get_url(settings, harness)

    if existing == url and _read_credential(settings, harness) == virtual_key:
        typer.echo(f"{harness.label} already points at {url} with a matching key; no-op")
        return

    if existing != url or virtual_key:
        existing_key = _read_credential(settings, harness)
        if existing_key and existing_key != virtual_key and not force:
            typer.echo(
                f"refusing to overwrite an existing {VIRTUAL_KEY_HEADER} header on "
                f"{harness.label}: this toggle never persists credentials to "
                f"{harness.backup_path}, so the old value could not be restored. "
                f"Re-run with --force to discard it, or remove the header first.",
                err=True,
            )
            raise typer.Exit(EXIT_ERROR)
        _save_backup(harness, existing, existing_key is not None, dry_run)

    _set_url(settings, harness, url)
    if virtual_key:
        _set_credential(settings, harness, virtual_key)
    else:
        typer.echo(
            f"WARNING: no virtual key available (set {VIRTUAL_KEY_ENV} or pass "
            f"--virtual-key-file). {harness.label} will reach Bifrost but be "
            f"rejected with 401 until a key is configured.",
            err=True,
        )

    if dry_run:
        typer.echo(
            f"[dry-run] would point {_endpoint_label(settings, harness)} at {url} "
            f"in {harness.settings_path}"
        )
        return

    _write_settings(harness.settings_path, settings)
    typer.echo(f"wrote {_endpoint_label(settings, harness)}={url} in {harness.settings_path}")
    typer.echo(f"note: {harness.restart_note}")


def _action_direct(harness: HarnessDescriptor, dry_run: bool) -> None:
    settings = _read_settings(harness.settings_path)
    url = _get_url(settings, harness)
    existing_key = _read_credential(settings, harness)

    if url is None and existing_key is None:
        typer.echo(f"{_endpoint_label(settings, harness)} is unset; no-op")
        return

    # Compare against whichever endpoint this toggle would have written, so a
    # provider-routed Qwen model (``/anthropic``) is recognised as
    # Bifrost-managed rather than mistaken for a hand-set third-party URL.
    bifrost_url = provider_bifrost_url(settings, DEFAULT_BIFROST_HOST, DEFAULT_BIFROST_PORT)
    if bifrost_url is None:
        bifrost_url = harness.bifrost_url()

    if url is not None and url != bifrost_url:
        # The URL is hand-set, so do not clobber it. But a stranded
        # ``x-bf-vk`` header is a credential the harness will send to
        # whatever endpoint the operator pointed at -- in practice a provider
        # like api.minimax.io, which has no use for it. Leaving it behind
        # because the URL no longer matches turns a Bifrost-specific secret
        # into a third party's traffic. Drop it either way.
        if existing_key is None:
            typer.echo(f"{harness.url_env_var}={url!r} is not Bifrost-managed; leaving it alone")
            return
        if dry_run:
            typer.echo(
                f"[dry-run] would remove the stranded {VIRTUAL_KEY_HEADER} header "
                f"(no credential was persisted, so this cannot be undone)"
            )
            return
        _pop_credential(settings, harness)
        _write_settings(harness.settings_path, settings)
        typer.echo(
            f"removed stranded {VIRTUAL_KEY_HEADER} header; {harness.url_env_var}={url!r} "
            f"left untouched"
        )
        typer.echo(f"note: {harness.restart_note}")
        return

    backup = _load_backup(harness)
    prior_url = backup.get("url")
    had_credential = backup.get("credential_present") == "true"

    _pop_url(settings, harness)
    _pop_credential(settings, harness)

    if dry_run:
        typer.echo(f"[dry-run] would restore {harness.label} to {prior_url or '<unset>'}")
        return

    if prior_url:
        _set_url(settings, harness, prior_url)
    elif _active_provider(settings)[1] is not None:
        # No prior URL was recorded (the model had no provider entry when the
        # toggle first ran), so fall back to the shipped upstream for this
        # provider rather than leaving the entry pointed at Bifrost.
        provider_key, _ = _active_provider(settings)
        upstream = _BIFROST_UPSTREAMS.get(provider_key or "")
        if upstream:
            _set_url(settings, harness, upstream)
            typer.echo(f"restored {provider_key} provider upstream to {upstream}")
    if had_credential:
        typer.echo(
            f"note: a pre-existing {VIRTUAL_KEY_HEADER} header was removed. It was "
            f"not backed up (credentials are never persisted), so re-add it if "
            f"{harness.label} still needs it.",
            err=True,
        )

    _write_settings(harness.settings_path, settings)
    harness.backup_path.unlink(missing_ok=True)
    typer.echo(f"restored {harness.label} to {prior_url or '<removed>'} in {harness.settings_path}")
    typer.echo(f"note: {harness.restart_note}")


def _endpoint_label(settings: dict[str, Any], harness: HarnessDescriptor) -> str:
    """Name the setting that actually carries this harness's endpoint.

    A Qwen model bound to a ``modelProviders`` entry is routed through that
    entry's ``baseUrl``; only an unbound model uses the generic URL env var.
    Printing the env-var name for a provider-routed model would misreport what
    the toggle touched.
    """
    provider_key, entry = _active_provider(settings)
    if entry is None:
        return harness.url_env_var
    return f"modelProviders.{provider_key}.baseUrl"


def _action_status(harness: HarnessDescriptor) -> None:
    settings = _read_settings(harness.settings_path)
    url = _get_url(settings, harness)
    provider_url = provider_bifrost_url(settings, DEFAULT_BIFROST_HOST, DEFAULT_BIFROST_PORT)
    if provider_url is None:
        provider_url = harness.bifrost_url()
    label = _endpoint_label(settings, harness)
    if url is None:
        typer.echo(f"{label}: <unset>")
    elif url == provider_url:
        typer.echo(f"{label}: Bifrost ({url})")
    else:
        typer.echo(f"{label}: custom ({url})")

    credential = _read_credential(settings, harness)
    typer.echo(f"{VIRTUAL_KEY_HEADER} header: {'present' if credential else 'absent'}")
    typer.echo(
        f"backup at {harness.backup_path}: {'yes' if harness.backup_path.exists() else 'no'}"
    )


def credential_configured(harness: HarnessDescriptor) -> bool:
    """True when ``harness`` currently carries the virtual-key header."""
    return _read_credential(_read_settings(harness.settings_path), harness) is not None


def apply(
    harness: HarnessDescriptor,
    action: str,
    host: str = DEFAULT_BIFROST_HOST,
    port: int = DEFAULT_BIFROST_PORT,
    key_file: Path | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> int:
    """Run ``action`` against ``harness``. Returns a process exit code."""
    if action == "status":
        _action_status(harness)
        return EXIT_OK

    if gate_blocks(action):
        typer.echo(f"{GATE_ENV} is set; skipping {harness.label} URL rewrite (action={action})")
        return EXIT_OK

    resolved_key = _resolve_virtual_key(key_file)

    if action == "bifrost":
        _action_bifrost(harness, host, port, resolved_key, dry_run, force)
        return EXIT_OK
    if action == "direct":
        _action_direct(harness, dry_run)
        return EXIT_OK

    typer.echo(f"error: unknown action {action!r}; expected bifrost|direct|status", err=True)
    return EXIT_ERROR

#!/usr/bin/env python3
"""Render the container's OpenCode config from a service registry and env vars.

OpenCode needs three things from whatever serves the model: an OpenAI-compatible
base URL, a provider id, and the model ids. This script is the composition root
that turns those into an ``OPENCODE_CONFIG_CONTENT`` JSON blob, so neither the
container nor the docs are tied to one server or one model.

Inputs (environment variables):
    OPENCODE_MODEL     full ``<service>/<model>`` reference; highest priority
    MODEL_SERVICE      registry id to use (default: deepseek)
    MODEL_BASE_URL     explicit base URL; selects the ``custom`` service unless
                       MODEL_SERVICE is set
    MODEL_PORT         overrides the registry port
    MODEL_NAME         exact model id; empty means discover via GET /models
    SMALL_MODEL_NAME   small-model id (default: same as MODEL_NAME)
    MODEL_DISCOVER     ``0`` disables discovery; the registry defaultModel is used
    MODEL_API_KEY      provider API key for hosted endpoints (e.g. DeepSeek)

Modes:
    (default)          print the OpenCode config JSON
    --health-url       print the resolved ``{base_url}/models`` URL (empty when
                       the service sets ``healthCheck: false``)
    --list             print the resolved service, model and base URL
    --check            probe the model server; exit 1 when unreachable; skipped
                       when the service sets ``healthCheck: false``

Profiles (``--profile``):
    default            full tool permissions (an allow-all ``permissions``
                       rule): the container itself is the security boundary
    readonly           the agent may read files (never env files) and search
                       them, but cannot write, run shell commands, browse, or
                       ask questions - used by unattended runs such as the
                       Telegram bot answering untrusted forwarded text

The rendered config grants full tool permissions (an allow-all ``permissions``
rule): the container itself is the security boundary (see DOCKER.md), and the
agent is meant to run unattended. Remove the rules to get approval prompts back.

Exit codes: 0 success, 1 health check failed, 2 configuration error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

DEFAULT_SERVICE = "deepseek"
CUSTOM_SERVICE = "custom"
DEFAULT_TIMEOUT = 3.0
DEFAULT_PROFILE = "default"
READONLY_PROFILE = "readonly"
PROFILES = (DEFAULT_PROFILE, READONLY_PROFILE)

# Unattended runs answer untrusted text: reads stay, everything that could
# change the workspace, execute code, or reach the network is denied. V2 checks
# external_directory before read/edit, so the deny keeps the bot inside /work
# (the OpenCode auth file lives in the mounted home volume).
READONLY_PERMISSIONS = [
    {"action": "*", "resource": "*", "effect": "deny"},
    {"action": "read", "resource": "*", "effect": "allow"},
    {"action": "read", "resource": "*.env", "effect": "deny"},
    {"action": "read", "resource": "*.env.*", "effect": "deny"},
    {"action": "glob", "resource": "*", "effect": "allow"},
    {"action": "grep", "resource": "*", "effect": "allow"},
    {"action": "question", "resource": "*", "effect": "deny"},
    {"action": "external_directory", "resource": "*", "effect": "deny"},
]
DEFAULT_PERMISSIONS = [{"action": "*", "resource": "*", "effect": "allow"}]
REGISTRY_PATH = Path(__file__).resolve().parent.parent / "docker" / "services.json"

Opener = Callable[[str, float], dict]


class ConfigError(Exception):
    """The environment and registry cannot produce a usable configuration."""


@dataclass
class Rendered:
    config: dict
    service_id: str
    model: str
    small_model: str
    base_url: str
    health_check: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def model_ref(self) -> str:
        return f"{self.service_id}/{self.model}" if self.model else self.service_id


def load_registry(path: Path | str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"registry not readable: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"registry is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ConfigError(f"registry must be a non-empty JSON object: {path}")
    return data


def _http_get_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def discover_model(base_url: str, opener: Opener, timeout: float) -> str | None:
    """Return the first model id the server reports, or None."""
    try:
        payload = opener(f"{base_url}/models", timeout)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    for entry in payload.get("data") or []:
        if isinstance(entry, dict):
            model_id = entry.get("id")
            if isinstance(model_id, str) and model_id:
                return model_id
    return None


def _split_service_model(value: str) -> tuple[str, str]:
    service, _, model = value.partition("/")
    if not service or not model:
        raise ConfigError(f"OPENCODE_MODEL must be '<service>/<model>', got: {value!r}")
    return service, model


def _build_base_url(service_id: str, service: Mapping, env: Mapping[str, str]) -> str:
    override = (env.get("MODEL_BASE_URL") or "").strip()
    if override:
        return override.rstrip("/")
    declared = str(service.get("baseURL") or "").strip()
    if declared:
        return declared.rstrip("/")
    host = service.get("host")
    port = env.get("MODEL_PORT") or service.get("port")
    path = service.get("path", "/v1")
    if not host or not port:
        raise ConfigError(
            f"service {service_id!r} has no host/port or baseURL; set MODEL_BASE_URL instead"
        )
    return f"http://{host}:{port}{path}".rstrip("/")


def _models_map(service: Mapping, model: str) -> dict:
    declared = service.get("models") or {}
    models: dict[str, dict] = {}
    for model_id, meta in declared.items():
        entry: dict = {"name": model_id, "capabilities": {"tools": True}}
        if isinstance(meta, dict):
            for key, value in meta.items():
                if key == "tools":
                    entry["capabilities"]["tools"] = bool(value)
                else:
                    entry[key] = value
        models[model_id] = entry
    if model:
        models.setdefault(model, {"name": model, "capabilities": {"tools": True}})
    return models


def _provider_package(service: Mapping) -> str:
    """Return the V2 provider package, prefixing AI SDK packages with ``aisdk:``."""
    explicit = str(service.get("package") or "").strip()
    if explicit:
        return explicit
    npm = str(service.get("npm") or "@ai-sdk/openai-compatible").strip()
    if npm.startswith(("aisdk:", "file:", "npm:", "git:", "github:")):
        return npm
    return f"aisdk:{npm}"


def build_config(
    env: Mapping[str, str],
    registry: Mapping[str, dict],
    opener: Opener = _http_get_json,
    timeout: float = DEFAULT_TIMEOUT,
    require_model: bool = True,
    profile: str = DEFAULT_PROFILE,
) -> Rendered:
    if profile not in PROFILES:
        raise ConfigError(f"unknown profile {profile!r}; known: {', '.join(PROFILES)}")
    warnings: list[str] = []

    legacy = (env.get("OPENCODE_MODEL") or "").strip()
    service_id = (env.get("MODEL_SERVICE") or "").strip()
    base_url_override = (env.get("MODEL_BASE_URL") or "").strip()
    model = (env.get("MODEL_NAME") or "").strip()
    small_model = (env.get("SMALL_MODEL_NAME") or "").strip()

    if legacy:
        service_id, model = _split_service_model(legacy)

    if not service_id:
        service_id = CUSTOM_SERVICE if base_url_override else DEFAULT_SERVICE

    service = registry.get(service_id)
    if not isinstance(service, dict):
        known = ", ".join(sorted(registry))
        raise ConfigError(f"unknown service {service_id!r}; registry has: {known}")

    base_url = _build_base_url(service_id, service, env)
    health_check = service.get("healthCheck", True) is not False

    if not model and require_model and env.get("MODEL_DISCOVER", "1") != "0" and health_check:
        discovered = discover_model(base_url, opener, timeout)
        if discovered:
            model = discovered
        else:
            default = service.get("defaultModel") or ""
            if default:
                warnings.append(
                    f"model discovery failed at {base_url}/models; "
                    f"using registry default {default!r}"
                )

    if not model:
        model = service.get("defaultModel") or ""

    if not model and require_model:
        raise ConfigError(
            "no model: set MODEL_NAME, or make the server's /models endpoint "
            f"reachable, or give service {service_id!r} a defaultModel"
        )

    if not small_model:
        small_model = model

    settings: dict = {"baseURL": base_url}
    api_key = (env.get("MODEL_API_KEY") or "").strip()
    if api_key:
        settings["apiKey"] = api_key
    provider = {
        "name": service.get("name", service_id),
        "package": _provider_package(service),
        "settings": settings,
        "models": _models_map(service, model),
    }
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{service_id}/{model}" if model else "",
        "agents": {"title": {"model": f"{service_id}/{small_model}"}} if small_model else {},
        "update": "disable",
        "share": "disabled",
        # Default: the container is the security boundary and the agent runs
        # unattended. The readonly profile is for runs over untrusted input
        # (the Telegram bot's forwarded questions).
        "permissions": DEFAULT_PERMISSIONS if profile == DEFAULT_PROFILE else READONLY_PERMISSIONS,
        "providers": {service_id: provider},
    }
    return Rendered(
        config=config,
        service_id=service_id,
        model=model,
        small_model=small_model,
        base_url=base_url,
        health_check=health_check,
        warnings=warnings,
    )


def probe(base_url: str, opener: Opener, timeout: float) -> bool:
    try:
        opener(f"{base_url}/models", timeout)
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None,
         opener: Opener | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--profile", choices=PROFILES, default=DEFAULT_PROFILE,
                        help="permission profile: default (allow all) or readonly")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--health-url", action="store_true",
                      help="print the resolved /models URL")
    mode.add_argument("--list", action="store_true",
                      help="print the resolved service, model and base URL")
    mode.add_argument("--check", action="store_true",
                      help="probe the model server; exit 1 when unreachable")
    args = parser.parse_args(argv)

    env = os.environ if env is None else env
    opener = _http_get_json if opener is None else opener

    try:
        registry = load_registry(args.registry)
        rendered = build_config(
            env,
            registry,
            opener=opener,
            timeout=args.timeout,
            # --health-url and --check only need the base URL; the default
            # render and --list need a model.
            require_model=args.list or not (args.health_url or args.check),
            profile=args.profile,
        )
    except ConfigError as exc:
        print(f"render_config: {exc}", file=sys.stderr)
        return 2

    for warning in rendered.warnings:
        print(f"render_config: warning: {warning}", file=sys.stderr)

    if args.health_url:
        if not rendered.health_check:
            return 0
        print(f"{rendered.base_url}/models")
        return 0
    if args.list:
        print(f"service: {rendered.service_id}")
        print(f"model:   {rendered.model_ref}")
        print(f"baseURL: {rendered.base_url}")
        return 0
    if args.check:
        if not rendered.health_check:
            print(f"SKIP: {rendered.service_id} has no health endpoint")
            return 0
        if probe(rendered.base_url, opener, args.timeout):
            print(f"OK: {rendered.model_ref} ({rendered.base_url})")
            return 0
        print(f"unreachable: {rendered.base_url}", file=sys.stderr)
        return 1

    print(json.dumps(rendered.config, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

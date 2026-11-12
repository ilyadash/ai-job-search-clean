"""Tests for the container OpenCode config renderer.

The renderer turns MODEL_* environment variables plus the service registry
(docker/services.json) into an OPENCODE_CONFIG_CONTENT JSON blob. These tests
inject the environment and the HTTP opener, so they never touch the network.
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tools import render_opencode_config as render

REPO_ROOT = Path(__file__).resolve().parent.parent

REGISTRY = {
    "lmstudio": {
        "name": "LM Studio (host)",
        "api": "openai",
        "npm": "@ai-sdk/openai-compatible",
        "host": "host.docker.internal",
        "port": 1234,
        "path": "/v1",
        "defaultModel": "qwen/qwen3.5-9b",
        "models": {"qwen/qwen3.5-9b": {"name": "qwen3.5-9b (local)", "tools": True}},
    },
    "custom": {
        "name": "Custom OpenAI-compatible endpoint",
        "api": "openai",
        "npm": "@ai-sdk/openai-compatible",
    },
    "deepseek": {
        "name": "DeepSeek (cloud)",
        "api": "openai",
        "npm": "@ai-sdk/openai-compatible",
        "baseURL": "https://api.deepseek.com",
        "healthCheck": False,
        "defaultModel": "deepseek-flash",
        "models": {"deepseek-flash": {"name": "DeepSeek Flash (cloud)", "tools": True}},
    },
}


def opener_returning(payload):
    calls = []

    def _opener(url, timeout):
        calls.append(url)
        return payload

    return _opener, calls


def opener_failing():
    calls = []

    def _opener(url, timeout):
        calls.append(url)
        raise OSError("connection refused")

    return _opener, calls


class BuildConfig(unittest.TestCase):
    def test_default_service_uses_the_registry_default(self):
        opener, calls = opener_returning({"data": [{"id": "discovered-model"}]})
        rendered = render.build_config({}, REGISTRY, opener=opener)

        self.assertEqual(rendered.service_id, "deepseek")
        self.assertEqual(rendered.model, "deepseek-flash")
        self.assertEqual(rendered.config["model"], "deepseek/deepseek-flash")
        self.assertEqual(
            rendered.config["providers"]["deepseek"]["settings"]["baseURL"],
            "https://api.deepseek.com",
        )
        self.assertEqual(calls, [])

    def test_lmstudio_discovers_its_model(self):
        opener, calls = opener_returning({"data": [{"id": "discovered-model"}]})
        rendered = render.build_config({"MODEL_SERVICE": "lmstudio"}, REGISTRY, opener=opener)

        self.assertEqual(rendered.service_id, "lmstudio")
        self.assertEqual(rendered.model, "discovered-model")
        self.assertEqual(rendered.config["model"], "lmstudio/discovered-model")
        self.assertEqual(
            rendered.config["providers"]["lmstudio"]["settings"]["baseURL"],
            "http://host.docker.internal:1234/v1",
        )
        self.assertEqual(calls, ["http://host.docker.internal:1234/v1/models"])

    def test_explicit_model_skips_discovery(self):
        opener, calls = opener_failing()
        rendered = render.build_config({"MODEL_NAME": "pinned-model"}, REGISTRY, opener=opener)

        self.assertEqual(rendered.model, "pinned-model")
        self.assertEqual(calls, [])

    def test_discovery_failure_falls_back_to_registry_default(self):
        opener, _ = opener_failing()
        rendered = render.build_config({"MODEL_SERVICE": "lmstudio"}, REGISTRY, opener=opener)

        self.assertEqual(rendered.model, "qwen/qwen3.5-9b")
        self.assertTrue(rendered.warnings)

    def test_discovery_disabled_uses_registry_default(self):
        opener, calls = opener_returning({"data": [{"id": "ignored"}]})
        rendered = render.build_config(
            {"MODEL_SERVICE": "lmstudio", "MODEL_DISCOVER": "0"},
            REGISTRY,
            opener=opener,
        )

        self.assertEqual(rendered.model, "qwen/qwen3.5-9b")
        self.assertEqual(calls, [])

    def test_model_port_override(self):
        rendered = render.build_config(
            {"MODEL_SERVICE": "lmstudio", "MODEL_PORT": "9999", "MODEL_NAME": "m"},
            REGISTRY,
            opener=opener_failing()[0],
        )
        self.assertEqual(rendered.base_url, "http://host.docker.internal:9999/v1")

    def test_service_selection(self):
        rendered = render.build_config(
            {"MODEL_SERVICE": "lmstudio", "MODEL_NAME": "qwen/qwen3.5-9b"},
            REGISTRY,
            opener=opener_failing()[0],
        )
        self.assertEqual(rendered.service_id, "lmstudio")
        self.assertEqual(rendered.model, "qwen/qwen3.5-9b")
        self.assertIn("lmstudio", rendered.config["providers"])

    def test_model_base_url_selects_custom_service(self):
        rendered = render.build_config(
            {"MODEL_BASE_URL": "http://example.test:8000/v1", "MODEL_NAME": "remote-model"},
            REGISTRY,
            opener=opener_failing()[0],
        )
        self.assertEqual(rendered.service_id, "custom")
        self.assertEqual(rendered.base_url, "http://example.test:8000/v1")
        self.assertEqual(rendered.config["model"], "custom/remote-model")

    def test_legacy_opencode_model_reference(self):
        rendered = render.build_config(
            {"OPENCODE_MODEL": "lmstudio/qwen/qwen3.5-9b"},
            REGISTRY,
            opener=opener_failing()[0],
        )
        self.assertEqual(rendered.service_id, "lmstudio")
        self.assertEqual(rendered.model, "qwen/qwen3.5-9b")

    def test_legacy_opencode_model_requires_service_and_model(self):
        with self.assertRaises(render.ConfigError):
            render.build_config({"OPENCODE_MODEL": "just-a-model"}, REGISTRY)

    def test_small_model_defaults_to_model_and_can_override(self):
        base = render.build_config({"MODEL_NAME": "m"}, REGISTRY, opener=opener_failing()[0])
        self.assertEqual(base.small_model, "m")

        overridden = render.build_config(
            {"MODEL_NAME": "m", "SMALL_MODEL_NAME": "tiny"}, REGISTRY,
            opener=opener_failing()[0],
        )
        self.assertEqual(overridden.config["agents"]["title"]["model"], "deepseek/tiny")

    def test_declared_models_and_discovered_model_are_included(self):
        opener, _ = opener_returning({"data": [{"id": "extra-model"}]})
        rendered = render.build_config({"MODEL_SERVICE": "lmstudio"}, REGISTRY, opener=opener)
        models = rendered.config["providers"]["lmstudio"]["models"]

        self.assertEqual(models["qwen/qwen3.5-9b"]["name"], "qwen3.5-9b (local)")
        self.assertTrue(models["qwen/qwen3.5-9b"]["capabilities"]["tools"])
        self.assertEqual(
            models["extra-model"],
            {"name": "extra-model", "capabilities": {"tools": True}},
        )

    def test_permission_is_allow_all(self):
        rendered = render.build_config({"MODEL_NAME": "m"}, REGISTRY, opener=opener_failing()[0])
        self.assertEqual(rendered.config["permissions"], render.DEFAULT_PERMISSIONS)
        self.assertEqual(rendered.config["update"], "disable")
        self.assertEqual(rendered.config["share"], "disabled")
        self.assertEqual(
            rendered.config["providers"]["deepseek"]["package"],
            "aisdk:@ai-sdk/openai-compatible",
        )

    def test_registry_base_url_selects_the_declared_endpoint(self):
        rendered = render.build_config(
            {"MODEL_SERVICE": "deepseek", "MODEL_NAME": "deepseek-chat"},
            REGISTRY,
            opener=opener_failing()[0],
        )
        self.assertEqual(rendered.base_url, "https://api.deepseek.com")
        self.assertEqual(rendered.config["model"], "deepseek/deepseek-chat")

    def test_model_base_url_overrides_the_registry_base_url(self):
        rendered = render.build_config(
            {"MODEL_SERVICE": "deepseek", "MODEL_NAME": "deepseek-chat",
             "MODEL_BASE_URL": "https://proxy.test/v1"},
            REGISTRY,
            opener=opener_failing()[0],
        )
        self.assertEqual(rendered.base_url, "https://proxy.test/v1")

    def test_model_api_key_is_injected_only_when_set(self):
        rendered = render.build_config(
            {"MODEL_SERVICE": "deepseek", "MODEL_NAME": "deepseek-chat",
             "MODEL_API_KEY": "sk-test"},
            REGISTRY,
            opener=opener_failing()[0],
        )
        self.assertEqual(
            rendered.config["providers"]["deepseek"]["settings"]["apiKey"], "sk-test"
        )

        without_key = render.build_config(
            {"MODEL_SERVICE": "deepseek", "MODEL_NAME": "deepseek-chat"},
            REGISTRY,
            opener=opener_failing()[0],
        )
        self.assertNotIn("apiKey", without_key.config["providers"]["deepseek"]["settings"])

    def test_readonly_profile_denies_everything_but_reads(self):
        rendered = render.build_config(
            {"MODEL_NAME": "m"}, REGISTRY, opener=opener_failing()[0],
            profile=render.READONLY_PROFILE,
        )
        permission = rendered.config["permissions"]
        self.assertEqual(permission, render.READONLY_PERMISSIONS)
        self.assertEqual(permission[0], {"action": "*", "resource": "*", "effect": "deny"})
        self.assertIn(
            {"action": "read", "resource": "*", "effect": "allow"}, permission
        )
        self.assertIn(
            {"action": "read", "resource": "*.env", "effect": "deny"}, permission
        )
        self.assertIn(
            {"action": "glob", "resource": "*", "effect": "allow"}, permission
        )
        self.assertIn(
            {"action": "grep", "resource": "*", "effect": "allow"}, permission
        )
        self.assertIn(
            {"action": "question", "resource": "*", "effect": "deny"}, permission
        )
        self.assertEqual(
            permission[-1],
            {"action": "external_directory", "resource": "*", "effect": "deny"},
        )

    def test_unknown_profile_is_an_error(self):
        with self.assertRaises(render.ConfigError):
            render.build_config(
                {"MODEL_NAME": "m"}, REGISTRY, opener=opener_failing()[0],
                profile="yolo",
            )

    def test_unknown_service_is_an_error(self):
        with self.assertRaises(render.ConfigError):
            render.build_config({"MODEL_SERVICE": "nope", "MODEL_NAME": "m"}, REGISTRY)

    def test_custom_without_base_url_is_an_error(self):
        with self.assertRaises(render.ConfigError):
            render.build_config({"MODEL_SERVICE": "custom", "MODEL_NAME": "m"}, REGISTRY)

    def test_repo_registry_is_valid_and_covers_the_documented_services(self):
        registry = render.load_registry(REPO_ROOT / "docker" / "services.json")
        for service_id in ("lmstudio", "deepseek", "custom"):
            self.assertIn(service_id, registry)
        self.assertEqual(registry["deepseek"]["defaultModel"], "deepseek-flash")


class MainCli(unittest.TestCase):
    def _run(self, argv, env=None, opener=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = render.main(argv, env=env or {}, opener=opener or opener_failing()[0])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_default_mode_prints_config_json(self):
        code, out, _ = self._run(
            [], env={"MODEL_NAME": "m"}, opener=opener_failing()[0]
        )
        self.assertEqual(code, 0)
        config = json.loads(out)
        self.assertEqual(config["model"], "deepseek/m")
        self.assertEqual(config["permissions"], render.DEFAULT_PERMISSIONS)

    def test_profile_flag_selects_the_readonly_permission(self):
        code, out, _ = self._run(
            ["--profile", "readonly"], env={"MODEL_NAME": "m"},
            opener=opener_failing()[0],
        )
        self.assertEqual(code, 0)
        config = json.loads(out)
        self.assertEqual(config["permissions"][0]["action"], "*")
        self.assertEqual(config["permissions"][0]["effect"], "deny")

    def test_health_url_mode_prints_url_without_model(self):
        code, out, _ = self._run(
            ["--health-url"], env={"MODEL_SERVICE": "lmstudio"}
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "http://host.docker.internal:1234/v1/models")

    def test_health_url_is_empty_for_a_service_without_health_check(self):
        code, out, _ = self._run(["--health-url"], env={})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_check_ok(self):
        opener, _ = opener_returning({"data": [{"id": "m"}]})
        code, out, _ = self._run(
            ["--check"], env={"MODEL_SERVICE": "lmstudio", "MODEL_NAME": "m"},
            opener=opener,
        )
        self.assertEqual(code, 0)
        self.assertIn("OK:", out)

    def test_check_unreachable(self):
        code, _, err = self._run(
            ["--check"], env={"MODEL_SERVICE": "lmstudio", "MODEL_NAME": "m"}
        )
        self.assertEqual(code, 1)
        self.assertIn("unreachable", err)

    def test_check_is_skipped_for_a_service_without_health_check(self):
        code, out, _ = self._run(["--check"], env={})
        self.assertEqual(code, 0)
        self.assertIn("SKIP: deepseek", out)

    def test_list_mode_prints_resolved_settings(self):
        code, out, _ = self._run(["--list"], env={"MODEL_NAME": "m"})
        self.assertEqual(code, 0)
        self.assertIn("service: deepseek", out)
        self.assertIn("model:   deepseek/m", out)

    def test_missing_registry_is_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            code, _, err = self._run(["--registry", str(missing)], env={"MODEL_NAME": "m"})
        self.assertEqual(code, 2)
        self.assertIn("registry not readable", err)

    def test_invalid_registry_is_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "services.json"
            broken.write_text("{not json", encoding="utf-8")
            code, _, err = self._run(["--registry", str(broken)], env={"MODEL_NAME": "m"})
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)


if __name__ == "__main__":
    unittest.main()

"""Model-role configuration and routing without live provider calls."""

from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from deep_agent_app.agent.llm.clients import _client_options
from deep_agent_app.utilities import model_registry
from deep_agent_app.utilities.validation import resolve_provider, validate_model_choice


class ModelRoleTests(SimpleTestCase):
    def test_explicit_roles_resolve_to_provider_ids(self):
        providers = {"small": {}, "balanced": {}, "strong": {}}
        roles = model_registry.model_role_registry(
            {
                "flash_model": "small",
                "main_model": "balanced",
                "frontier_model": "strong",
            },
            providers,
        )
        with (
            patch.object(model_registry, "MODEL_ROLES", roles),
            patch.object(model_registry, "PROVIDERS", providers),
        ):
            self.assertEqual(resolve_provider("auto"), "balanced")
            self.assertEqual(resolve_provider("flash"), "small")
            self.assertEqual(resolve_provider("main"), "balanced")
            self.assertEqual(resolve_provider("frontier"), "strong")
            self.assertEqual(resolve_provider("strong"), "strong")
            with self.assertRaisesMessage(ValueError, "unknown or unavailable model"):
                validate_model_choice("missing")

    def test_legacy_single_provider_maps_all_roles_during_migration(self):
        roles = model_registry.model_role_registry({"llm_provider": "old"}, {"old": {}})
        self.assertEqual(
            dict(roles), dict.fromkeys(("flash", "main", "frontier"), "old")
        )

    def test_partial_or_unknown_role_configuration_fails_closed(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "together"):
            model_registry.model_role_registry({"flash_model": "small"}, {"small": {}})
        with self.assertRaisesMessage(ImproperlyConfigured, "frontier_model"):
            model_registry.model_role_registry(
                {
                    "flash_model": "small",
                    "main_model": "small",
                    "frontier_model": "absent",
                },
                {"small": {}},
            )
        with self.assertRaisesMessage(ImproperlyConfigured, "reserved"):
            model_registry.model_role_registry({"llm_provider": "flash"}, {"flash": {}})

    def test_model_choices_put_stable_roles_before_raw_provider_ids(self):
        choices = model_registry.model_choices()
        self.assertEqual(
            [choice["id"] for choice in choices[:4]],
            ["auto", "flash", "main", "frontier"],
        )
        self.assertEqual(
            [choice["id"] for choice in choices[4:]],
            list(model_registry.PROVIDERS),
        )
        self.assertNotIn("api_key", str(choices))

    def test_reasoning_model_can_omit_unsupported_temperature_parameter(self):
        options = _client_options(
            {
                "model_provider": "openai",
                "api_key": "test-key",
                "send_temperature": False,
            },
            0.0,
        )
        self.assertNotIn("temperature", options)
        self.assertEqual(options["api_key"], "test-key")
        self.assertEqual(
            _client_options({"api_key": "test-key"}, 0.25)["temperature"],
            0.25,
        )

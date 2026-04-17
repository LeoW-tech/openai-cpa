import importlib
import sys
import unittest


class Sub2APIDefaultModelMappingTests(unittest.TestCase):
    def _reload_client_module(self):
        sys.modules.pop("utils.integrations.sub2api_client", None)
        return importlib.import_module("utils.integrations.sub2api_client")

    def test_default_model_mapping_contains_expected_models_in_order(self):
        sub2api_client = self._reload_client_module()

        mapping = sub2api_client.build_default_model_mapping()

        self.assertEqual(
            [
                "gpt-5.1",
                "gpt-5.1-codex",
                "gpt-5.1-codex-max",
                "gpt-5.1-codex-mini",
                "gpt-5.2",
                "gpt-5.2-codex",
                "gpt-5.3",
                "gpt-5.3-codex",
                "gpt-5.4",
            ],
            list(mapping.keys()),
        )
        self.assertEqual(mapping, {model_id: model_id for model_id in mapping})


if __name__ == "__main__":
    unittest.main()

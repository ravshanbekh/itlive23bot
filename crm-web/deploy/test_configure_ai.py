import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("configure_ai", Path(__file__).with_name("configure-ai.py"))
configure_ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure_ai)


class ConfigureAITests(unittest.TestCase):
    def test_preserves_database_secret_and_replaces_only_selected_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            env = Path(temp) / ".env"
            env.write_text("POSTGRES_PASSWORD=database-password\nGROQ_API_KEY=old-key\nOPENAI_API_KEY=other-key\n", encoding="utf-8")
            configure_ai.save_key(env, "GROQ_API_KEY", "groq", "new-test-key-12345")
            content = env.read_text(encoding="utf-8")
            self.assertIn("POSTGRES_PASSWORD=database-password", content)
            self.assertIn("OPENAI_API_KEY=other-key", content)
            self.assertEqual(content.count("GROQ_API_KEY="), 1)
            self.assertIn("GROQ_API_KEY=new-test-key-12345", content)
            self.assertIn("AI_PROVIDER=groq", content)
            if os.name == "posix":
                self.assertEqual(env.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()

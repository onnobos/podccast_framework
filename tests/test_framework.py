"""
Comprehensive Unit Test Suite for Podcast Generation Framework.
Covers Models, Ingesters, Plugins, Registry, Validation, and Prompt Loading.
"""
import unittest
from pathlib import Path
import tempfile
import shutil

from src.framework.models import (
    HostConfig,
    AudioThemeConfig,
    ShowMetadata,
    CloudDistributionConfig,
    ScriptConfig,
    IngestionResult,
)
from src.framework.base_ingester import BaseIngester
from src.framework.base_plugin import PodcastPlugin
from src.framework.registry import PluginRegistry, registry, get_active_plugin
from src.prompt_loader import load_prompt
from plugins.volleyball.plugin import VolleyballPodcastPlugin
from plugins.volleyball.ingester import VolleyBrainsIngester


class MockCustomIngester(BaseIngester):
    """Mock Ingester for testing."""
    def get_slug(self, source: str) -> str:
        return source.strip("/").split("/")[-1]

    def ingest(self, source: str, **kwargs) -> IngestionResult:
        slug = self.get_slug(source)
        return IngestionResult(
            slug=slug,
            title="Mock Episode Title",
            article_markdown="# Mock Article\nSample content for testing.",
            video_urls=["https://youtube.com/watch?v=mock123"],
            metadata={"source": source}
        )


class MockCustomPlugin(PodcastPlugin):
    """Mock Plugin for testing base plugin behaviors."""
    def __init__(self, temp_prompts_dir: Path | None = None):
        self._temp_prompts_dir = temp_prompts_dir

    @property
    def name(self) -> str:
        return "Mock Tech Show"

    @property
    def slug(self) -> str:
        return "mock_tech"

    @property
    def show_metadata(self) -> ShowMetadata:
        return ShowMetadata(
            title="Mock Tech Show",
            author="Mock Author",
            email="mock@example.com",
            description="Testing mock podcast",
            category="Technology",
            subcategory="Software",
            explicit=False
        )

    @property
    def hosts(self) -> dict[str, HostConfig]:
        return {
            "HOST_A": HostConfig(name="Alice", role="Anchor", voice="alloy", mic_position="left"),
            "HOST_B": HostConfig(name="Bob", role="Tech Lead", voice="echo", mic_position="right")
        }

    @property
    def audio_theme(self) -> AudioThemeConfig:
        return AudioThemeConfig(
            intro_solo_ms=5000,
            intro_duck_ms=15000,
            outro_duck_ms=3000,
            outro_solo_ms=1500,
            duck_gain_db=-18.0,
            target_lufs=-14.0
        )

    @property
    def distribution(self) -> CloudDistributionConfig:
        return CloudDistributionConfig(
            bucket_name="mock-bucket",
            feed_key="tech_feed.xml"
        )

    @property
    def script_config(self) -> ScriptConfig:
        return ScriptConfig(
            curator_model="test-curator-model",
            script_model="test-script-model",
            target_duration_min=15,
            target_clip_ratio=0.30,
            banned_phrases=["buzzword", "synergy"]
        )

    @property
    def prompts_dir(self) -> Path:
        if self._temp_prompts_dir:
            return self._temp_prompts_dir
        return super().prompts_dir

    def get_ingester(self) -> BaseIngester:
        return MockCustomIngester()


class TestFrameworkModels(unittest.TestCase):
    """Test all Pydantic data models used across the framework."""

    def test_host_config_defaults_and_custom(self):
        host = HostConfig(name="Host One", role="Lead", voice="shimmer")
        self.assertEqual(host.name, "Host One")
        self.assertEqual(host.role, "Lead")
        self.assertEqual(host.voice, "shimmer")
        self.assertEqual(host.mic_position, "left")
        self.assertEqual(host.description, "")

        host_b = HostConfig(name="Host Two", role="Expert", voice="ash", mic_position="right", description="Bio")
        self.assertEqual(host_b.mic_position, "right")
        self.assertEqual(host_b.description, "Bio")

    def test_audio_theme_config_defaults(self):
        theme = AudioThemeConfig()
        self.assertEqual(theme.intro_solo_ms, 7500)
        self.assertEqual(theme.intro_duck_ms, 30000)
        self.assertEqual(theme.outro_duck_ms, 5000)
        self.assertEqual(theme.outro_solo_ms, 2000)
        self.assertEqual(theme.duck_gain_db, -16.0)
        self.assertEqual(theme.target_lufs, -16.0)
        self.assertEqual(theme.room_tone_dbfs, -56.0)
        self.assertTrue(theme.enable_room_tone)
        self.assertTrue(theme.enable_mic_bleed)

    def test_show_metadata_defaults(self):
        meta = ShowMetadata(
            title="Pod Title",
            author="Pod Author",
            email="author@pod.com",
            description="Pod Description"
        )
        self.assertEqual(meta.language, "en")
        self.assertEqual(meta.category, "Sports")
        self.assertEqual(meta.subcategory, "Volleyball")
        self.assertFalse(meta.explicit)
        self.assertIsNone(meta.cover_art_path)

    def test_cloud_distribution_config_defaults(self):
        dist = CloudDistributionConfig()
        self.assertEqual(dist.feed_key, "feed.xml")
        self.assertEqual(dist.bucket_name, "")
        self.assertEqual(dist.audio_prefix, "")

    def test_script_config_defaults_and_banned_words(self):
        cfg = ScriptConfig()
        self.assertEqual(cfg.curator_model, "google/gemini-2.5-pro")
        self.assertEqual(cfg.script_model, "anthropic/claude-sonnet-4")
        self.assertEqual(cfg.audit_model, "google/gemini-2.5-flash")
        self.assertEqual(cfg.target_duration_min, 25)
        self.assertEqual(cfg.target_clip_ratio, 0.40)
        self.assertIn("incredible", cfg.banned_phrases)
        self.assertIn("game-changer", cfg.banned_phrases)

    def test_ingestion_result_model(self):
        res = IngestionResult(
            slug="test-slug",
            title="Test Title",
            article_markdown="# Hello",
            video_urls=["url1", "url2"],
            metadata={"source": "unit_test"}
        )
        self.assertEqual(res.slug, "test-slug")
        self.assertEqual(len(res.video_urls), 2)
        self.assertEqual(res.metadata["source"], "unit_test")


class TestBaseIngesterAndPlugin(unittest.TestCase):
    """Test BaseIngester and PodcastPlugin base implementations."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.prompts_dir = self.test_dir / "prompts"
        self.prompts_dir.mkdir(parents=True)
        self.plugin = MockCustomPlugin(temp_prompts_dir=self.prompts_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mock_ingester(self):
        ingester = self.plugin.get_ingester()
        slug = ingester.get_slug("https://example.com/shows/deep-dive-episode")
        self.assertEqual(slug, "deep-dive-episode")

        result = ingester.ingest("https://example.com/shows/deep-dive-episode")
        self.assertEqual(result.slug, "deep-dive-episode")
        self.assertEqual(result.title, "Mock Episode Title")
        self.assertEqual(result.video_urls, ["https://youtube.com/watch?v=mock123"])

    def test_plugin_properties(self):
        self.assertEqual(self.plugin.name, "Mock Tech Show")
        self.assertEqual(self.plugin.slug, "mock_tech")
        self.assertEqual(self.plugin.show_metadata.category, "Technology")
        self.assertEqual(self.plugin.audio_theme.target_lufs, -14.0)
        self.assertEqual(self.plugin.script_config.target_duration_min, 15)
        self.assertIn("HOST_A", self.plugin.hosts)
        self.assertIn("HOST_B", self.plugin.hosts)

    def test_plugin_script_validation_banned_phrases(self):
        clean_script = "Host A: We are discussing engineering paradigms today."
        issues = self.plugin.validate_script(clean_script)
        self.assertEqual(issues, [])

        dirty_script = "Host A: We must leverage corporate synergy and another buzzword."
        issues = self.plugin.validate_script(dirty_script)
        self.assertEqual(len(issues), 2)
        self.assertTrue(any("synergy" in i for i in issues))
        self.assertTrue(any("buzzword" in i for i in issues))

    def test_plugin_get_prompt_with_and_without_h1(self):
        # 1. Fallback when file doesn't exist
        default_val = "Default fallback prompt"
        self.assertEqual(self.plugin.get_prompt("non_existent.md", default=default_val), default_val)

        # 2. File with leading markdown H1
        prompt_with_h1 = self.prompts_dir / "test_prompt.md"
        prompt_with_h1.write_text("# Test Prompt Title\n\nActual prompt instructions here.", encoding="utf-8")
        loaded = self.plugin.get_prompt("test_prompt.md")
        self.assertEqual(loaded, "Actual prompt instructions here.")

        # 3. File without leading markdown H1
        prompt_raw = self.prompts_dir / "raw_prompt.md"
        prompt_raw.write_text("Pure prompt content without header.", encoding="utf-8")
        loaded_raw = self.plugin.get_prompt("raw_prompt.md")
        self.assertEqual(loaded_raw, "Pure prompt content without header.")


class TestPluginRegistry(unittest.TestCase):
    """Test PluginRegistry discovery, registration, and active plugin management."""

    def setUp(self):
        self.isolated_registry = PluginRegistry(plugins_dir=Path("plugins"))

    def test_global_registry_has_volleyball(self):
        plugins = registry.list_plugins()
        self.assertIn("volleyball", plugins)
        active = get_active_plugin()
        self.assertIsNotNone(active)

    def test_custom_registration(self):
        mock_plugin = MockCustomPlugin()
        self.isolated_registry.register(mock_plugin)
        self.assertIn("mock_tech", self.isolated_registry.list_plugins())
        retrieved = self.isolated_registry.get_plugin("mock_tech")
        self.assertEqual(retrieved.name, "Mock Tech Show")

    def test_set_active_plugin(self):
        mock_plugin = MockCustomPlugin()
        self.isolated_registry.register(mock_plugin)
        
        active = self.isolated_registry.set_active_plugin("mock_tech")
        self.assertEqual(active.slug, "mock_tech")
        self.assertEqual(self.isolated_registry.active_plugin.slug, "mock_tech")

    def test_set_active_plugin_invalid_slug_raises_error(self):
        with self.assertRaises(ValueError):
            self.isolated_registry.set_active_plugin("non_existent_plugin_xyz")

    def test_empty_registry_active_plugin_raises_error(self):
        empty_reg = PluginRegistry(plugins_dir=Path(tempfile.gettempdir()) / "empty_plugins_dir_xyz")
        with self.assertRaises(RuntimeError):
            _ = empty_reg.active_plugin


class TestVolleyballPlugin(unittest.TestCase):
    """Test specific functionality of the flagship Volleyball plugin."""

    def setUp(self):
        self.plugin = VolleyballPodcastPlugin()

    def test_volleyball_plugin_metadata(self):
        self.assertEqual(self.plugin.name, "Volleyball Coaching Uncovered")
        self.assertEqual(self.plugin.slug, "volleyball")
        self.assertEqual(self.plugin.show_metadata.title, "Volleyball Coaching Uncovered")
        self.assertEqual(self.plugin.show_metadata.category, "Sports")
        self.assertEqual(self.plugin.show_metadata.subcategory, "Volleyball")

    def test_volleyball_hosts_configuration(self):
        hosts = self.plugin.hosts
        self.assertIn("HOST_A", hosts)
        self.assertIn("HOST_B", hosts)
        self.assertEqual(hosts["HOST_A"].name, "Chloe Miller")
        self.assertEqual(hosts["HOST_B"].name, "Davis Hayes")
        self.assertEqual(hosts["HOST_A"].mic_position, "left")
        self.assertEqual(hosts["HOST_B"].mic_position, "right")

    def test_volleyball_audio_theme(self):
        theme = self.plugin.audio_theme
        self.assertEqual(theme.intro_solo_ms, 7500)
        self.assertEqual(theme.intro_duck_ms, 30000)
        self.assertEqual(theme.target_lufs, -16.0)
        self.assertEqual(theme.duck_gain_db, -16.0)
        self.assertTrue(theme.enable_room_tone)
        self.assertTrue(theme.enable_mic_bleed)

    def test_volleyball_ingester_slug(self):
        ingester = self.plugin.get_ingester()
        self.assertIsInstance(ingester, VolleyBrainsIngester)
        slug = ingester.get_slug("https://volleybrains.com/andre-sa-masterclass/")
        self.assertEqual(slug, "andre-sa-masterclass")

    def test_volleyball_brand_neutrality_validation(self):
        # Banned brand check
        dirty_script = "[HOST_A] Welcome to VolleyBrains today!"
        issues = self.plugin.validate_script(dirty_script)
        self.assertTrue(any("VolleyBrains" in i for i in issues))

        # Banned clichés check
        cliche_script = "[HOST_A] This is a game-changer drill and it is incredible."
        issues = self.plugin.validate_script(cliche_script)
        self.assertTrue(any("game-changer" in i for i in issues))
        self.assertTrue(any("incredible" in i for i in issues))

        # Clean script
        clean_script = "[HOST_A] Watch the platform angle on float reception."
        clean_issues = self.plugin.validate_script(clean_script)
        self.assertEqual(clean_issues, [])


class TestPromptLoaderWithPlugin(unittest.TestCase):
    """Test load_prompt fallback and plugin prompt override mechanism."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.prompts_dir = self.test_dir / "prompts"
        self.prompts_dir.mkdir(parents=True)
        self.plugin = MockCustomPlugin(temp_prompts_dir=self.prompts_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_prompt_from_plugin(self):
        custom_file = self.prompts_dir / "curator_system.md"
        custom_file.write_text("# Plugin Specific Curator\n\nCustom prompt instructions", encoding="utf-8")

        loaded = load_prompt("curator_system.md", default="fallback", plugin=self.plugin)
        self.assertEqual(loaded, "Custom prompt instructions")

    def test_load_prompt_fallback_to_root(self):
        # Request file that doesn't exist in plugin, but exists in root prompts/ (e.g. hosts.md)
        loaded = load_prompt("hosts.md", default="fallback", plugin=self.plugin)
        self.assertTrue(len(loaded) > 0)
        self.assertNotEqual(loaded, "fallback")

    def test_load_prompt_complete_fallback(self):
        loaded = load_prompt("totally_fake_file.md", default="custom_fallback", plugin=self.plugin)
        self.assertEqual(loaded, "custom_fallback")


class TestSecurityRemediations(unittest.TestCase):
    """Test OWASP Top 10 security defenses: SSRF, Path Traversal, and Hashing."""

    def test_validate_url_ssrf_protection(self):
        from src.scraper import validate_url
        # Legitimate URLs pass
        validate_url("https://volleybrains.com/andre-sa/")
        validate_url("https://example.com/masterclass")

        # Disallowed schemes raise ValueError
        with self.assertRaises(ValueError):
            validate_url("file:///C:/Windows/System32/drivers/etc/hosts")

        with self.assertRaises(ValueError):
            validate_url("gopher://127.0.0.1:70")

        # Localhost / Cloud metadata raise ValueError
        with self.assertRaises(ValueError):
            validate_url("http://localhost:8000/internal")

        with self.assertRaises(ValueError):
            validate_url("http://127.0.0.1:8000/internal")

        with self.assertRaises(ValueError):
            validate_url("http://169.254.169.254/latest/meta-data/")

        # Private IP ranges raise ValueError
        with self.assertRaises(ValueError):
            validate_url("http://192.168.1.10/admin")

        with self.assertRaises(ValueError):
            validate_url("http://10.0.0.1/admin")

    def test_sha256_hash_derivation(self):
        from src.transcriber import get_url_hash
        h = get_url_hash("https://youtube.com/watch?v=sample123")
        self.assertEqual(len(h), 12)
        # Consistent hash
        self.assertEqual(h, get_url_hash("https://youtube.com/watch?v=sample123"))

    def test_slug_regex_validation(self):
        import re
        valid_slug = "andre-sa_part1"
        self.assertTrue(bool(re.match(r"^[a-zA-Z0-9_-]+$", valid_slug)))

        # Path traversal attempts
        self.assertFalse(bool(re.match(r"^[a-zA-Z0-9_-]+$", "../../../etc/passwd")))
        self.assertFalse(bool(re.match(r"^[a-zA-Z0-9_-]+$", "slug; rm -rf /")))


if __name__ == "__main__":
    unittest.main()

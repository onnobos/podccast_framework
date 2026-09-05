"""
Plugin Discovery and Registry
"""
import importlib.util
import inspect
from pathlib import Path
from typing import Dict, Optional, Type
from rich.console import Console

from src.framework.base_plugin import PodcastPlugin

import re

console = Console()

class PluginRegistry:
    """Registry managing discovered and active podcast plugins."""

    def __init__(self, plugins_dir: Optional[Path] = None):
        self.plugins_dir = plugins_dir or (Path(__file__).resolve().parent.parent.parent / "plugins")
        self._plugins: Dict[str, PodcastPlugin] = {}
        self._active_plugin: Optional[PodcastPlugin] = None

    def register(self, plugin: PodcastPlugin):
        """Register a plugin instance."""
        self._plugins[plugin.slug] = plugin
        if self._active_plugin is None:
            self._active_plugin = plugin

    def discover_plugins(self) -> Dict[str, PodcastPlugin]:
        """Scan the plugins/ directory and instantiate any discovered PodcastPlugin implementations."""
        if not self.plugins_dir.exists():
            return self._plugins

        for sub_dir in self.plugins_dir.iterdir():
            if not sub_dir.is_dir() or sub_dir.name.startswith((".", "_")):
                continue

            if not re.match(r"^[a-zA-Z0-9_-]+$", sub_dir.name):
                console.print(f"[yellow]Skipping plugin directory with suspicious name: {sub_dir.name}[/yellow]")
                continue

            plugin_py = sub_dir / "plugin.py"
            if plugin_py.exists():
                try:
                    mod_name = f"plugins.{sub_dir.name}.plugin"
                    spec = importlib.util.spec_from_file_location(mod_name, plugin_py)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        # Find class inheriting from PodcastPlugin
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if (
                                inspect.isclass(attr)
                                and issubclass(attr, PodcastPlugin)
                                and attr is not PodcastPlugin
                            ):
                                instance = attr()
                                self.register(instance)
                except Exception as err:
                    console.print(f"[yellow]Failed loading plugin from {plugin_py}: {err}[/yellow]")

        return self._plugins

    def get_plugin(self, slug: str) -> Optional[PodcastPlugin]:
        """Retrieve a registered plugin by slug."""
        if not self._plugins:
            self.discover_plugins()
        return self._plugins.get(slug)

    def list_plugins(self) -> Dict[str, PodcastPlugin]:
        """Get all registered plugins."""
        if not self._plugins:
            self.discover_plugins()
        return self._plugins

    def set_active_plugin(self, slug: str) -> PodcastPlugin:
        """Set the globally active plugin for the pipeline run."""
        plugin = self.get_plugin(slug)
        if not plugin:
            raise ValueError(f"Plugin '{slug}' not found. Available: {list(self.list_plugins().keys())}")
        self._active_plugin = plugin
        return plugin

    @property
    def active_plugin(self) -> PodcastPlugin:
        """Get the active plugin. Defaults to first discovered plugin (e.g. volleyball)."""
        if self._active_plugin is None:
            self.discover_plugins()
            if self._plugins:
                self._active_plugin = next(iter(self._plugins.values()))
            else:
                raise RuntimeError("No podcast plugins found in plugins/ directory.")
        return self._active_plugin


# Global registry singleton
registry = PluginRegistry()


def get_active_plugin() -> PodcastPlugin:
    """Convenience getter for the active plugin."""
    return registry.active_plugin

"""
Auto-discovery of Voice Pipeline providers via entry_points.

This module enables automatic registration of providers from
installed packages using Python's entry_points mechanism.

To create a discoverable provider package:

1. Create your provider class implementing the appropriate interface.

2. In your pyproject.toml, add an entry_point:

    [project.entry-points."voice_pipeline.providers"]
    my_asr = "my_package.providers:register_providers"

3. In your register_providers function, register your providers:

    def register_providers(registry):
        from my_package.asr import MyASR
        registry.register_asr(
            name="my-asr",
            provider_class=MyASR,
            capabilities=ASRCapabilities(streaming=True),
        )

4. Install your package: pip install my-package

5. The providers will be auto-discovered when calling:
    registry.auto_discover()
"""

import importlib.metadata
import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from voice_pipeline.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)

# Entry point group name
ENTRY_POINT_GROUP = "voice_pipeline.providers"


def discover_providers(registry: "ProviderRegistry") -> int:
    """
    Discover and register providers from entry_points.

    This function looks for entry_points in the 'voice_pipeline.providers'
    group and calls them with the registry to register providers.

    Args:
        registry: The ProviderRegistry to register discovered providers in.

    Returns:
        Number of entry_points successfully loaded.
    """
    discovered = 0

    try:
        # Python 3.10+ has importlib.metadata.entry_points(group=...)
        eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        # Python 3.9 compatibility
        eps = importlib.metadata.entry_points().get(ENTRY_POINT_GROUP, [])

    for ep in eps:
        try:
            logger.debug(f"Loading provider entry_point: {ep.name}")

            # Load the entry_point
            register_func: Callable = ep.load()

            # Call it with the registry
            if callable(register_func):
                register_func(registry)
                discovered += 1
                logger.info(f"Loaded provider entry_point: {ep.name}")
            else:
                logger.warning(
                    f"Entry point {ep.name} is not callable, skipping"
                )

        except Exception as e:
            logger.error(
                f"Failed to load provider entry_point {ep.name}: {e}"
            )
            continue

    return discovered


def discover_from_module(
    module_name: str,
    registry: "ProviderRegistry",
    function_name: str = "register_providers",
) -> bool:
    """
    Discover providers from a specific module.

    This is useful for explicitly loading providers from a module
    without relying on entry_points.

    Args:
        module_name: Fully qualified module name (e.g., "voice_community.asr").
        registry: The ProviderRegistry to register providers in.
        function_name: Name of the registration function to call.

    Returns:
        True if successful, False otherwise.
    """
    try:
        import importlib

        module = importlib.import_module(module_name)
        register_func = getattr(module, function_name, None)

        if register_func and callable(register_func):
            register_func(registry)
            logger.info(f"Loaded providers from module: {module_name}")
            return True
        else:
            logger.warning(
                f"Module {module_name} does not have {function_name} function"
            )
            return False

    except ImportError as e:
        logger.error(f"Failed to import module {module_name}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error loading providers from {module_name}: {e}")
        return False


def list_available_packages() -> list[str]:
    """
    List installed packages that provide Voice Pipeline providers.

    Returns:
        List of package names that have entry_points for voice_pipeline.providers.
    """
    packages = []

    try:
        eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        eps = importlib.metadata.entry_points().get(ENTRY_POINT_GROUP, [])

    for ep in eps:
        # Get the distribution name from the entry_point
        if hasattr(ep, "dist") and ep.dist:
            packages.append(ep.dist.name)
        elif hasattr(ep, "_dist"):
            packages.append(ep._dist.name)
        else:
            # Fallback: use entry_point name
            packages.append(ep.name)

    return list(set(packages))


def get_provider_metadata(package_name: str) -> dict:
    """
    Get metadata about a provider package.

    Args:
        package_name: Name of the package.

    Returns:
        Dictionary with package metadata.
    """
    try:
        dist = importlib.metadata.distribution(package_name)
        return {
            "name": dist.name,
            "version": dist.version,
            "author": dist.metadata.get("Author", ""),
            "description": dist.metadata.get("Summary", ""),
            "url": dist.metadata.get("Home-page", ""),
        }
    except importlib.metadata.PackageNotFoundError:
        return {"name": package_name, "error": "Package not found"}

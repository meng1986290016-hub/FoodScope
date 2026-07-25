"""Choose the Horizon or FoodScope orchestrator from validated config."""

from .models import Config
from .orchestrator import HorizonOrchestrator
from .storage.manager import StorageManager


def create_orchestrator(
    config: Config, storage: StorageManager
) -> HorizonOrchestrator:
    """Construct the configured workflow without changing legacy behavior."""

    if config.foodscope and config.foodscope.enabled:
        from .foodscope.orchestrator import FoodScopeOrchestrator

        return FoodScopeOrchestrator(config, storage)
    return HorizonOrchestrator(config, storage)

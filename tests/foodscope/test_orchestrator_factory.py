from src.foodscope.orchestrator import FoodScopeOrchestrator
from src.models import Config
from src.orchestrator import HorizonOrchestrator
from src.orchestrator_factory import create_orchestrator
from src.storage.manager import StorageManager
from tests.foodscope.test_config_models import legacy_config


def test_factory_preserves_legacy_horizon(tmp_path):
    config = Config.model_validate(legacy_config())

    orchestrator = create_orchestrator(
        config, StorageManager(data_dir=str(tmp_path))
    )

    assert type(orchestrator) is HorizonOrchestrator


def test_factory_selects_foodscope(tmp_path):
    raw = legacy_config()
    raw["foodscope"] = {"enabled": True, "source_packs": []}
    raw["ai_routes"] = {"fast": raw["ai"], "analysis": raw["ai"]}
    config = Config.model_validate(raw)

    orchestrator = create_orchestrator(
        config, StorageManager(data_dir=str(tmp_path))
    )

    assert isinstance(orchestrator, FoodScopeOrchestrator)

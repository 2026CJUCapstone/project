"""Configuration and inventory wiring for approved preserved stateful IDs."""

import os

import pytest

from tests.test_edge_deploy import adapter, edge


BLUE_ID = "a" * 64
BLUE_ID_2 = "b" * 64
GREEN_ID = "c" * 64
GREEN_ID_2 = "d" * 64


@pytest.fixture(autouse=True)
def clean_edge_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("WEBCOMPILER_") or name in {"PROJECT_ROOT", "SANDBOX_POOL_ID"}:
            monkeypatch.delenv(name, raising=False)


def configure_root(monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path.resolve()))


def test_from_environment_defaults_preserved_stateful_ids_to_empty(monkeypatch, tmp_path):
    configure_root(monkeypatch, tmp_path)

    config = adapter.Config.from_environment()

    assert config.preserved_blue == ()
    assert config.preserved_green == ()


def test_from_environment_preserves_exact_ids_and_order_per_color(monkeypatch, tmp_path):
    configure_root(monkeypatch, tmp_path)
    monkeypatch.setenv("WEBCOMPILER_BLUE_PRESERVED_STATEFUL_IDS", f"{BLUE_ID},{BLUE_ID_2}")
    monkeypatch.setenv("WEBCOMPILER_GREEN_PRESERVED_STATEFUL_IDS", f"{GREEN_ID},{GREEN_ID_2}")

    config = adapter.Config.from_environment()

    assert config.preserved_blue == (BLUE_ID, BLUE_ID_2)
    assert config.preserved_green == (GREEN_ID, GREEN_ID_2)


@pytest.mark.parametrize(
    ("blue", "green"),
    [
        pytest.param("a" * 63, "", id="short-id"),
        pytest.param(f"{BLUE_ID},{BLUE_ID}", "", id="duplicate-within-color"),
        pytest.param(BLUE_ID, BLUE_ID, id="duplicate-across-colors"),
        pytest.param(",".join(f"{number:064x}" for number in range(1, 6)), "", id="five-ids"),
        pytest.param(f"{BLUE_ID} ", "", id="whitespace-in-id"),
    ],
)
def test_from_environment_rejects_invalid_preserved_stateful_csv(
    monkeypatch, tmp_path, blue, green
):
    configure_root(monkeypatch, tmp_path)
    monkeypatch.setenv("WEBCOMPILER_BLUE_PRESERVED_STATEFUL_IDS", blue)
    monkeypatch.setenv("WEBCOMPILER_GREEN_PRESERVED_STATEFUL_IDS", green)

    with pytest.raises((TypeError, ValueError, edge.EdgeError)):
        adapter.Config.from_environment()


@pytest.mark.parametrize(
    ("color", "config_attribute"),
    [("blue", "preserved_blue"), ("green", "preserved_green")],
)
def test_inventory_passes_the_matching_color_preserved_tuple(
    monkeypatch, tmp_path, color, config_attribute
):
    preserved_blue = (BLUE_ID, BLUE_ID_2)
    preserved_green = (GREEN_ID, GREEN_ID_2)
    config = adapter.Config(
        tmp_path.resolve(),
        edge.Layout(18000, 15173),
        (18001, 15174),
        (18002, 15175),
        preserved_blue=preserved_blue,
        preserved_green=preserved_green,
    )
    deployment = adapter.Deployment.__new__(adapter.Deployment)
    deployment.config = config
    deployment.store = object()
    deployment.call = lambda _args: None
    captured = []

    class FakeInventory:
        def __init__(self, *args, **kwargs):
            captured.append((args, kwargs))

    monkeypatch.setattr(adapter, "Inventory", FakeInventory)

    release = config.release(color, "e" * 40)
    deployment.inventory(release)

    assert len(captured) == 1
    assert captured[0][1]["preserved_stateful"] == getattr(config, config_attribute)
    assert captured[0][0][2] == f"{config.project_prefix}-{color}"

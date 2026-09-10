"""Reject malformed or managed observations from the preservation escape hatch."""

import pytest

from tests.test_edge_deploy import edge
from tests.test_preserved_stateful_inventory import add_legacy
from tests.test_runtime_inventory import inventory
from runtime_inventory import preserved_stateful_record


def legacy_observation(inventory_fixture):
    identity, item = add_legacy(inventory_fixture)
    project = inventory_fixture[2].project
    return identity, item, project


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("non-mapping", id="non-mapping-record"),
        pytest.param("missing-config", id="missing-config"),
        pytest.param("wrong-config-type", id="wrong-config-type"),
        pytest.param("wrong-mounts-type", id="wrong-mounts-type"),
        pytest.param("wrong-mount-type", id="wrong-mount-type"),
        pytest.param("wrong-destination-type", id="wrong-destination-type"),
        pytest.param("duplicate-destination", id="duplicate-destination"),
        pytest.param("too-many-mounts", id="33-mounts"),
    ],
)
def test_malformed_preserved_stateful_observations_are_rejected(inventory, case):
    identity, item, project = legacy_observation(inventory)

    if case == "non-mapping":
        item = None
    elif case == "missing-config":
        item.pop("Config")
    elif case == "wrong-config-type":
        item["Config"] = []
    elif case == "wrong-mounts-type":
        item["Mounts"] = {"Destination": "/var/lib/data"}
    elif case == "wrong-mount-type":
        item["Mounts"] = [None]
    elif case == "wrong-destination-type":
        item["Mounts"][0]["Destination"] = 123
    elif case == "duplicate-destination":
        item["Mounts"].append(dict(item["Mounts"][0]))
    else:
        item["Mounts"] = [
            {"Type": "volume", "Name": f"legacy-{number}", "Destination": f"/data/{number}"}
            for number in range(33)
        ]

    with pytest.raises(edge.EdgeError):
        preserved_stateful_record(item, identity, project)


@pytest.mark.parametrize("label", ["io.webcompiler.owner", "io.webcompiler.shared.role"])
def test_managed_shared_labels_are_not_accepted_for_preservation(inventory, label):
    identity, item, project = legacy_observation(inventory)
    item["Config"]["Labels"][label] = "fixture-managed-value"

    with pytest.raises(edge.EdgeError):
        preserved_stateful_record(item, identity, project)


def test_attachment_to_configured_shared_network_is_rejected(inventory):
    identity, item, project = legacy_observation(inventory)
    shared_network = "custom-shared-network"
    item["NetworkSettings"]["Networks"][shared_network] = {"NetworkID": "b" * 64}

    with pytest.raises(edge.EdgeError):
        preserved_stateful_record(item, identity, project, shared_network=shared_network)


def test_attachment_to_opposite_color_private_plane_is_rejected(inventory):
    identity, item, project = legacy_observation(inventory)
    item["NetworkSettings"]["Networks"]["webcompiler-green-api-plane"] = {
        "NetworkID": "c" * 64
    }

    with pytest.raises(edge.EdgeError):
        preserved_stateful_record(item, identity, project)

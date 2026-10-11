from copy import deepcopy

import pytest
import yaml
from optipool.estimator import Scenario, estimate
from optipool.metrics import summarize
from optipool.pricing import cost
from optipool.resources import node_eligible, pod_resources, quantity


@pytest.mark.parametrize(
    "value,expected",
    [("500m", 0.5), ("2Gi", 2 * 1024**3), ("1e3", 1000), ("20M", 20_000_000), ("1Ki", 1024), ("42", 42)],
)
def test_quantities(value, expected):
    assert quantity(value) == expected


@pytest.mark.parametrize("value", ["-1", "NaN", "1GiB", "inf", "1e999"])
def test_reject_invalid_quantities(value):
    with pytest.raises(ValueError):
        quantity(value)


def test_init_restartable_sidecar_and_overhead():
    def container(cpu, **kwargs):
        return {"resources": {"requests": {"cpu": cpu}}, **kwargs}

    spec = {
        "containers": [container("2")],
        "initContainers": [container("1", restartPolicy="Always"), container("4")],
        "overhead": {"cpu": "100m"},
    }
    assert pod_resources(spec)["cpu"] == 5.1
    assert pod_resources({"containers": [{"resources": {"limits": {"cpu": "1"}}}]})["cpu"] == 1


def empty_nodes(saved):
    for n in saved["nodes"]:
        n["requested"] = {"cpu": 0, "memory": 0}
        n["pod_count"] = 0
    saved["context"]["pods"] = []


def test_per_node_fragmentation_requires_new_node(saved):
    for n in saved["nodes"]:
        n["requested"]["cpu"] = 2.9
    result = estimate(saved, Scenario(cpu="1", memory="1Gi", replicas=1))
    assert result["outcome"] == "Needs nodes"
    assert result["additional_nodes"] == 1


def test_policy_is_per_resource_and_environment(saved):
    empty_nodes(saved)
    saved["node_templates"] = []
    for n in saved["nodes"]:
        n["requested"]["cpu"] = 3.0
    assert estimate(saved, Scenario(cpu="400m", replicas=1))["outcome"] == "Cannot fully assess"
    saved["pool"]["environment"] = "nonproduction"
    assert estimate(saved, Scenario(cpu="400m", replicas=1))["outcome"] == "Fits"
    for n in saved["nodes"]:
        n["requested"]["memory"] = n["allocatable"]["memory"]
    r = estimate(saved, Scenario(cpu="0", memory="1Mi", replicas=1))
    assert len(r["violations"]) == len(saved["nodes"])
    assert r["outcome"] != "Fits"


def test_existing_nodes_stay_and_autoscaler_limit_is_separate(saved):
    original = deepcopy(saved)
    saved["pool"]["autoscaler_max"] = len(saved["nodes"])
    result = estimate(saved, Scenario(cpu="2", memory="1Gi", replicas=10))
    assert result["additional_nodes"] > 0
    assert result["exceeds_autoscaler_max"]
    assert saved["nodes"] == original["nodes"]
    assert result["cost"]["synthetic"]


def deployment(spec, labels=None, replicas=2):
    return yaml.safe_dump(
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test"},
            "spec": {
                "replicas": replicas,
                "selector": {"matchLabels": labels or {"app": "test"}},
                "template": {"metadata": {"labels": labels or {"app": "test"}}, "spec": spec},
            },
        }
    )


def test_selector_and_taint_constraints(saved):
    spec = {
        "containers": [{"name": "test", "resources": {"requests": {"cpu": "100m", "memory": "1Mi"}}}],
        "nodeSelector": {"cloud.google.com/gke-nodepool": "other-pool"},
    }
    result = estimate(saved, Scenario(manifest=deployment(spec)))
    assert result["outcome"] == "Blocked constraints"
    node = deepcopy(saved["nodes"][0])
    node["taints"] = [{"key": "dedicated", "value": "batch", "effect": "NoSchedule"}]
    assert not node_eligible(node, {})
    assert node_eligible(node, {"tolerations": [{"key": "dedicated", "operator": "Equal", "value": "batch"}]})


def test_hard_anti_affinity_spreads_replicas(saved):
    empty_nodes(saved)
    spec = {
        "containers": [{"name": "test", "resources": {"requests": {"cpu": "100m"}}}],
        "affinity": {
            "podAntiAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": [
                    {
                        "labelSelector": {"matchLabels": {"app": "test"}},
                        "topologyKey": "kubernetes.io/hostname",
                    }
                ]
            }
        },
    }
    r = estimate(saved, Scenario(manifest=deployment(spec, replicas=4)))
    assert r["outcome"] == "Needs nodes"
    assert r["additional_nodes"] == 1
    assert len({p["node"] for p in r["placements"]}) == 4


def test_unsupported_storage_returns_conditional(saved):
    spec = {
        "containers": [{"name": "test"}],
        "volumes": [{"name": "disk", "persistentVolumeClaim": {"claimName": "data"}}],
    }
    r = estimate(saved, Scenario(manifest=deployment(spec)))
    assert r["outcome"] == "Cannot fully assess"
    assert any("Storage" in s for s in r["warnings"])


def test_pending_demand_consumes_capacity_first(saved):
    empty_nodes(saved)
    saved["nodes"] = saved["nodes"][:1]
    saved["context"]["pending"] = [
        {
            "name": "waiting",
            "namespace": "default",
            "spec": {"containers": [{"name": "waiting", "resources": {"requests": {"cpu": "3"}}}]},
        }
    ]
    r = estimate(saved, Scenario(cpu="1", replicas=1))
    assert r["additional_nodes"] == 1
    assert r["pending_replicas_accounted"] == 1
    assert r["placements"][0]["existing_demand"]


def test_search_exhaustion_is_not_proof(saved):
    r = estimate(saved, Scenario(cpu="2", replicas=100), max_added=1)
    assert r["outcome"] == "Cannot fully assess"
    assert r["additional_nodes"] is None
    assert "bound" in r["reason"]


def test_unknown_namespace_blocks_before_capacity(saved):
    result = estimate(saved, Scenario(namespace="absent"))
    assert result["outcome"] == "Blocked constraints"
    assert "namespace" in result["reason"]


def test_p99_independent_maxima_and_saved_window(saved):
    saved["metrics"] = {
        "cutoff": 1000000,
        "source": "fixture",
        "samples": [
            {
                "time": 1000000 - i * 100,
                "replica": replica,
                "workload": "w",
                "cpu": cpu,
                "memory": mem,
                "attributed": True,
            }
            for replica, cpu, mem in [("cpu-pod", 2, 10), ("memory-pod", 1, 20)]
            for i in range(25)
        ],
    }
    saved["metrics"]["samples"].append(
        {
            "time": 1000000,
            "replica": "unknown",
            "workload": "w",
            "cpu": 100,
            "memory": 100,
            "attributed": False,
        }
    )
    result = summarize(saved, 1)
    assert result["cutoff"] == 1000000
    assert result["start"] == 1000000 - 86400
    m = result["workloads"]["w"]
    assert m["cpu_p99"] == 2 and m["memory_p99"] == 20
    assert m["cpu_replica"] == "cpu-pod" and m["memory_replica"] == "memory-pod"
    assert result["timeline"][0]["cpu"] == 3


def test_missing_metrics_not_zero(saved):
    saved["metrics"]["samples"] = []
    assert summarize(saved, 10)["workloads"] == {}
    saved["metrics"]["samples"] = [
        {
            "time": saved["metrics"]["cutoff"],
            "replica": "r",
            "workload": "w",
            "attributed": True,
            "memory": 10,
        }
    ]
    assert summarize(saved, 10)["timeline"][0]["cpu"] is None


def test_cost_component_commitment_and_730_hours(saved):
    r = cost(saved["pricing"], 2)
    assert r["on_demand_monthly"] == pytest.approx((0.12 + 0.07 + 0.014) * 2 * 730)
    assert r["cud_3y_hourly"] == pytest.approx((0.058 + 0.034 + 0.014) * 2)
    assert r["commitment_3y_obligation"] == pytest.approx((0.058 + 0.034) * 2 * 24 * 365 * 3)
    assert not cost({}, 1)["available"]
    assert not cost({"components": [{"on_demand_hourly": None}]}, 1)["available"]

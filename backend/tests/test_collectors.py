from copy import deepcopy

import pytest
from optipool.collector import CloudCollector, normalize


def raw_fixture():
    def meta(name, uid, **extra):
        return {"name": name, "uid": uid, "namespace": "shop", **extra}

    template = {
        "metadata": {"labels": {"app": "api"}},
        "spec": {
            "containers": [{"name": "api", "resources": {"requests": {"cpu": "500m", "memory": "1Gi"}}}],
            "nodeSelector": {"cloud.google.com/gke-nodepool": "services"},
        },
    }
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": meta("api", "d"),
        "spec": {"replicas": 3, "template": template},
    }
    rs = {
        "kind": "ReplicaSet",
        "metadata": meta(
            "api-rs",
            "r",
            ownerReferences=[{"kind": "Deployment", "name": "api", "uid": "d", "controller": True}],
        ),
        "spec": {"replicas": 3},
    }
    pod = {
        "kind": "Pod",
        "metadata": meta(
            "api-one",
            "p",
            creationTimestamp="2026-10-01T00:00:00Z",
            labels={"app": "api"},
            ownerReferences=[{"kind": "ReplicaSet", "name": "api-rs", "uid": "r", "controller": True}],
        ),
        "spec": {**deepcopy(template["spec"]), "nodeName": "node-a"},
        "status": {"phase": "Running", "containerStatuses": [{"restartCount": 2}]},
    }
    node = {
        "kind": "Node",
        "metadata": {
            "name": "node-a",
            "labels": {
                "cloud.google.com/gke-nodepool": "services",
                "topology.kubernetes.io/zone": "us-central1-a",
                "kubernetes.io/hostname": "node-a",
            },
        },
        "spec": {},
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "allocatable": {"cpu": "3920m", "memory": "14Gi", "pods": "110"},
        },
    }
    raw = {
        key: []
        for key in [
            "deployments",
            "replicasets",
            "statefulsets",
            "daemonsets",
            "jobs",
            "cronjobs",
            "nodes",
            "pods",
            "services",
            "quotas",
            "limit_ranges",
            "pv",
            "pvc",
            "storage_classes",
        ]
    }
    raw.update(
        deployments=[deployment],
        replicasets=[rs],
        pods=[pod],
        nodes=[node],
        services=[{"metadata": meta("api-service", "s"), "spec": {"selector": {"app": "api"}}}],
    )
    return raw


def test_ownership_services_desired_and_effective_requests(saved):
    pool = {**saved["pool"], "raw_config": {}}
    value = normalize(pool, raw_fixture(), [])
    w = value["workloads"][0]
    assert w["id"] == "shop/Deployment/api"
    assert w["services"] == ["api-service"] and w["desired"] == 3 and w["running"] == 1
    assert w["pool_replicas"] == 1 and w["requested"]["cpu"] == 0.5
    assert value["nodes"][0]["pod_count"] == 1
    assert len(value["context"]["pending"]) == 2
    assert value["context"]["pods"][0]["restarts"] == 2


def test_pending_not_counted_twice_and_multipool_is_uncertain(saved):
    raw = raw_fixture()
    p = deepcopy(raw["pods"][0])
    p["metadata"].update(name="api-two", uid="p2")
    p["spec"].pop("nodeName")
    p["status"]["phase"] = "Pending"
    raw["pods"].append(p)
    value = normalize({**saved["pool"], "raw_config": {}}, raw, [])
    assert len(value["context"]["pending"]) == 2  # one Pending + one not yet materialized
    p["spec"].pop("nodeSelector")
    other = deepcopy(raw["nodes"][0])
    other["metadata"]["name"] = "node-b"
    other["metadata"]["labels"]["cloud.google.com/gke-nodepool"] = "workers"
    raw["nodes"].append(other)
    value = normalize({**saved["pool"], "raw_config": {}}, raw, [])
    assert any("multiple pools" in w for w in value["context"]["uncertainties"])


def test_dynamic_discovery_pagination_permissions_and_allowlist(settings):
    collector = object.__new__(CloudCollector)
    collector.settings = settings
    calls = []

    def get(url, params=None, verify=True):
        calls.append((url, dict(params or {})))
        if "projects:search" in url:
            if not params.get("pageToken"):
                return {"projects": [{"projectId": "visible-a", "state": "ACTIVE"}], "nextPageToken": "next"}
            return {
                "projects": [
                    {"projectId": "visible-b", "state": "ACTIVE"},
                    {"projectId": "deleted", "state": "DELETE_REQUESTED"},
                ]
            }
        if "/visible-b/" in url:
            raise ValueError("permission denied")
        return {
            "clusters": [
                {
                    "name": "cluster",
                    "location": "us-central1",
                    "locations": ["us-central1-a"],
                    "nodePools": [
                        {
                            "name": "services",
                            "config": {"machineType": "n2-standard-4"},
                            "autoscaling": {"enabled": True, "maxNodeCount": 4},
                        }
                    ],
                }
            ]
        }

    collector.get = get
    pools, success, errors = collector.discover()
    assert len(pools) == 1 and success == ["visible-a"] and errors[0]["scope"] == "visible-b"
    assert any(p.get("pageToken") == "next" for _, p in calls)
    settings.project_allowlist = ["visible-a"]
    assert collector.discover()[2] == []


def test_core_endpoint_failure_never_returns_snapshot(saved, settings):
    collector = object.__new__(CloudCollector)
    collector.settings = settings
    pool = {**saved["pool"], "environment": "nonproduction"}
    collector.get = lambda *args, **kwargs: {
        "name": pool["cluster"],
        "location": pool["location"],
        "endpoint": "127.0.0.1",
        "masterAuth": {"clusterCaCertificate": "Y2E="},
        "nodePools": [{"name": pool["name"], "config": {}}],
    }

    def missing(*args, **kwargs):
        raise ValueError("Kubernetes list forbidden")

    collector.pages = missing
    settings.default_environment = "nonproduction"
    with pytest.raises(ValueError, match="forbidden"):
        collector.collect(pool)


def test_exact_catalog_components_and_missing_price(saved, settings):
    collector = object.__new__(CloudCollector)
    collector.settings = settings
    pool = saved["pool"]
    key = "us-central1/n2-standard-4/STANDARD/pd-balanced/100"
    assert collector.prices(pool)["components"] == []
    settings.pricing_mappings[key] = {
        "components": [
            {
                "name": "CPU",
                "quantity": 4,
                "unit": "h",
                "on_demand_sku": "normal",
                "cud_eligible": True,
                "cud_model": "resource-3y",
                "cud_3y_sku": "cud",
            }
        ]
    }

    def sku(sid, rate):
        return {
            "skuId": sid,
            "serviceRegions": ["us-central1"],
            "pricingInfo": [
                {
                    "effectiveTime": "2026-01-01T00:00:00Z",
                    "pricingExpression": {
                        "usageUnit": "h",
                        "tieredRates": [{"unitPrice": {"currencyCode": "USD", "nanos": int(rate * 1e9)}}],
                    },
                }
            ],
        }

    collector.pages = lambda *args, **kwargs: [sku("normal", 0.03), sku("cud", 0.01)]
    value = collector.prices(pool)["components"][0]
    assert value["on_demand_hourly"] == 0.12 and value["cud_3y_hourly"] == 0.04
    pool = {**pool, "provisioning_model": "SPOT"}
    settings.pricing_mappings[key.replace("STANDARD", "SPOT")] = settings.pricing_mappings[key]
    with pytest.raises(ValueError, match="eligible"):
        collector.prices(pool)


def test_gmp_attribution_ignores_prior_same_name_pod(saved, settings):
    import time

    collector = object.__new__(CloudCollector)
    collector.settings = settings
    pod = saved["context"]["pods"][0]
    pod["created"] = time.time() - 1000
    samples = [[pod["created"] - 100, "99"], [int(time.time()), "0.2"]]
    collector.get = lambda *args, **kwargs: {
        "status": "success",
        "data": {
            "result": [{"metric": {"namespace": pod["namespace"], "pod": pod["name"]}, "values": samples}]
        },
    }
    metrics = collector.metrics(saved["pool"], saved)
    assert metrics["source"] == "GMP cAdvisor"
    assert len(metrics["samples"]) == 1
    assert metrics["samples"][0]["cpu"] == 0.2
    assert "partial" in metrics["coverage"]

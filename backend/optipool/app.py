import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .auth import Auth
from .comparison import compare
from .config import load_settings
from .demo import DemoCollector
from .estimator import Scenario, estimate
from .exports import pod_rows, pool_rows, render, workload_rows
from .recommendations import recommend
from .store import Store
from .views import SavedViews

logger = logging.getLogger("optipool")


def create_app(settings=None, collector=None):
    settings = settings or load_settings()
    store = Store(settings.database)
    recorded_mode = store.metadata("collection_mode")
    if not recorded_mode:
        existing = store.inventory()
        recorded_mode = "demo" if existing and all(p.get("synthetic") for p in existing) else settings.mode
    if recorded_mode != settings.mode:
        store.close()
        raise ValueError("Demo and live collection require separate databases; choose a new database path")
    store.set_metadata("collection_mode", settings.mode)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="collection")
    # Live ADC is loaded inside the first collection job, so cached viewing survives credential outages.
    state = {"collector": collector or (DemoCollector(settings) if settings.mode == "demo" else None)}
    auth = Auth(settings)
    views = SavedViews(store, settings.min_metric_samples)

    def source():
        if state["collector"] is None:
            from .collector import CloudCollector

            state["collector"] = CloudCollector(settings)
        return state["collector"]

    def collect_pool(pool_id):
        pool = store.pool(pool_id)
        if not pool or not pool["available"]:
            raise ValueError("Pool is unavailable; refresh inventory")
        payload = source().collect(pool)
        store.publish_snapshot(pool_id, payload)

    def run(job, initial=False):
        store.update_job(job["id"], "running")
        started = time.monotonic()
        try:
            if job["kind"] == "inventory":
                pools, successful, errors = source().discover()
                store.publish_inventory(pools, successful, errors)
                if initial:
                    for pool in store.inventory():
                        if pool["available"] and not pool["snapshot_id"]:
                            pjob, fresh = store.enqueue(pool["id"], "pool", "initial-import")
                            if fresh:
                                run(pjob)
                    store.set_metadata("initialized", "true")
                if errors:
                    raise ValueError("Inventory partially discovered; see inventory errors")
            else:
                collect_pool(job["scope"])
            store.update_job(job["id"], "succeeded")
            store.prune()
            logger.info(
                json.dumps(
                    {
                        "event": "collection",
                        "job": job["id"],
                        "state": "succeeded",
                        "duration_seconds": time.monotonic() - started,
                    }
                )
            )
        except Exception as exc:
            store.update_job(job["id"], "failed", str(exc)[:1000])
            logger.warning(json.dumps({"event": "collection", "job": job["id"], "state": "failed"}))

    @asynccontextmanager
    async def lifespan(app):
        if not store.metadata("initialized"):
            job, fresh = store.enqueue("all", "inventory", "initial-import")
            if fresh:
                executor.submit(run, job, True)
        yield
        executor.shutdown(wait=True)
        store.close()

    app = FastAPI(
        title="OptiPool",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.auth_mode == "local" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.auth_mode == "local" else None,
    )
    app.state.store = store

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        # Same-origin JSON mutations reject cross-site form submissions.
        if request.url.path.startswith("/api/") and request.method == "POST":
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return Response("JSON content type required", status_code=415)
            origin = request.headers.get("origin")
            if origin:
                from urllib.parse import urlsplit

                if urlsplit(origin).netloc != request.headers.get("host"):
                    return Response("Cross-origin mutation rejected", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        store.metadata("initialized")
        return {"status": "ok"}

    @app.get("/api/inventory")
    def inventory(actor=Depends(auth)):
        pools = store.inventory()
        summaries = {}
        for pool in pools:
            summary = pool.pop("snapshot_summary", None)
            saved_pool = pool.pop("snapshot_pool", None)
            if saved_pool:
                pool.update(
                    {
                        **saved_pool,
                        "available": pool["available"],
                        "snapshot_id": pool["snapshot_id"],
                        "snapshot_at": pool["snapshot_at"],
                    }
                )
            if summary is not None:
                summaries[pool["id"]] = summary
        return {
            "pools": pools,
            "summaries": summaries,
            "mode": settings.mode,
            "actor": actor,
            "inventory_at": store.metadata("inventory_at"),
            "errors": json.loads(store.metadata("inventory_errors") or "[]"),
            "initialized": bool(store.metadata("initialized")),
            "discovery_job": store.latest_job("all", "inventory"),
        }

    def snapshot(pool_id):
        value = store.snapshot(pool_id=pool_id, include_metrics=False)
        if value is None:
            raise HTTPException(404, "Pool has no saved snapshot. Use Fetch latest live data.")
        return value

    def saved_view(pool_id, days, snapshot_id=None):
        content = views.get(pool_id, days, snapshot_id)
        if content is None:
            raise HTTPException(404, "Pool has no saved snapshot. Use Fetch latest live data.")
        return content

    @app.get("/api/snapshot")
    def get_snapshot(pool_id: str, days: int = Query(3, ge=1, le=10), actor=Depends(auth)):
        return Response(saved_view(pool_id, days), media_type="application/json")

    @app.get("/api/recommendations")
    def recommendations(
        pool_id: str,
        days: int = Query(3, ge=1, le=10),
        headroom: int = Query(20, ge=0, le=100),
        snapshot_id: str | None = None,
        actor=Depends(auth),
    ):
        value = json.loads(saved_view(pool_id, days, snapshot_id))
        return recommend(value, value["usage"], headroom)

    @app.get("/api/snapshots")
    def snapshots(pool_id: str, actor=Depends(auth)):
        return store.snapshots(pool_id)

    @app.get("/api/snapshots/compare")
    def comparison(pool_id: str, before: str, after: str, actor=Depends(auth)):
        values = [store.snapshot(snapshot_id=sid, include_metrics=False) for sid in [before, after]]
        if any(v is None or v["pool"]["id"] != pool_id for v in values):
            raise HTTPException(404, "Both snapshots must be saved for the selected pool")
        return compare(*values)

    @app.post("/api/refresh/inventory", status_code=202)
    def refresh_inventory(actor=Depends(auth)):
        job, fresh = store.enqueue("all", "inventory", actor)
        if fresh:
            executor.submit(run, job, not bool(store.metadata("initialized")))
        return job

    @app.post("/api/refresh/pool", status_code=202)
    def refresh_pool(pool_id: str, actor=Depends(auth)):
        pool = store.pool(pool_id)
        if not pool or not pool["available"]:
            raise HTTPException(404, "Pool unavailable")
        job, fresh = store.enqueue(pool_id, "pool", actor)
        if fresh:
            executor.submit(run, job)
        return job

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str, actor=Depends(auth)):
        value = store.job(job_id)
        if not value:
            raise HTTPException(404, "Job not found")
        return value

    @app.post("/api/estimate")
    def estimate_route(scenario: Scenario, pool_id: str, actor=Depends(auth)):
        try:
            value = snapshot(pool_id)
            if scenario.pod()[2] > settings.max_replicas:
                raise ValueError("Replica count exceeds the configured simulation bound")
            result = estimate(value, scenario, settings.max_added_nodes, settings.max_replicas)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None
        ident = store.save_estimate(value["id"], scenario.model_dump(), result, actor)
        return {"id": ident, **result}

    @app.get("/api/estimates")
    def history(pool_id: str, actor=Depends(auth)):
        return store.estimates(pool_id)

    @app.get("/api/export/{table}")
    def export(
        table: str,
        format: str = "csv",
        pool_id: str | None = None,
        project: str | None = None,
        cluster: str | None = None,
        days: int = Query(3, ge=1, le=10),
        snapshot_id: str | None = None,
        actor=Depends(auth),
        pod_search: str = Query("", max_length=200),
    ):
        if format not in {"csv", "xlsx"} or table not in {"node-pools", "workloads", "pods"}:
            raise HTTPException(422, "Choose node-pools/workloads/pods and csv/xlsx")
        if table == "node-pools":
            pools = [
                p
                for p in store.inventory()
                if (not project or p["project"] == project) and (not cluster or p["cluster"] == cluster)
            ]
            rows = pool_rows(pools)
        else:
            if not pool_id:
                raise HTTPException(422, "pool_id required")
            value = json.loads(saved_view(pool_id, days, snapshot_id))
            rows = (
                pod_rows(value, pod_search, value["usage"])
                if table == "pods"
                else workload_rows(value, value["usage"])
            )
        content, mime = render(rows, format, table)
        return Response(
            content,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="optipool-{table}.{format}"',
                "Cache-Control": "no-store",
            },
        )

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
        if (dist / "licenses").exists():
            app.mount("/licenses", StaticFiles(directory=dist / "licenses"), name="licenses")

        @app.get("/", dependencies=[Depends(auth)])
        def index():
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})

    return app

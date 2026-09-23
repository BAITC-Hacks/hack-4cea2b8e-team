"""FastAPI-приложение: API + отдача фронтенда без сборки.

Запуск:  uvicorn app.main:app --reload
Открыть: http://localhost:8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipeline import typologies

from . import config, db, llm
from .graph_store import GraphStore
from .responses import GraphJSONResponse

graph_store = GraphStore()

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    graph_store.load(config.DATA_DIR)
    yield


app = FastAPI(title=config.APP_NAME, lifespan=lifespan, default_response_class=GraphJSONResponse)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# ---------------------------------------------------------------- модели ---
class GenerateIn(BaseModel):
    prompt: str
    system: str | None = None


class ItemIn(BaseModel):
    title: str
    payload: dict[str, Any] = {}


class CommonReceiversIn(BaseModel):
    gids: list[int] = Field(min_length=2, max_length=20)
    limit: int = Field(default=50, ge=1, le=200)


Direction = Literal["in", "out", "both"]
Role = Literal["consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"]
Typology = Literal["structuring", "layering", "synchronized-inflow", "round-tripping"]


# ------------------------------------------------------------------- API ---
@app.get("/api/health")
def health() -> dict[str, Any]:
    """Эндпоинт для быстрой проверки «оно живое». Упомяните его в README."""
    return {
        "status": "ok",
        "app": config.APP_NAME,
        "demo_mode": config.DEMO_MODE,
        "model": config.MODEL,
        "graph_loaded": graph_store.analysis is not None,
        "n_nodes": len(graph_store.nodes),
        **db.stats(),
    }


@app.post("/api/generate")
def generate(body: GenerateIn) -> dict[str, str]:
    if not body.prompt.strip():
        raise HTTPException(400, "prompt пустой")
    text = llm.complete(body.prompt, body.system or "Ты — полезный ассистент.")
    return {"text": text}


@app.post("/api/generate/stream")
def generate_stream(body: GenerateIn) -> StreamingResponse:
    return StreamingResponse(
        llm.stream(body.prompt, body.system or "Ты — полезный ассистент."),
        media_type="text/plain; charset=utf-8",
    )


@app.get("/api/items")
def get_items() -> list[dict[str, Any]]:
    return db.list_items()


@app.post("/api/items")
def post_item(body: ItemIn) -> dict[str, int]:
    return {"id": db.add_item(body.title, body.payload)}


@app.delete("/api/items/{item_id}")
def remove_item(item_id: int) -> dict[str, bool]:
    db.delete_item(item_id)
    return {"ok": True}


def _node_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "gid": record["gid"],
        "role": record["role"],
        "priority_score": record["priority_score"],
        "depth": record["depth"],
        "is_seed": record["is_seed"],
        "cluster_id": record["cluster_id"],
        "role_score": record["role_score"],
        "truncated": record["truncated"],
        "sum_in": record["sum_in"],
        "sum_out": record["sum_out"],
        "typologies": record["typologies"],
        "evidence": record["evidence"],
        "in_degree": record["in_degree"],
        "out_degree": record["out_degree"],
        "n_tx_in": int(record["n_tx_in"]),
        "n_tx_out": int(record["n_tx_out"]),
        "passthrough_ratio": record["passthrough_ratio"],
        "ratio_reliable": record["ratio_reliable"],
    }


def _subgraph_response(
    center: int, records: list[dict[str, Any]], truncated: bool
) -> dict[str, Any]:
    node_ids = {record["gid"] for record in records}
    return {
        "center": center,
        "nodes": [_node_summary(record) for record in records],
        "edges": graph_store.edges_between(node_ids),
        "truncated": truncated,
    }


@app.get("/api/node/{gid}")
def get_node(gid: int) -> dict[str, Any]:
    record = graph_store.card(gid)
    if record is None:
        raise HTTPException(404, "узел не найден")
    return record


@app.get("/api/subgraph")
def get_subgraph(
    gid: int,
    hops: int = Query(2, ge=0, le=10),
    limit: int = Query(150, ge=1, le=1000),
    direction: Direction = "both",
) -> dict[str, Any]:
    if graph_store.node(gid) is None:
        raise HTTPException(404, "узел не найден")
    records, truncated = graph_store.subgraph_nodes(gid, hops, limit, direction)
    return _subgraph_response(gid, records, truncated)


@app.get("/api/cluster/{cluster_id}")
def get_cluster(
    cluster_id: int, limit: int = Query(150, ge=1, le=1000)
) -> dict[str, Any]:
    records, truncated = graph_store.cluster_nodes(cluster_id, limit)
    if not records:
        raise HTTPException(404, "кластер не найден")
    response = _subgraph_response(cluster_id, records, truncated)
    response["cluster_id"] = cluster_id
    return response


@app.get("/api/top")
def get_top(limit: int = Query(25, ge=1, le=1000)) -> list[dict[str, Any]]:
    return graph_store.top(limit)


@app.get("/api/search")
def search_nodes(q: str = Query(..., min_length=1)) -> list[dict[str, Any]]:
    return graph_store.search(q)


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    """Сводка для первого экрана, ограничения данных и формула приоритета."""
    assert graph_store.analysis is not None
    return graph_store.analysis.overview()


@app.get("/api/clusters")
def clusters() -> list[dict[str, Any]]:
    assert graph_store.analysis is not None
    return graph_store.analysis.clusters.to_dict("records")


@app.get("/api/nodes")
def list_nodes(
    role: Role | None = None, cluster_id: int | None = None,
    is_seed: bool | None = None, truncated: bool | None = None,
    min_priority: float = Query(0, ge=0, le=1), q: str = "",
    typology: Typology | None = None,
    limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    records = graph_store.filtered(role=role, cluster_id=cluster_id, is_seed=is_seed,
                                   truncated=truncated, min_priority=min_priority, q=q, typology=typology)
    return {"total": len(records), "offset": offset, "limit": limit,
            "items": records[offset:offset + limit]}


@app.get("/api/path")
def directed_path(source: int, target: int, max_hops: int = Query(6, ge=1, le=10)) -> dict[str, Any]:
    for gid in (source, target):
        if graph_store.node(gid) is None:
            raise HTTPException(404, f"узел {gid} не найден")
    return graph_store.path(source, target, max_hops)


@app.get("/api/graph")
def graph_view(role: Role | None = None, cluster_id: int | None = None,
               is_seed: bool | None = None, truncated: bool | None = None,
               min_priority: float = Query(0, ge=0, le=1),
               typology: Typology | None = None,
               limit: int = Query(150, ge=1, le=3000)) -> dict[str, Any]:
    """Обзор графа: фильтры применяются к узлам, рёбра соединяют выбранные узлы."""
    records = graph_store.filtered(role=role, cluster_id=cluster_id, is_seed=is_seed,
                                   truncated=truncated, min_priority=min_priority, typology=typology)
    selected = records[:limit]
    return {"nodes": [_node_summary(r) for r in selected],
            "edges": graph_store.edges_between({r["gid"] for r in selected}),
            "total": len(records), "truncated": len(records) > limit}


@app.post("/api/common-receivers")
def common_receivers(body: CommonReceiversIn) -> dict[str, Any]:
    gids = sorted(set(body.gids))
    if len(gids) < 2:
        raise HTTPException(422, "нужны минимум два различных gid")
    for gid in gids:
        if graph_store.node(gid) is None:
            raise HTTPException(404, f"узел {gid} не найден")
    return graph_store.common_receivers(gids, body.limit)


@app.get("/api/node/{gid}/transactions")
def node_transactions(gid: int, direction: Direction = "both",
                      date_from: date | None = None, date_to: date | None = None,
                      limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0),
                      counterparty: int | None = None) -> dict[str, Any]:
    if graph_store.node(gid) is None:
        raise HTTPException(404, "узел не найден")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "начало периода позже конца")
    if counterparty is not None and graph_store.node(counterparty) is None:
        raise HTTPException(404, "контрагент не найден")
    return graph_store.transactions(gid, limit, offset, direction,
                                    date_from.isoformat() if date_from else None,
                                    date_to.isoformat() if date_to else None, counterparty)


@app.get("/api/node/{gid}/flows")
def node_flows(gid: int, direction: Literal["in", "out"] = "out",
               limit: int = Query(5, ge=1, le=20), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    """Читаемый шаг цепочки: до пяти контрагентов с суммами, датами и долями."""
    if graph_store.node(gid) is None:
        raise HTTPException(404, "узел не найден")
    return graph_store.flows(gid, direction, limit, offset)


@app.get("/api/export/{filename}")
def export_csv(filename: Literal["nodes_roles.csv", "clusters.csv", "top_nodes.csv"]) -> StreamingResponse:
    """CSV в точности из результата, который видит аналитик в API."""
    assert graph_store.analysis is not None
    csv = graph_store.analysis.tables()[filename].to_csv(index=False)
    return StreamingResponse(iter([csv]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/resilience")
def resilience(top: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
    gids = [row["gid"] for row in graph_store.top(top)]
    return {**typologies.resilience(graph_store.graph, gids), "gids": gids,
            "interpretation": "Удаление узлов из наблюдаемого графа; это оценка связности, а не прогноз прекращения переводов."}


# -------------------------------------------------------------- фронтенд ---
@app.get("/graph", response_class=FileResponse)
def graph_page() -> FileResponse:
    """Экран расследования Кости. /graph.html также доступен через статику."""
    return FileResponse(WEB_DIR / "graph.html")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=WEB_DIR), name="web")

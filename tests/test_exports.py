"""Контракт обязательных CSV из ТЗ одинаков для CLI и HTTP-экспорта."""
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pipeline.analysis import analyze

# Фиксируем внешний контракт буквально, независимо от констант реализации.
SCHEMAS = {
    "nodes_roles.csv": ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"],
    "clusters.csv": ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"],
    "top_nodes.csv": ["rank", "gid", "role", "priority_score", "why"],
}


@pytest.fixture(scope="module")
def export_data(tmp_path_factory):
    folder = tmp_path_factory.mktemp("export-input")
    gids = [100000000000000001 + i for i in range(25)]
    pd.DataFrame({"gid": gids, "depth": [0] + [1] * 24,
                  "is_seed": [True] + [False] * 24}).to_parquet(folder / "nodes.parquet")
    pd.DataFrame({"src": [gids[0]] * 24, "dst": gids[1:], "sum_kzt": [20000] * 24,
                  "n_tx": [4] * 24, "depth": [1] * 24}).to_parquet(folder / "edges.parquet")
    pd.DataFrame([{"src": gids[0], "dst": gid, "sum_kzt": 5000, "date": "2026-07-15"}
                  for gid in gids[1:] for _ in range(4)]).to_parquet(folder / "transactions.parquet")
    return folder


def check_required(tables):
    for name, columns in SCHEMAS.items():
        assert tables[name].columns.tolist() == columns
        assert tables[name].notna().all().all()
    nodes, top = tables["nodes_roles.csv"], tables["top_nodes.csv"]
    assert len(nodes) == 25 and len(top) >= 20
    assert nodes.gid.dtype == "int64"
    assert nodes.gid.tolist() == list(range(100000000000000001, 100000000000000026))
    assert top.gid.isin(nodes.gid).all()
    assert nodes.role_score.between(0, 1).all()
    assert nodes.priority_score.between(0, 1).all()
    assert nodes.evidence.str.len().between(1, 200).all()
    assert top.priority_score.is_monotonic_decreasing
    assert top["rank"].tolist() == list(range(1, len(top) + 1))


@pytest.mark.parametrize("extended", [False, True])
def test_cli_exact_csv_schema(export_data, tmp_path, extended):
    command = [sys.executable, "-m", "pipeline.run", "--data", str(export_data),
               "--out", str(tmp_path), "--top", "1"]
    if extended:
        command.append("--extended")
    subprocess.run(command, check=True, capture_output=True, text=True,
                   cwd=Path(__file__).resolve().parents[1])
    tables = {p.name: pd.read_csv(p) for p in tmp_path.glob("*.csv")}
    check_required(tables)
    expected = set(SCHEMAS)
    if extended:
        expected |= {"nodes_roles_extended.csv", "top_nodes_extended.csv"}
        for name in ["nodes_roles", "top_nodes"]:
            expanded = tables[name + "_extended.csv"]
            pd.testing.assert_frame_equal(expanded[SCHEMAS[name + ".csv"]], tables[name + ".csv"])
            assert "typologies" in expanded.columns
        assert tables["nodes_roles_extended.csv"].typologies.notna().any()
    assert set(tables) == expected


def test_api_exports_match_analysis(export_data, monkeypatch):
    import app.main as main
    analysis = analyze(export_data)
    monkeypatch.setattr(main, "graph_store", SimpleNamespace(analysis=analysis))
    monkeypatch.setattr(main.app.state, "data_ready", True, raising=False)
    # Без lifespan: только синтетический результат, без файлов пользователя и SQLite.
    client = TestClient(main.app)
    tables = {}
    for filename, expected in analysis.tables(extended=True).items():
        response = client.get("/api/export/" + filename)
        assert response.status_code == 200
        assert response.text == expected.to_csv(index=False)
        assert filename in response.headers["content-disposition"]
        tables[filename] = pd.read_csv(StringIO(response.text))
    check_required(tables)
    assert client.get("/api/export/unknown.csv").status_code == 422
    assert "typologies" in analysis.top().columns  # JSON-топ сохраняет расширение.

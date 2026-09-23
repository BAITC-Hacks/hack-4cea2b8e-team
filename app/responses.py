"""Идентификаторы int64 передаются в браузер строками без потери точности."""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def browser_ids(value: Any) -> Any:
    """Преобразуем только идентификаторы клиентов, не суммы и номера кластеров."""
    if isinstance(value, list):
        return [browser_ids(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"gid", "src", "dst", "source", "target"} and isinstance(item, int):
            result[key] = str(item)
        elif key == "center" and "cluster_id" not in value and isinstance(item, int):
            result[key] = str(item)
        elif key == "gids" and isinstance(item, list):
            result[key] = [str(gid) for gid in item]
        else:
            result[key] = browser_ids(item)
    return result


class GraphJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return super().render(browser_ids(content))

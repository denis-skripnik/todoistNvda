from __future__ import annotations

import addonHandler
import json
from datetime import datetime
from typing import Any
from urllib import error, parse, request


API_BASE = "https://api.todoist.com/api/v1"
SYNC_API_BASE = "https://api.todoist.com/sync/v9"


addonHandler.initTranslation()


class TodoistError(Exception):
    pass


def _value(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def get_task_id(task: dict[str, Any]) -> str:
    return str(_value(task, "id", "task_id") or "")


def get_task_content(task: dict[str, Any]) -> str:
    return str(_value(task, "content") or "").strip()


def get_task_project_id(task: dict[str, Any]) -> str:
    return str(_value(task, "project_id", "projectId") or "")


def get_task_parent_id(task: dict[str, Any]) -> str:
    return str(_value(task, "parent_id", "parentId", "v2_parent_id") or "")


def get_task_labels(task: dict[str, Any]) -> list[str]:
    labels = _value(task, "labels")
    if not isinstance(labels, list):
        return []
    return [str(label).strip() for label in labels if str(label).strip()]


def get_due(task: dict[str, Any]) -> dict[str, Any]:
    due = _value(task, "due")
    if isinstance(due, dict):
        return due
    return {}


def get_due_text(task: dict[str, Any]) -> str:
    due = get_due(task)
    return str(
        _value(due, "string")
        or _value(due, "datetime")
        or _value(due, "date")
        or ""
    ).strip()


def get_due_date_value(task: dict[str, Any]) -> str:
    due = get_due(task)
    return str(_value(due, "date") or "").strip()


def parse_due_datetime(task: dict[str, Any]) -> datetime | None:
    due = get_due(task)
    raw_value = str(_value(due, "datetime") or _value(due, "date") or "").strip()
    if not raw_value:
        return None
    if "T" not in raw_value:
        return None
    normalized = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


class TodoistClient:
    def __init__(self, api_key: str, timeout: int = 30):
        self._api_key = api_key.strip()
        self._timeout = timeout
        if not self._api_key:
            raise TodoistError(_("Todoist API key is not configured."))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        base_url: str = API_BASE,
    ) -> Any:
        url = f"{base_url}{path}"
        if params:
            filtered = {
                key: value
                for key, value in params.items()
                if value is not None and value != ""
            }
            if filtered:
                url = f"{url}?{parse.urlencode(filtered, doseq=True)}"

        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = request.Request(
            url,
            data=data,
            headers=self._headers(),
            method=method.upper(),
        )

        try:
            with request.urlopen(req, timeout=self._timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TodoistError(
                _("Todoist request failed with status {status}: {body}").format(
                    status=exc.code,
                    body=body or exc.reason,
                )
            )
        except error.URLError as exc:
            raise TodoistError(_("Todoist connection failed: {error}").format(error=exc))

        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return raw.decode("utf-8", errors="replace")

    def _paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor = None
        while True:
            page_params = dict(params or {})
            if cursor:
                page_params["cursor"] = cursor
            response = self._request("GET", path, params=page_params)
            if isinstance(response, list):
                results.extend(item for item in response if isinstance(item, dict))
                break
            if not isinstance(response, dict):
                break
            page_results = response.get("results")
            if isinstance(page_results, list):
                results.extend(item for item in page_results if isinstance(item, dict))
            cursor = response.get("next_cursor")
            if not cursor:
                break
        return results

    def _normalize_completed_item(self, item: dict[str, Any]) -> dict[str, Any]:
        task = dict(item.get("item_object") or {})
        task["id"] = str(item.get("task_id") or task.get("id") or "")
        task["content"] = str(item.get("content") or task.get("content") or "").strip()
        task["project_id"] = str(item.get("project_id") or task.get("project_id") or "")
        task["parent_id"] = str(
            task.get("parent_id")
            or task.get("v2_parent_id")
            or item.get("parent_id")
            or ""
        )
        task["_completed_at"] = str(item.get("completed_at") or "").strip()
        return task

    def get_projects(self) -> list[dict[str, Any]]:
        return self._paginate("/projects")

    def create_project(self, name: str) -> dict[str, Any]:
        response = self._request("POST", "/projects", payload={"name": name})
        return response if isinstance(response, dict) else {}

    def get_labels(self) -> list[dict[str, Any]]:
        return self._paginate("/labels")

    def create_label(self, name: str) -> dict[str, Any]:
        response = self._request("POST", "/labels", payload={"name": name})
        return response if isinstance(response, dict) else {}

    def get_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        params = {"project_id": project_id} if project_id else None
        return self._paginate("/tasks", params=params)

    def get_task(self, task_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/tasks/{task_id}")
        return response if isinstance(response, dict) else {}

    def add_task(
        self,
        content: str,
        project_id: str | None = None,
        parent_id: str | None = None,
        due_date: str | None = None,
        due_datetime: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"content": content}
        if project_id:
            payload["project_id"] = project_id
        if parent_id:
            payload["parent_id"] = parent_id
        if due_datetime:
            payload["due_datetime"] = due_datetime
        elif due_date:
            payload["due_date"] = due_date
        if labels is not None:
            payload["labels"] = labels
        response = self._request("POST", "/tasks", payload=payload)
        return response if isinstance(response, dict) else {}

    def close_task(self, task_id: str) -> None:
        self._request("POST", f"/tasks/{task_id}/close")

    def reopen_task(self, task_id: str) -> None:
        self._request("POST", f"/tasks/{task_id}/reopen")

    def delete_task(self, task_id: str) -> None:
        self._request("DELETE", f"/tasks/{task_id}")

    def update_task(
        self,
        task_id: str,
        content: str | None = None,
        labels: list[str] | None = None,
        due_date: str | None = None,
        due_datetime: str | None = None,
        clear_due: bool = False,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        if labels is not None:
            payload["labels"] = labels
        if clear_due:
            payload["due_string"] = "no date"
        elif due_datetime:
            payload["due_datetime"] = due_datetime
        elif due_date:
            payload["due_date"] = due_date
        response = self._request("POST", f"/tasks/{task_id}", payload=payload)
        return response if isinstance(response, dict) else response

    def get_subtasks(self, parent_task: dict[str, Any]) -> list[dict[str, Any]]:
        parent_id = get_task_id(parent_task)
        if not parent_id:
            return []
        return self._paginate("/tasks", params={"parent_id": parent_id})

    def get_completed_tasks(
        self,
        project_id: str | None = None,
        parent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "limit": limit,
            "annotate_items": True,
        }
        if project_id:
            payload["project_id"] = project_id
        response = self._request(
            "POST",
            "/completed/get_all",
            payload=payload,
            base_url=SYNC_API_BASE,
        )
        items = response.get("items") if isinstance(response, dict) else []
        if not isinstance(items, list):
            return []
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_completed_item(item)
            if parent_id and get_task_parent_id(normalized) != str(parent_id):
                continue
            results.append(normalized)
        return results

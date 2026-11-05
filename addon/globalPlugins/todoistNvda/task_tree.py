"""Native task hierarchy; wx/MSAA owns arrow navigation, levels and states."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

import wx

from .todoist_api import get_task_id, get_task_parent_id


def descendant_tasks(tasks: list[dict[str, Any]], parent_id: str) -> list[dict[str, Any]]:
    """Select the complete loaded subtree, retaining the API's sibling order."""
    children = defaultdict(list)
    for task in tasks:
        children[get_task_parent_id(task)].append(get_task_id(task))
    descendants = set()
    pending = list(children[parent_id])
    while pending:
        task_id = pending.pop()
        if task_id == parent_id or task_id in descendants:
            continue
        descendants.add(task_id)
        pending.extend(children[task_id])
    return [task for task in tasks if get_task_id(task) in descendants]


class TaskTree(wx.TreeCtrl):
    def __init__(self, parent):
        super().__init__(
            parent,
            style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_HIDE_ROOT | wx.TR_SINGLE,
        )
        self._items = {}
        self._expanded_ids = set()

    def current_task(self) -> dict[str, Any] | None:
        item = self.GetSelection()
        if not item or not item.IsOk():
            return None
        return self.GetItemData(item)

    def _selection_path(self) -> list[str]:
        path = []
        item = self.GetSelection()
        while item and item.IsOk():
            task = self.GetItemData(item)
            if not task:
                break
            path.append(get_task_id(task))
            item = self.GetItemParent(item)
        return path

    def render(self, tasks: list[dict[str, Any]], summary: Callable[[dict[str, Any]], str]):
        selection_path = self._selection_path()
        # Remember hidden branches across search/filter changes, but respect native collapse.
        self._expanded_ids.difference_update(self._items)
        self._expanded_ids.update(
            task_id for task_id, item in self._items.items() if self.IsExpanded(item)
        )
        children = defaultdict(list)
        for index, task in enumerate(tasks):
            children[get_task_parent_id(task)].append(index)
        task_ids = {get_task_id(task) for task in tasks}
        roots = [index for index, task in enumerate(tasks)
                 if not get_task_parent_id(task) or get_task_parent_id(task) not in task_ids
                 or get_task_parent_id(task) == get_task_id(task)]
        self.Freeze()
        try:
            self.DeleteAllItems()
            self._items = {}
            root = self.AddRoot('')
            visited = set()
            # The second pass roots malformed cycles rather than hiding tasks or recursing forever.
            for index in roots + list(range(len(tasks))):
                pending = [(index, root)]
                while pending:
                    current, parent = pending.pop()
                    if current in visited:
                        continue
                    visited.add(current)
                    task = tasks[current]
                    item = self.AppendItem(parent, summary(task), data=task)
                    task_id = get_task_id(task)
                    self._items[task_id] = item
                    if task_id:
                        pending.extend((child, item) for child in reversed(children[task_id]))
            for task_id, item in self._items.items():
                if task_id in self._expanded_ids:
                    self.Expand(item)
            selected_id = next((task_id for task_id in selection_path if task_id in self._items), None)
            if selected_id is None and selection_path and self._items:
                selected_id = next(iter(self._items))
            if selected_id is not None:
                item = self._items[selected_id]
                self.SelectItem(item)
                self.EnsureVisible(item)
        finally:
            self.Thaw()

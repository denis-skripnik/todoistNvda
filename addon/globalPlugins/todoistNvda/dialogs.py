from __future__ import annotations

import api
import threading
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any, Callable

import addonHandler
import ui
import wx

from .todoist_api import (
    TodoistClient,
    TodoistError,
    get_due,
    get_due_date_value,
    get_task_content,
    get_task_id,
    get_task_labels,
    get_task_parent_id,
    get_task_project_id,
    parse_due_datetime,
)


addonHandler.initTranslation()


MONTH_CHOICES = [
    (1, _("January")),
    (2, _("February")),
    (3, _("March")),
    (4, _("April")),
    (5, _("May")),
    (6, _("June")),
    (7, _("July")),
    (8, _("August")),
    (9, _("September")),
    (10, _("October")),
    (11, _("November")),
    (12, _("December")),
]


def _project_name(project: dict[str, Any]) -> str:
    return str(project.get("name") or "").strip()


def _label_name(label: dict[str, Any]) -> str:
    return str(label.get("name") or "").strip()


def _task_summary(task: dict[str, Any]) -> str:
    content = get_task_content(task) or _("Untitled task")
    due = get_due(task)
    due_label = ""
    due_dt = parse_due_datetime(task)
    if due_dt is not None:
        due_label = due_dt.astimezone().strftime("%d.%m %H:%M")
    elif due:
        due_label = str(due.get("date") or due.get("string") or "").strip()
    labels = get_task_labels(task)
    parts = [content]
    if due_label:
        parts.append(f"[{due_label}]")
    if labels:
        parts.append(" ".join(f"#{label}" for label in labels))
    completed_at = str(task.get("_completed_at") or "").strip()
    if completed_at:
        parts.append(f"({_('Completed')}: {completed_at})")
    return " ".join(part for part in parts if part)


def _call_in_thread(target: Callable[[], Any]) -> None:
    threading.Thread(target=target, daemon=True).start()


def _local_timezone():
    return datetime.now().astimezone().tzinfo


def task_is_due_today(task: dict[str, Any], today: date | None = None) -> bool:
    today = today or datetime.now().astimezone().date()
    due_datetime = parse_due_datetime(task)
    if due_datetime is not None:
        return due_datetime.astimezone().date() == today
    due_date = get_due_date_value(task)
    if not due_date:
        return False
    if "T" in due_date:
        try:
            parsed = datetime.fromisoformat(due_date)
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_local_timezone())
        return parsed.astimezone().date() == today
    try:
        return date.fromisoformat(due_date) == today
    except ValueError:
        return False


def _extract_due_editor_state(task: dict[str, Any] | None) -> dict[str, Any]:
    now = datetime.now().astimezone()
    state = {
        "enabled": False,
        "has_time": False,
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
    }
    if task is None:
        return state
    due_datetime = parse_due_datetime(task)
    if due_datetime is not None:
        local_due = due_datetime.astimezone()
        state.update(
            enabled=True,
            has_time=True,
            year=local_due.year,
            month=local_due.month,
            day=local_due.day,
            hour=local_due.hour,
            minute=local_due.minute,
        )
        return state
    due = get_due(task)
    due_date = str(due.get("date") or "").strip()
    if not due_date:
        return state
    try:
        parsed = date.fromisoformat(due_date)
    except ValueError:
        return state
    state.update(
        enabled=True,
        has_time=False,
        year=parsed.year,
        month=parsed.month,
        day=parsed.day,
        hour=9,
        minute=0,
    )
    return state


def _focus_screen_point() -> wx.Point:
    try:
        focus = api.getFocusObject()
        location = getattr(focus, "location", None)
        if hasattr(location, "left"):
            left = int(location.left)
            top = int(location.top)
            height = int(getattr(location, "height", 0) or 0)
            return wx.Point(left, top + max(height, 0))
        if isinstance(location, (tuple, list)) and len(location) >= 4:
            left, top, _, height = location[:4]
            return wx.Point(int(left), int(top + max(height, 0)))
    except Exception:
        pass
    return wx.GetMousePosition()


def _move_window_near_focus(window: wx.TopLevelWindow) -> None:
    point = _focus_screen_point()
    geometry = None
    for index in range(wx.Display.GetCount()):
        rect = wx.Display(index).GetGeometry()
        if rect.Contains(point):
            geometry = rect
            break
    if geometry is None:
        geometry = wx.GetClientDisplayRect()

    width, height = window.GetSize()
    x = min(max(point.x, geometry.GetLeft()), geometry.GetRight() - width)
    y = min(max(point.y, geometry.GetTop()), geometry.GetBottom() - height)
    window.SetPosition((max(x, geometry.GetLeft()), max(y, geometry.GetTop())))


class ProjectNameDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Добавить проект"), style=wx.DEFAULT_DIALOG_STYLE)
        panel = wx.Panel(self)
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        panelSizer = wx.BoxSizer(wx.VERTICAL)

        panelSizer.Add(
            wx.StaticText(panel, label=_("Название проекта:")),
            flag=wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )
        self.nameEdit = wx.TextCtrl(panel)
        self.nameEdit.SetMaxLength(60)
        panelSizer.Add(
            self.nameEdit,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
            border=12,
        )

        panel.SetSizer(panelSizer)
        mainSizer.Add(panel, proportion=1, flag=wx.EXPAND)
        mainSizer.Add(
            self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL),
            flag=wx.EXPAND | wx.ALL,
            border=12,
        )
        self.SetSizerAndFit(mainSizer)
        self.nameEdit.SetFocus()

    def get_name(self) -> str:
        return self.nameEdit.GetValue().strip()


class LabelFilterDialog(wx.Dialog):
    def __init__(self, parent, labels: list[str], selected_labels: set[str] | None = None):
        super().__init__(parent, title=_("Фильтр по тегам"), style=wx.DEFAULT_DIALOG_STYLE)
        self._labels = labels
        self._selected_labels = set(selected_labels) if selected_labels else set()
        self._checkboxes: list[tuple[str, wx.CheckBox]] = []

        panel = wx.Panel(self)
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        panelSizer = wx.BoxSizer(wx.VERTICAL)

        if labels:
            panelSizer.Add(
                wx.StaticText(panel, label=_("Выберите теги для фильтра:")),
                flag=wx.LEFT | wx.RIGHT | wx.TOP,
                border=12,
            )
            labelsWindow = wx.ScrolledWindow(panel, style=wx.VSCROLL | wx.BORDER_THEME)
            labelsWindow.SetScrollRate(0, 10)
            labelsWindow.SetMinSize((-1, 200))
            labelsSizer = wx.BoxSizer(wx.VERTICAL)
            for labelName in labels:
                checkbox = wx.CheckBox(labelsWindow, label=labelName)
                checkbox.SetValue(labelName in self._selected_labels)
                self._checkboxes.append((labelName, checkbox))
                labelsSizer.Add(checkbox, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=8)
            labelsSizer.AddSpacer(8)
            labelsWindow.SetSizer(labelsSizer)
            panelSizer.Add(labelsWindow, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=12)
        else:
            panelSizer.Add(
                wx.StaticText(panel, label=_("Нет доступных тегов.")),
                flag=wx.LEFT | wx.RIGHT | wx.TOP,
                border=12,
            )

        panel.SetSizer(panelSizer)
        mainSizer.Add(panel, proportion=1, flag=wx.EXPAND)
        mainSizer.Add(
            self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL),
            flag=wx.EXPAND | wx.ALL,
            border=12,
        )
        self.SetSizerAndFit(mainSizer)

    def get_selected_labels(self) -> set[str]:
        return {label for label, checkbox in self._checkboxes if checkbox.GetValue()}


class LabelNameDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Новый тег"), style=wx.DEFAULT_DIALOG_STYLE)
        panel = wx.Panel(self)
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        panelSizer = wx.BoxSizer(wx.VERTICAL)

        panelSizer.Add(
            wx.StaticText(panel, label=_("Название тега:")),
            flag=wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )
        self.nameEdit = wx.TextCtrl(panel)
        self.nameEdit.SetMaxLength(40)
        panelSizer.Add(
            self.nameEdit,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
            border=12,
        )

        panel.SetSizer(panelSizer)
        mainSizer.Add(panel, proportion=1, flag=wx.EXPAND)
        mainSizer.Add(
            self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL),
            flag=wx.EXPAND | wx.ALL,
            border=12,
        )
        self.SetSizerAndFit(mainSizer)
        self.nameEdit.SetFocus()

    def get_name(self) -> str:
        return self.nameEdit.GetValue().strip()


class TaskEditorDialog(wx.Dialog):
    def __init__(
        self,
        parent,
        title: str,
        client_factory: Callable[[], TodoistClient],
        labels: list[str],
        task: dict[str, Any] | None = None,
        focus_target: str = "content",
    ):
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((620, 560))
        self._client_factory = client_factory
        self._focus_target = focus_target
        self._labelNames = labels
        self._labelCheckboxes: list[tuple[str, wx.CheckBox]] = []

        panel = wx.Panel(self)
        self._panel = panel
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        panelSizer = wx.BoxSizer(wx.VERTICAL)

        panelSizer.Add(
            wx.StaticText(panel, label=_("Текст задачи:")),
            flag=wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )
        self.contentEdit = wx.TextCtrl(
            panel,
            value=get_task_content(task) if task is not None else "",
            style=wx.TE_MULTILINE,
            size=(-1, 100),
        )
        panelSizer.Add(
            self.contentEdit,
            proportion=1,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )

        dueState = _extract_due_editor_state(task)
        self.dueCheckbox = wx.CheckBox(panel, label=_("Задать срок"))
        self.dueCheckbox.SetValue(dueState["enabled"])
        panelSizer.Add(self.dueCheckbox, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=12)

        dateSizer = wx.BoxSizer(wx.HORIZONTAL)
        self._dayValues = [str(index) for index in range(1, 32)]
        self.dayChoice = wx.Choice(panel, choices=self._dayValues)
        self.monthChoice = wx.Choice(panel, choices=[label for _, label in MONTH_CHOICES])
        self.yearSpin = wx.SpinCtrl(panel, min=2000, max=2100, initial=dueState["year"])
        dateSizer.Add(wx.StaticText(panel, label=_("День:")), flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4)
        dateSizer.Add(self.dayChoice, flag=wx.RIGHT, border=12)
        dateSizer.Add(wx.StaticText(panel, label=_("Месяц:")), flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4)
        dateSizer.Add(self.monthChoice, flag=wx.RIGHT, border=12)
        dateSizer.Add(wx.StaticText(panel, label=_("Год:")), flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4)
        dateSizer.Add(self.yearSpin)
        panelSizer.Add(dateSizer, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=12)

        self.timeCheckbox = wx.CheckBox(panel, label=_("Указать время"))
        self.timeCheckbox.SetValue(dueState["has_time"])
        panelSizer.Add(self.timeCheckbox, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=12)

        timeSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.hourSpin = wx.SpinCtrl(panel, min=0, max=23, initial=dueState["hour"])
        self.minuteSpin = wx.SpinCtrl(panel, min=0, max=59, initial=dueState["minute"])
        timeSizer.Add(wx.StaticText(panel, label=_("Часы:")), flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4)
        timeSizer.Add(self.hourSpin, flag=wx.RIGHT, border=12)
        timeSizer.Add(wx.StaticText(panel, label=_("Минуты:")), flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4)
        timeSizer.Add(self.minuteSpin)
        panelSizer.Add(timeSizer, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=12)

        panelSizer.Add(
            wx.StaticText(panel, label=_("Теги:")),
            flag=wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )
        self.labelsAreaSizer = wx.BoxSizer(wx.VERTICAL)
        panelSizer.Add(
            self.labelsAreaSizer,
            proportion=1,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )
        self.newLabelButton = wx.Button(panel, label=_("Новый тег"))
        panelSizer.Add(
            self.newLabelButton,
            flag=wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )
        self.labelsList = None
        self.labelsWindow = None
        self._rebuild_label_controls(preselected_labels=set(get_task_labels(task or {})))

        panel.SetSizer(panelSizer)
        mainSizer.Add(panel, proportion=1, flag=wx.EXPAND)
        mainSizer.Add(
            self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL),
            flag=wx.EXPAND | wx.ALL,
            border=12,
        )
        self.SetSizerAndFit(mainSizer)

        self.monthChoice.SetSelection(max(0, dueState["month"] - 1))
        self.yearSpin.SetValue(dueState["year"])
        self._refresh_day_choices(preferred_day=dueState["day"])

        self.dueCheckbox.Bind(wx.EVT_CHECKBOX, self._onDueToggle)
        self.timeCheckbox.Bind(wx.EVT_CHECKBOX, self._onTimeToggle)
        self.monthChoice.Bind(wx.EVT_CHOICE, self._onDatePartChanged)
        self.yearSpin.Bind(wx.EVT_SPINCTRL, self._onDatePartChanged)
        self.newLabelButton.Bind(wx.EVT_BUTTON, self._onNewLabel)
        self._update_due_controls()

    def postInit(self):
        if self._focus_target == "due":
            self.dueCheckbox.SetFocus()
            return
        if self._focus_target == "labels" and self._labelCheckboxes:
            self._labelCheckboxes[0][1].SetFocus()
            return
        self.contentEdit.SetFocus()

    def _selected_month(self) -> int:
        selection = self.monthChoice.GetSelection()
        if selection == wx.NOT_FOUND:
            return 1
        return MONTH_CHOICES[selection][0]

    def _selected_day(self) -> int:
        selection = self.dayChoice.GetSelection()
        if selection == wx.NOT_FOUND:
            return 1
        return int(self._dayValues[selection])

    def _refresh_day_choices(self, preferred_day: int | None = None):
        max_day = monthrange(self.yearSpin.GetValue(), self._selected_month())[1]
        current_day = preferred_day or self._selected_day()
        self._dayValues = [str(index) for index in range(1, max_day + 1)]
        self.dayChoice.Clear()
        for value in self._dayValues:
            self.dayChoice.Append(value)
        self.dayChoice.SetSelection(min(max(current_day, 1), max_day) - 1)

    def _onDueToggle(self, evt):
        self._update_due_controls()

    def _onTimeToggle(self, evt):
        self._update_due_controls()

    def _onDatePartChanged(self, evt):
        self._refresh_day_choices()

    def _update_due_controls(self):
        dueEnabled = self.dueCheckbox.GetValue()
        for control in (self.dayChoice, self.monthChoice, self.yearSpin, self.timeCheckbox):
            control.Enable(dueEnabled)
        timeEnabled = dueEnabled and self.timeCheckbox.GetValue()
        self.hourSpin.Enable(timeEnabled)
        self.minuteSpin.Enable(timeEnabled)

    def _get_labels(self) -> list[str]:
        return [label for label, checkbox in self._labelCheckboxes if checkbox.GetValue()]

    def _rebuild_label_controls(self, preselected_labels: set[str] | None = None):
        selectedLabels = preselected_labels if preselected_labels is not None else set(self._get_labels())
        self._labelCheckboxes = []
        self.labelsAreaSizer.Clear(delete_windows=True)
        self.labelsWindow = None

        if self._labelNames:
            labelsWindow = wx.ScrolledWindow(self._panel, style=wx.VSCROLL | wx.BORDER_THEME)
            labelsWindow.SetScrollRate(0, 10)
            labelsWindow.SetMinSize((-1, 160))
            labelsSizer = wx.BoxSizer(wx.VERTICAL)
            for labelName in self._labelNames:
                checkbox = wx.CheckBox(labelsWindow, label=labelName)
                checkbox.SetValue(labelName in selectedLabels)
                self._labelCheckboxes.append((labelName, checkbox))
                labelsSizer.Add(checkbox, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=8)
            labelsSizer.AddSpacer(8)
            labelsWindow.SetSizer(labelsSizer)
            self.labelsAreaSizer.Add(labelsWindow, proportion=1, flag=wx.EXPAND)
            self.labelsWindow = labelsWindow
        else:
            self.labelsAreaSizer.Add(
                wx.StaticText(self._panel, label=_("Нет доступных тегов Todoist.")),
                flag=wx.EXPAND,
            )

        self.Layout()

    def _onNewLabel(self, evt):
        dialog = LabelNameDialog(self)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.get_name()
        finally:
            dialog.Destroy()

        if not name:
            ui.message(_("Label name cannot be empty."))
            return
        if len(name) > 40:
            ui.message(_("Label name must be 40 characters or fewer."))
            return
        if any(character.isspace() for character in name):
            ui.message(_("Label name must not contain spaces."))
            return

        existing = {label.lower(): label for label in self._labelNames}
        if name.lower() in existing:
            self._rebuild_label_controls(preselected_labels=set(self._get_labels()) | {existing[name.lower()]})
            ui.message(_("Label already exists and was selected."))
            return

        try:
            created = self._client_factory().create_label(name)
        except Exception as error:
            ui.message(str(error))
            return

        createdName = _label_name(created) or name
        self._labelNames.append(createdName)
        self._labelNames.sort(key=str.lower)
        self._rebuild_label_controls(preselected_labels=set(self._get_labels()) | {createdName})
        ui.message(_("Label added"))

    def get_payload(self) -> dict[str, Any]:
        content = self.contentEdit.GetValue().strip()
        if not content:
            raise TodoistError(_("Task text cannot be empty."))

        payload = {
            "content": content,
            "labels": self._get_labels(),
            "due_date": None,
            "due_datetime": None,
            "clear_due": False,
        }
        if not self.dueCheckbox.GetValue():
            payload["clear_due"] = True
            return payload

        year = self.yearSpin.GetValue()
        month = self._selected_month()
        day = self._selected_day()
        try:
            selectedDate = date(year, month, day)
        except ValueError:
            raise TodoistError(_("Invalid date."))

        if not self.timeCheckbox.GetValue():
            payload["due_date"] = selectedDate.isoformat()
            return payload

        hour = self.hourSpin.GetValue()
        minute = self.minuteSpin.GetValue()
        localDateTime = datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=_local_timezone(),
        )
        payload["due_datetime"] = (
            localDateTime.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        return payload


class ReminderDialog(wx.Dialog):
    def __init__(self, parent, task: dict[str, Any], on_complete: Callable[[dict[str, Any]], None]):
        super().__init__(
            parent,
            title=_("Todoist reminder"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )
        self._task = task
        self._on_complete = on_complete
        panel = wx.Panel(self)
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        panelSizer = wx.BoxSizer(wx.VERTICAL)

        panelSizer.Add(
            wx.StaticText(panel, label=_("Task is due now:")),
            flag=wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )
        self.taskText = wx.TextCtrl(
            panel,
            value=get_task_content(task),
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(420, 100),
        )
        panelSizer.Add(
            self.taskText,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )
        panel.SetSizer(panelSizer)

        self.completeButton = wx.Button(self, label=_("Выполнил"))
        okButton = wx.Button(self, wx.ID_OK, _("OK"))
        buttonsSizer = wx.StdDialogButtonSizer()
        buttonsSizer.AddButton(self.completeButton)
        buttonsSizer.AddButton(okButton)
        buttonsSizer.Realize()

        mainSizer.Add(panel, proportion=1, flag=wx.EXPAND)
        mainSizer.Add(buttonsSizer, flag=wx.ALIGN_RIGHT | wx.ALL, border=12)
        self.SetSizerAndFit(mainSizer)
        self.completeButton.Bind(wx.EVT_BUTTON, self._onComplete)

    def show_modal_near_focus(self):
        _move_window_near_focus(self)
        self.ShowModal()

    def _onComplete(self, evt):
        self.completeButton.Disable()
        self._on_complete(self._task)
        self.EndModal(wx.ID_OK)


class DailySummaryDialog(wx.Dialog):
    def __init__(
        self,
        parent,
        tasks: list[dict[str, Any]],
        client_factory: Callable[[], TodoistClient],
    ):
        super().__init__(
            parent,
            title=_("Today's incomplete tasks"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP,
        )
        self.SetMinSize((720, 420))
        self._client_factory = client_factory
        self._tasks = list(tasks)

        panel = wx.Panel(self)
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        panelSizer = wx.BoxSizer(wx.VERTICAL)

        panelSizer.Add(
            wx.StaticText(panel, label=_("Today's incomplete tasks:")),
            flag=wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )
        self.tasksList = wx.ListBox(panel, style=wx.LB_SINGLE)
        panelSizer.Add(
            self.tasksList,
            proportion=1,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            border=12,
        )

        buttonsSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.completeButton = wx.Button(panel, label=_("Выполнил"))
        self.editDueButton = wx.Button(panel, label=_("Изменить срок"))
        self.okButton = wx.Button(panel, wx.ID_OK, _("OK"))
        buttonsSizer.Add(self.completeButton, flag=wx.RIGHT, border=8)
        buttonsSizer.Add(self.editDueButton, flag=wx.RIGHT, border=8)
        buttonsSizer.Add(self.okButton)
        panelSizer.Add(buttonsSizer, flag=wx.ALIGN_RIGHT | wx.ALL, border=12)

        self.statusLabel = wx.StaticText(panel, label="")
        panelSizer.Add(self.statusLabel, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=12)

        panel.SetSizer(panelSizer)
        mainSizer.Add(panel, proportion=1, flag=wx.EXPAND)
        self.SetSizerAndFit(mainSizer)

        self.tasksList.Bind(wx.EVT_LISTBOX, self._onSelectionChanged)
        self.completeButton.Bind(wx.EVT_BUTTON, self._onComplete)
        self.editDueButton.Bind(wx.EVT_BUTTON, self._onEditDue)
        self._refresh_list()
        self.tasksList.SetFocus()

    def _current_task(self) -> dict[str, Any] | None:
        index = self.tasksList.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._tasks):
            return None
        return self._tasks[index]

    def _set_status(self, text: str):
        self.statusLabel.SetLabel(text)

    def _refresh_list(self):
        self.tasksList.Clear()
        for task in self._tasks:
            self.tasksList.Append(_task_summary(task))
        self.completeButton.Enable(False)
        self.editDueButton.Enable(False)

    def _onSelectionChanged(self, evt):
        has_task = self._current_task() is not None
        self.completeButton.Enable(has_task)
        self.editDueButton.Enable(has_task)

    def _run_action(
        self,
        success_message: str,
        action: Callable[[TodoistClient], Any],
        after_success: Callable[[Any], None] | None = None,
    ):
        self._set_status(_("Working"))

        def worker():
            try:
                result = action(self._client_factory())
            except Exception as error:
                wx.CallAfter(self._handle_error, error)
                return
            wx.CallAfter(self._handle_success, success_message, result, after_success)

        _call_in_thread(worker)

    def _handle_error(self, error: Exception):
        message = str(error)
        self._set_status(message)
        ui.message(message)

    def _handle_success(
        self,
        success_message: str,
        result: Any,
        after_success: Callable[[Any], None] | None,
    ):
        self._set_status(success_message)
        ui.message(success_message)
        if after_success is not None:
            after_success(result)

    def _remove_current_task(self):
        index = self.tasksList.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._tasks):
            return
        self._tasks.pop(index)
        self._refresh_list()

    def _replace_current_task_due(self, task: dict[str, Any], payload: dict[str, Any]):
        task_id = get_task_id(task)
        self._run_action(
            _("Task updated"),
            lambda client: client.update_task(
                task_id,
                content=payload["content"],
                labels=payload["labels"],
                due_date=payload["due_date"],
                due_datetime=payload["due_datetime"],
                clear_due=payload["clear_due"],
            ),
            after_success=lambda result: self._remove_current_task(),
        )

    def _onComplete(self, evt):
        task = self._current_task()
        if task is None:
            return
        self._run_action(
            _("Task completed"),
            lambda client: client.close_task(get_task_id(task)),
            after_success=lambda result: self._remove_current_task(),
        )

    def _onEditDue(self, evt):
        task = self._current_task()
        if task is None:
            return
        dialog = TaskEditorDialog(
            self,
            title=_("Изменить срок"),
            client_factory=self._client_factory,
            labels=get_task_labels(task),
            task=task,
            focus_target="due",
        )
        try:
            dialog.postInit()
            if dialog.ShowModal() != wx.ID_OK:
                return
            payload = dialog.get_payload()
        except Exception as error:
            self._handle_error(error)
            return
        finally:
            dialog.Destroy()
        self._replace_current_task_due(task, payload)


class TaskBrowserDialog(wx.Dialog):
    def __init__(
        self,
        parent,
        client_factory: Callable[[], TodoistClient],
        parent_task: dict[str, Any] | None = None,
        on_task_changed: Callable[[], None] | None = None,
        completed_mode: bool = False,
    ):
        title = _("Completed tasks") if completed_mode else _("Todoist")
        if parent_task is not None:
            title = _("Completed subtasks") if completed_mode else _("Подзадачи")
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((860, 620))
        self._client_factory = client_factory
        self._parent_task = parent_task
        self._on_task_changed = on_task_changed
        self._completed_mode = completed_mode
        self._projects: list[dict[str, Any]] = []
        self._labels: list[str] = []
        self._tasks: list[dict[str, Any]] = []
        self._visibleTasks: list[dict[str, Any]] = []
        self._closed = False
        self._pendingProjectId: str | None = None
        self._labelFilter: set[str] = set()

        self._build_ui()
        self._setup_accelerators()
        self.Bind(wx.EVT_CLOSE, self._onClose)

        if self._parent_task is None:
            self._load_projects()
        else:
            self._load_tasks()

    def _build_ui(self):
        panel = wx.Panel(self)
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        panelSizer = wx.BoxSizer(wx.VERTICAL)

        if self._parent_task is None:
            projectSizer = wx.BoxSizer(wx.HORIZONTAL)
            projectSizer.Add(
                wx.StaticText(panel, label=_("Проект:")),
                flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                border=8,
            )
            self.projectCombo = wx.ComboBox(panel, style=wx.CB_READONLY, choices=[])
            projectSizer.Add(self.projectCombo, proportion=1, flag=wx.RIGHT, border=8)
            if not self._completed_mode:
                self.addProjectButton = wx.Button(panel, label=_("Добавить проект"))
                projectSizer.Add(self.addProjectButton)
            else:
                self.addProjectButton = None
            panelSizer.Add(projectSizer, flag=wx.EXPAND | wx.ALL, border=12)

            searchSizer = wx.BoxSizer(wx.HORIZONTAL)
            self.searchEdit = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
            self.searchButton = wx.Button(panel, label=_("Найти"))
            self.filterButton = wx.Button(panel, label=_("Фильтр"))
            searchSizer.Add(self.searchEdit, proportion=1, flag=wx.RIGHT, border=8)
            searchSizer.Add(self.searchButton, flag=wx.RIGHT, border=8)
            searchSizer.Add(self.filterButton)
            panelSizer.Add(
                searchSizer,
                flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                border=12,
            )

            self.projectCombo.Bind(wx.EVT_COMBOBOX, self._onProjectChanged)
            self.searchButton.Bind(wx.EVT_BUTTON, self._onSearch)
            self.searchEdit.Bind(wx.EVT_TEXT_ENTER, self._onSearch)
            self.filterButton.Bind(wx.EVT_BUTTON, self._onFilter)
            if self.addProjectButton is not None:
                self.addProjectButton.Bind(wx.EVT_BUTTON, self._onAddProject)
        else:
            self.addProjectButton = None
            panelSizer.Add(
                wx.StaticText(panel, label=_("Родительская задача:")),
                flag=wx.LEFT | wx.RIGHT | wx.TOP,
                border=12,
            )
            panelSizer.Add(
                wx.TextCtrl(
                    panel,
                    value=_task_summary(self._parent_task),
                    style=wx.TE_MULTILINE | wx.TE_READONLY,
                    size=(-1, 70),
                ),
                flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                border=12,
            )

        self.tasksList = wx.ListBox(panel, style=wx.LB_SINGLE)
        panelSizer.Add(
            self.tasksList,
            proportion=1,
            flag=wx.EXPAND | wx.LEFT | wx.RIGHT,
            border=12,
        )

        buttonsSizer = wx.WrapSizer(wx.HORIZONTAL, 8)
        if not self._completed_mode:
            self.addButton = wx.Button(panel, label=_("Добавить"))
            buttonsSizer.Add(self.addButton, flag=wx.RIGHT | wx.BOTTOM, border=8)
        else:
            self.addButton = None

        self.completeButton = wx.Button(
            panel,
            label=_("Вернуть") if self._completed_mode else _("Выполнил"),
        )
        buttonsSizer.Add(self.completeButton, flag=wx.RIGHT | wx.BOTTOM, border=8)

        if not self._completed_mode:
            self.editTextButton = wx.Button(panel, label=_("Изменить текст"))
            self.editDueButton = wx.Button(panel, label=_("Изменить срок"))
            self.labelsButton = wx.Button(panel, label=_("Тег"))
            self.deleteButton = wx.Button(panel, label=_("Удалить"))
            for button in (
                self.editTextButton,
                self.editDueButton,
                self.labelsButton,
                self.deleteButton,
            ):
                buttonsSizer.Add(button, flag=wx.RIGHT | wx.BOTTOM, border=8)
        else:
            self.editTextButton = None
            self.editDueButton = None
            self.labelsButton = None
            self.deleteButton = None

        self.subtasksButton = wx.Button(panel, label=_("Подзадачи"))
        buttonsSizer.Add(self.subtasksButton, flag=wx.RIGHT | wx.BOTTOM, border=8)

        if not self._completed_mode and self._parent_task is None:
            self.completedTasksButton = wx.Button(panel, label=_("Выполненные задачи"))
            buttonsSizer.Add(self.completedTasksButton, flag=wx.RIGHT | wx.BOTTOM, border=8)
        else:
            self.completedTasksButton = None

        self.closeButton = wx.Button(panel, label=_("Закрыть"))
        buttonsSizer.Add(self.closeButton, flag=wx.RIGHT | wx.BOTTOM, border=8)
        panelSizer.Add(buttonsSizer, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=12)

        self.statusLabel = wx.StaticText(panel, label="")
        panelSizer.Add(self.statusLabel, flag=wx.EXPAND | wx.ALL, border=12)

        panel.SetSizer(panelSizer)
        mainSizer.Add(panel, proportion=1, flag=wx.EXPAND)
        self.SetSizer(mainSizer)

        self.tasksList.Bind(wx.EVT_LISTBOX, self._onSelectionChanged)
        self.tasksList.Bind(wx.EVT_LISTBOX_DCLICK, self._onOpenSubtasks)
        self.tasksList.Bind(wx.EVT_KEY_DOWN, self._onTaskListKeyDown)
        if self.addButton is not None:
            self.addButton.Bind(wx.EVT_BUTTON, self._onAddTask)
        self.completeButton.Bind(wx.EVT_BUTTON, self._onComplete)
        self.subtasksButton.Bind(wx.EVT_BUTTON, self._onOpenSubtasks)
        self.closeButton.Bind(wx.EVT_BUTTON, self._onCloseButton)
        if self.editTextButton is not None:
            self.editTextButton.Bind(wx.EVT_BUTTON, self._onEditText)
            self.editDueButton.Bind(wx.EVT_BUTTON, self._onEditDue)
            self.labelsButton.Bind(wx.EVT_BUTTON, self._onEditLabels)
            self.deleteButton.Bind(wx.EVT_BUTTON, self._onDelete)
        if self.completedTasksButton is not None:
            self.completedTasksButton.Bind(wx.EVT_BUTTON, self._onCompletedTasks)
        self._update_action_state()

    def _onClose(self, evt):
        self._closed = True
        evt.Skip()

    def focus_initial_control(self):
        target = None
        if self._parent_task is None and hasattr(self, "projectCombo"):
            target = self.projectCombo
        elif hasattr(self, "tasksList"):
            target = self.tasksList
        if target is None:
            return
        try:
            target.SetFocus()
        except Exception:
            pass

    def _status(self, text: str):
        if not self._closed:
            self.statusLabel.SetLabel(text)

    def _safe_ui(self, callback: Callable[..., None], *args):
        if self._closed:
            return
        callback(*args)

    def _current_task(self) -> dict[str, Any] | None:
        index = self.tasksList.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._visibleTasks):
            return None
        return self._visibleTasks[index]

    def _setup_accelerators(self):
        # Set up keyboard handler for filter shortcut
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _on_char_hook(self, evt):
        # Check for Ctrl+F as filter shortcut
        if evt.GetKeyCode() == ord('F') and evt.ControlDown():
            self._onFilter(None)
            return
        evt.Skip()

    def request_refresh(self):
        if self._parent_task is None and not self._projects:
            self._load_projects()
            return
        self._load_tasks()

    def _selected_project_id(self) -> str | None:
        if self._parent_task is not None:
            return get_task_project_id(self._parent_task) or None
        selection = self.projectCombo.GetSelection()
        if selection == wx.NOT_FOUND or selection == 0:
            return None
        return str(self._projects[selection - 1].get("id") or "")

    def _select_project_by_id(self, project_id: str | None):
        if not project_id:
            self.projectCombo.SetSelection(0)
            return
        for index, project in enumerate(self._projects, start=1):
            if str(project.get("id") or "") == project_id:
                self.projectCombo.SetSelection(index)
                return
        self.projectCombo.SetSelection(0)

    def _load_projects(self):
        self._status(_("Loading projects"))

        def worker():
            try:
                client = self._client_factory()
                projects = client.get_projects()
                labels = self._labels
                if not self._completed_mode:
                    labels = [
                        _label_name(label)
                        for label in client.get_labels()
                        if _label_name(label)
                    ]
            except Exception as error:
                wx.CallAfter(self._safe_ui, self._show_error, error)
                return
            wx.CallAfter(self._safe_ui, self._finish_projects, projects, labels)

        _call_in_thread(worker)

    def _finish_projects(self, projects: list[dict[str, Any]], labels: list[str]):
        currentProjectId = self._pendingProjectId or self._selected_project_id()
        self._projects = projects
        self._labels = labels
        self.projectCombo.Clear()
        self.projectCombo.Append(_("Все проекты"))
        for project in self._projects:
            self.projectCombo.Append(_project_name(project))
        self._select_project_by_id(currentProjectId)
        self._pendingProjectId = None
        self._update_action_state()
        self._load_tasks()

    def _load_tasks(self):
        self._status(_("Loading tasks"))
        project_id = self._selected_project_id()
        parent_task = self._parent_task
        completed_mode = self._completed_mode

        def worker():
            try:
                client = self._client_factory()
                labels = self._labels
                if not completed_mode and not labels:
                    labels = [
                        _label_name(label)
                        for label in client.get_labels()
                        if _label_name(label)
                    ]
                if completed_mode:
                    tasks = client.get_completed_tasks(
                        project_id=project_id,
                        parent_id=get_task_id(parent_task) if parent_task else None,
                    )
                elif parent_task is None:
                    tasks = client.get_tasks(project_id)
                else:
                    tasks = client.get_subtasks(parent_task)
            except Exception as error:
                wx.CallAfter(self._safe_ui, self._show_error, error)
                return
            wx.CallAfter(self._safe_ui, self._finish_tasks, tasks, labels)

        _call_in_thread(worker)

    def _finish_tasks(self, tasks: list[dict[str, Any]], labels: list[str]):
        self._tasks = tasks
        self._labels = labels
        self._apply_filter()
        self._status(_("Tasks: {count}").format(count=len(self._visibleTasks)))

    def _apply_filter(self):
        query = ""
        if self._parent_task is None:
            query = self.searchEdit.GetValue().strip().lower()
        filtered_tasks = self._tasks

        # Apply text search filter
        if query:
            filtered_tasks = [
                task for task in filtered_tasks if query in get_task_content(task).lower()
            ]

        # Apply label filter
        if self._labelFilter:
            filtered_tasks = [
                task for task in filtered_tasks
                if set(get_task_labels(task)) & self._labelFilter
            ]

        self._visibleTasks = filtered_tasks

        self.tasksList.Clear()
        for task in self._visibleTasks:
            self.tasksList.Append(_task_summary(task))
        self._clear_selection()
        self._update_action_state()

    def _clear_selection(self):
        try:
            self.tasksList.SetSelection(wx.NOT_FOUND)
        except Exception:
            pass

    def _onProjectChanged(self, evt):
        self._update_action_state()
        self._load_tasks()

    def _onSearch(self, evt):
        self._apply_filter()
        self._status(_("Found tasks: {count}").format(count=len(self._visibleTasks)))

    def _onFilter(self, evt):
        if not self._labels:
            ui.message(_("No labels available. Load tasks first."))
            return
        dialog = LabelFilterDialog(self, self._labels, self._labelFilter)
        try:
            dialog.CentreOnParent()
            if dialog.ShowModal() != wx.ID_OK:
                return
            self._labelFilter = dialog.get_selected_labels()
        finally:
            dialog.Destroy()
        self._apply_filter()
        if self._labelFilter:
            self._status(_("Фильтр: {count} тегов").format(count=len(self._labelFilter)))
        else:
            self._status(_("Фильтр сброшен"))

    def _onSelectionChanged(self, evt):
        self._update_action_state()

    def _onTaskListKeyDown(self, evt):
        if evt.GetKeyCode() == wx.WXK_ESCAPE:
            self._clear_selection()
            self._update_action_state()
            return
        evt.Skip()

    def _update_action_state(self):
        has_task = self._current_task() is not None
        if self.addButton is not None:
            self.addButton.Enable(not has_task)
        self.completeButton.Enable(has_task)
        if self.editTextButton is not None:
            self.editTextButton.Enable(has_task)
            self.editDueButton.Enable(has_task)
            self.labelsButton.Enable(has_task)
            self.deleteButton.Enable(has_task)
        self.subtasksButton.Enable(has_task)
        if self.addProjectButton is not None:
            shouldShow = self.projectCombo.GetSelection() in (wx.NOT_FOUND, 0)
            self.addProjectButton.Show(shouldShow)
            self.Layout()

    def _run_action(
        self,
        success_message: str,
        action: Callable[[TodoistClient], Any],
        after_success: Callable[[Any], None] | None = None,
    ):
        self._status(_("Working"))

        def worker():
            try:
                client = self._client_factory()
                result = action(client)
            except Exception as error:
                wx.CallAfter(self._safe_ui, self._show_error, error)
                return
            wx.CallAfter(self._safe_ui, self._finish_action, success_message, result, after_success)

        _call_in_thread(worker)

    def _finish_action(
        self,
        success_message: str,
        result: Any,
        after_success: Callable[[Any], None] | None,
    ):
        self._status(success_message)
        ui.message(success_message)
        if after_success is not None:
            after_success(result)
        else:
            self._load_tasks()
        if self._on_task_changed is not None:
            self._on_task_changed()

    def _show_error(self, error: Exception):
        message = str(error)
        self._status(message)
        ui.message(message)

    def _open_editor(
        self,
        title: str,
        task: dict[str, Any] | None = None,
        focus_target: str = "content",
    ) -> dict[str, Any] | None:
        dialog = TaskEditorDialog(
            self,
            title=title,
            client_factory=self._client_factory,
            labels=self._labels,
            task=task,
            focus_target=focus_target,
        )
        try:
            dialog.postInit()
            if dialog.ShowModal() != wx.ID_OK:
                return None
            return dialog.get_payload()
        except Exception as error:
            self._show_error(error)
            return None
        finally:
            dialog.Destroy()

    def _show_modal_child(self, dialog: wx.Dialog):
        try:
            dialog.CentreOnParent()
            dialog.ShowModal()
        finally:
            dialog.Destroy()

    def _onAddProject(self, evt):
        dialog = ProjectNameDialog(self)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.get_name()
        finally:
            dialog.Destroy()
        if not name:
            ui.message(_("Project name cannot be empty."))
            return
        self._run_action(
            _("Project added"),
            lambda client: client.create_project(name),
            after_success=self._after_project_created,
        )

    def _after_project_created(self, project: Any):
        if isinstance(project, dict):
            self._pendingProjectId = str(project.get("id") or "") or None
        self._load_projects()

    def _apply_editor_update(self, task: dict[str, Any], payload: dict[str, Any], success_message: str):
        task_id = get_task_id(task)
        self._run_action(
            success_message,
            lambda client: client.update_task(
                task_id,
                content=payload["content"],
                labels=payload["labels"],
                due_date=payload["due_date"],
                due_datetime=payload["due_datetime"],
                clear_due=payload["clear_due"],
            ),
        )

    def _onAddTask(self, evt):
        payload = self._open_editor(_("Добавить задачу"))
        if payload is None:
            return
        parent_id = None
        project_id = self._selected_project_id()
        if self._parent_task is not None:
            parent_id = get_task_id(self._parent_task)
            project_id = get_task_project_id(self._parent_task) or project_id
        self._run_action(
            _("Task added"),
            lambda client: client.add_task(
                content=payload["content"],
                project_id=project_id,
                parent_id=parent_id,
                due_date=payload["due_date"],
                due_datetime=payload["due_datetime"],
                labels=payload["labels"],
            ),
        )

    def _onComplete(self, evt):
        task = self._current_task()
        if task is None:
            return
        task_id = get_task_id(task)
        if not task_id:
            self._show_error(TodoistError(_("Selected task has no id.")))
            return
        if self._completed_mode:
            self._run_action(_("Task reopened"), lambda client: client.reopen_task(task_id))
            return
        self._run_action(_("Task completed"), lambda client: client.close_task(task_id))

    def _onEditText(self, evt):
        task = self._current_task()
        if task is None:
            return
        payload = self._open_editor(_("Изменить задачу"), task=task, focus_target="content")
        if payload is None:
            return
        self._apply_editor_update(task, payload, _("Task updated"))

    def _onEditDue(self, evt):
        task = self._current_task()
        if task is None:
            return
        payload = self._open_editor(_("Изменить срок"), task=task, focus_target="due")
        if payload is None:
            return
        self._apply_editor_update(task, payload, _("Task updated"))

    def _onEditLabels(self, evt):
        task = self._current_task()
        if task is None:
            return
        payload = self._open_editor(_("Изменить теги"), task=task, focus_target="labels")
        if payload is None:
            return
        self._apply_editor_update(task, payload, _("Task updated"))

    def _onDelete(self, evt):
        task = self._current_task()
        if task is None:
            return
        confirm = wx.MessageDialog(
            self,
            _("Delete the selected task?"),
            _("Delete task"),
            style=wx.OK | wx.CANCEL | wx.ICON_WARNING,
        )
        try:
            if confirm.ShowModal() != wx.ID_OK:
                return
        finally:
            confirm.Destroy()
        self._run_action(
            _("Task deleted"),
            lambda client: client.delete_task(get_task_id(task)),
        )

    def _onOpenSubtasks(self, evt):
        task = self._current_task()
        if task is None:
            return
        dialog = TaskBrowserDialog(
            self,
            client_factory=self._client_factory,
            parent_task=task,
            on_task_changed=self._on_task_changed,
            completed_mode=self._completed_mode,
        )
        if self._completed_mode:
            self._show_modal_child(dialog)
        else:
            dialog.Show()

    def _onCompletedTasks(self, evt):
        dialog = TaskBrowserDialog(
            self,
            client_factory=self._client_factory,
            on_task_changed=self._on_task_changed,
            completed_mode=True,
        )
        self._show_modal_child(dialog)

    def _onCloseButton(self, evt):
        self.Close()

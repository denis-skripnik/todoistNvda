from __future__ import annotations

import threading
from datetime import datetime, timezone

import addonHandler
import globalPluginHandler
import gui
import scriptHandler
import ui
import wx
from gui.settingsDialogs import NVDASettingsDialog
from logHandler import log

from .configuration import get_settings
from .dialogs import DailySummaryDialog, ReminderDialog, TaskBrowserDialog, task_is_due_today
from .settings import TodoistSettingsPanel
from .todoist_api import TodoistClient, get_due_text, get_task_id, parse_due_datetime


addonHandler.initTranslation()


class ReminderService:
    def __init__(self, client_factory, on_due_task, poll_interval=30):
        self._client_factory = client_factory
        self._on_due_task = on_due_task
        self._poll_interval = poll_interval
        self._stopEvent = threading.Event()
        self._thread = None
        self._lastCheck = datetime.now(timezone.utc)
        self._seenTokens: set[str] = set()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopEvent.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stopEvent.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _loop(self):
        while not self._stopEvent.wait(self._poll_interval):
            try:
                self._poll_once()
            except Exception:
                log.exception("Todoist NVDA: reminder polling failed")

    def _poll_once(self):
        settings = get_settings()
        now = datetime.now(timezone.utc)
        previous = self._lastCheck
        self._lastCheck = now
        if not settings.api_key:
            return
        client = self._client_factory()
        tasks = client.get_tasks()
        active_tokens = set()
        for task in tasks:
            due_dt = parse_due_datetime(task)
            if due_dt is None:
                continue
            token = f"{get_task_id(task)}::{get_due_text(task)}"
            active_tokens.add(token)
            if token in self._seenTokens:
                continue
            if previous < due_dt <= now:
                self._seenTokens.add(token)
                wx.CallAfter(self._on_due_task, task)
        self._seenTokens.intersection_update(active_tokens)


class DailySummaryService:
    def __init__(self, client_factory, on_tasks_due, poll_interval=30):
        self._client_factory = client_factory
        self._on_tasks_due = on_tasks_due
        self._poll_interval = poll_interval
        self._stopEvent = threading.Event()
        self._thread = None
        self._lastShownDate = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopEvent.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stopEvent.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _loop(self):
        while not self._stopEvent.wait(self._poll_interval):
            try:
                self._poll_once()
            except Exception:
                log.exception("Todoist NVDA: daily summary polling failed")

    def _poll_once(self):
        settings = get_settings()
        if not settings.api_key:
            return
        now = datetime.now().astimezone()
        today = now.date()
        try:
            target_hour = int(settings.daily_summary_time[:2])
            target_minute = int(settings.daily_summary_time[3:])
        except Exception:
            target_hour = 19
            target_minute = 0
        if (now.hour, now.minute) < (target_hour, target_minute):
            return
        if self._lastShownDate == today:
            return
        tasks = [
            task for task in self._client_factory().get_tasks()
            if task_is_due_today(task, today=today)
        ]
        self._lastShownDate = today
        if tasks:
            wx.CallAfter(self._on_tasks_due, tasks)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("Todoist")

    def __init__(self):
        super().__init__()
        self._mainDialog = None
        self._menuItem = None
        self._register_settings_panel()
        self._create_menu_item()
        self._reminderService = ReminderService(self._create_client, self._show_reminder_popup)
        self._dailySummaryService = DailySummaryService(self._create_client, self._show_daily_summary_popup)
        self._reminderService.start()
        self._dailySummaryService.start()

    def terminate(self):
        try:
            self._reminderService.stop()
        except Exception:
            log.exception("Todoist NVDA: failed to stop reminder service")
        try:
            self._dailySummaryService.stop()
        except Exception:
            log.exception("Todoist NVDA: failed to stop daily summary service")
        self._destroy_main_dialog()
        self._destroy_menu_item()
        self._unregister_settings_panel()
        super().terminate()

    @scriptHandler.script(
        description=_("Open Todoist manager"),
        gesture="kb:nvda+windows+t",
        category=scriptCategory,
    )
    def script_openTodoistManager(self, gesture):
        self._open_main_window()

    def _register_settings_panel(self):
        for panelClass in list(NVDASettingsDialog.categoryClasses):
            if panelClass is TodoistSettingsPanel:
                continue
            if getattr(panelClass, "title", None) == TodoistSettingsPanel.title:
                NVDASettingsDialog.categoryClasses.remove(panelClass)
        if TodoistSettingsPanel not in NVDASettingsDialog.categoryClasses:
            NVDASettingsDialog.categoryClasses.append(TodoistSettingsPanel)

    def _unregister_settings_panel(self):
        if TodoistSettingsPanel in NVDASettingsDialog.categoryClasses:
            NVDASettingsDialog.categoryClasses.remove(TodoistSettingsPanel)

    def _create_menu_item(self):
        toolsMenu = gui.mainFrame.sysTrayIcon.toolsMenu
        self._menuItem = toolsMenu.Append(wx.ID_ANY, _("Todoist..."))
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self._onMenu, self._menuItem)

    def _destroy_menu_item(self):
        if self._menuItem is None:
            return
        try:
            gui.mainFrame.sysTrayIcon.Unbind(wx.EVT_MENU, handler=self._onMenu, source=self._menuItem)
        except Exception:
            pass
        try:
            gui.mainFrame.sysTrayIcon.toolsMenu.Remove(self._menuItem)
        except Exception:
            pass
        self._menuItem = None

    def _onMenu(self, evt):
        self._open_main_window()

    def _create_client(self):
        return TodoistClient(get_settings().api_key)

    def _open_main_window(self):
        settings = get_settings()
        if not settings.api_key:
            ui.message(_("Set the Todoist API key in NVDA settings first."))
            return
        if self._mainDialog is not None:
            try:
                if self._mainDialog.IsShown():
                    self._mainDialog.Raise()
                    self._mainDialog.SetFocus()
                    self._mainDialog.request_refresh()
                    return
            except Exception:
                self._mainDialog = None

        dialog = TaskBrowserDialog(
            gui.mainFrame,
            client_factory=self._create_client,
            on_task_changed=self._refresh_main_dialog,
        )
        dialog.Bind(wx.EVT_CLOSE, self._on_main_dialog_close)
        self._mainDialog = dialog
        dialog.Show()
        self._activate_main_dialog(dialog)

    def _activate_main_dialog(self, dialog):
        if dialog is None or dialog is not self._mainDialog:
            return
        try:
            dialog.Raise()
            dialog.RequestUserAttention()
            dialog.focus_initial_control()
        except Exception:
            return
        wx.CallAfter(self._activate_main_dialog_later, dialog)
        wx.CallLater(150, self._activate_main_dialog_later, dialog)

    def _activate_main_dialog_later(self, dialog):
        if dialog is None or dialog is not self._mainDialog:
            return
        try:
            dialog.Raise()
            dialog.focus_initial_control()
        except Exception:
            pass

    def _on_main_dialog_close(self, evt):
        self._mainDialog = None
        evt.Skip()

    def _refresh_main_dialog(self):
        if self._mainDialog is None:
            return
        try:
            self._mainDialog.request_refresh()
        except Exception:
            self._mainDialog = None

    def _destroy_main_dialog(self):
        if self._mainDialog is None:
            return
        try:
            self._mainDialog.Destroy()
        except Exception:
            pass
        self._mainDialog = None

    def _show_reminder_popup(self, task):
        task_id = get_task_id(task)
        if not task_id:
            return
        gui.mainFrame.prePopup()
        dialog = ReminderDialog(gui.mainFrame, task, self._complete_from_reminder)
        try:
            dialog.Raise()
            dialog.show_modal_near_focus()
        finally:
            try:
                dialog.Destroy()
            finally:
                gui.mainFrame.postPopup()
        ui.message(task.get("content") or _("Todoist reminder"))

    def _complete_from_reminder(self, task):
        task_id = get_task_id(task)
        if not task_id:
            return

        def worker():
            try:
                self._create_client().close_task(task_id)
            except Exception as error:
                wx.CallAfter(ui.message, str(error))
                return
            wx.CallAfter(ui.message, _("Task completed"))
            wx.CallAfter(self._refresh_main_dialog)

        threading.Thread(target=worker, daemon=True).start()

    def _show_daily_summary_popup(self, tasks):
        if not tasks:
            return
        gui.mainFrame.prePopup()
        dialog = DailySummaryDialog(
            gui.mainFrame,
            tasks=tasks,
            client_factory=self._create_client,
        )
        try:
            dialog.Raise()
            dialog.CentreOnScreen()
            dialog.ShowModal()
        finally:
            try:
                dialog.Destroy()
            finally:
                gui.mainFrame.postPopup()
        ui.message(_("Today's incomplete tasks"))

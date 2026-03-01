from __future__ import annotations

import addonHandler
import gui
import wx
from gui.settingsDialogs import SettingsPanel

from .configuration import get_settings, normalize_daily_summary_time, save_settings


addonHandler.initTranslation()


class TodoistSettingsPanel(SettingsPanel):
    title = _("Todoist")

    def makeSettings(self, settingsSizer):
        settings = get_settings()
        sHelper = gui.guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
        self.apiKeyEdit = sHelper.addLabeledControl(
            _("Todoist API key:"),
            wx.TextCtrl,
            value=settings.api_key,
            style=wx.TE_PASSWORD,
        )
        self.dailySummaryTimeEdit = sHelper.addLabeledControl(
            _("Daily incomplete tasks time:"),
            wx.TextCtrl,
            value=settings.daily_summary_time,
        )

    def postInit(self):
        self.apiKeyEdit.SetFocus()

    def onSave(self):
        normalizedTime = normalize_daily_summary_time(self.dailySummaryTimeEdit.GetValue())
        self.dailySummaryTimeEdit.SetValue(normalizedTime)
        save_settings(self.apiKeyEdit.GetValue(), normalizedTime)

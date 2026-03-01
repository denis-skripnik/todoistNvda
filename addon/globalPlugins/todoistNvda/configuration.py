from __future__ import annotations

from dataclasses import dataclass

import config


CONFIG_SECTION = "todoistNvda"

DEFAULTS = {
    "apiKey": "",
    "dailySummaryTime": "19:00",
}

CONFIG_SPEC = {
    "apiKey": "string(default='')",
    "dailySummaryTime": "string(default='19:00')",
}


@dataclass
class AddonSettings:
    api_key: str
    daily_summary_time: str


def normalize_daily_summary_time(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) != 5 or value[2] != ":":
        return DEFAULTS["dailySummaryTime"]
    hours = value[:2]
    minutes = value[3:]
    if not (hours.isdigit() and minutes.isdigit()):
        return DEFAULTS["dailySummaryTime"]
    hour = int(hours)
    minute = int(minutes)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return DEFAULTS["dailySummaryTime"]
    return f"{hour:02d}:{minute:02d}"


def _get_section():
    if CONFIG_SECTION not in config.conf.spec:
        config.conf.spec[CONFIG_SECTION] = dict(CONFIG_SPEC)
    section = config.conf[CONFIG_SECTION]
    for key, value in DEFAULTS.items():
        if key not in section:
            section[key] = value
    return section


def get_settings() -> AddonSettings:
    section = _get_section()
    return AddonSettings(
        api_key=str(section.get("apiKey", "")).strip(),
        daily_summary_time=normalize_daily_summary_time(
            str(section.get("dailySummaryTime", DEFAULTS["dailySummaryTime"]))
        ),
    )


def save_settings(api_key: str, daily_summary_time: str) -> None:
    section = _get_section()
    section["apiKey"] = api_key.strip()
    section["dailySummaryTime"] = normalize_daily_summary_time(daily_summary_time)
    config.conf.save()

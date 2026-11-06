# Todoist for NVDA

NVDA add-on for working with Todoist projects, tasks, subtasks, reminders, and
daily summaries directly from NVDA.

## Download

[Download latest version (v0.2.1)](https://github.com/denis-skripnik/todoistNvda/raw/main/dist/todoistNvda-0.2.1.nvda-addon)

## Features

- Open the main window from NVDA Tools or with `NVDA+Windows+T`
- Browse projects and active tasks
- Search tasks in the current project or across all projects
- Filter tasks by labels using the "Filter" button or `NVDA+Windows+F`
- Add, edit, complete, reopen, and delete tasks
- Work with subtasks
- Create projects from the main window
- Manage labels as checkboxes and create new labels from the task editor
- Receive a due-time reminder dialog with `Complete` and `OK`
- Receive a daily summary of today's incomplete tasks at a configured time

## Task tree navigation

Tasks and subtasks use a native tree with accessible levels and expanded/collapsed
states. Press Right Arrow to expand a task, Down Arrow to visit its children, and
Left Arrow to collapse it (or return to its parent). Tab reaches the existing
action buttons, which act on the selected task at any depth. Escape clears the
selection and enables Add; use the Subtasks button to open a branch and add a
subtask there. Refresh keeps surviving selections and expanded branches. Search
and label filters show matching tasks even when their parents do not match.

## Interface language

The interface follows the NVDA interface language, not the Windows language or
speech synthesizer voice. Russian (`ru`, including regional variants) uses the
Russian translation; English and other languages use English source messages.
After changing the NVDA language, restart NVDA. Menus, settings, dialogs, month
names, notifications and add-on validation messages are localized. User task,
project and label names, and raw messages returned by external services are kept
unchanged. Standard OK/Cancel buttons follow NVDA/wx localization.

## Settings

In NVDA Settings, the Todoist panel lets you configure:

- Todoist API key
- Daily incomplete-task summary time in `HH:MM` format, for example `19:00`

## Build

Run from this directory:

```bash
python3 build_addon.py
```

The resulting `.nvda-addon` file is written to `dist/`. The build compiles
`addon/locale/ru/LC_MESSAGES/nvda.po` into `nvda.mo` in the package using only
the Python standard library. The small compiler supports singular messages and
continuation lines; unsupported plural/context syntax and fuzzy entries fail
the build. Run `python3 -m unittest discover -s tests -v` to check translations
and existing task-tree behavior.

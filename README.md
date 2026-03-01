# Todoist for NVDA

NVDA add-on for working with Todoist projects, tasks, subtasks, reminders, and
daily summaries directly from NVDA.

## Features

- Open the main window from NVDA Tools or with `NVDA+Windows+T`
- Browse projects and active tasks
- Search tasks in the current project or across all projects
- Add, edit, complete, reopen, and delete tasks
- Work with subtasks
- Create projects from the main window
- Manage labels as checkboxes and create new labels from the task editor
- Receive a due-time reminder dialog with `Выполнил` and `OK`
- Receive a daily summary of today's incomplete tasks at a configured time

## Settings

In NVDA Settings, the Todoist panel lets you configure:

- Todoist API key
- Daily incomplete-task summary time in `HH:MM` format, for example `19:00`

## Build

Run from this directory:

```bash
python3 build_addon.py
```

The resulting `.nvda-addon` file is written to `dist/`.

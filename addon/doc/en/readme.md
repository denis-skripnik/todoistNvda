# Todoist for NVDA

Todoist for NVDA adds a global Todoist task manager to NVDA.

## Features

- Open the main window from NVDA Tools or with `NVDA+Windows+T`
- Browse Todoist projects and active tasks
- Search within the current task list
- Add, complete, reopen, edit, and delete tasks
- Create projects from the main window
- Open nested subtasks and add new subtasks
- Manage labels with checkboxes and create new labels from the task editor
- View completed tasks and reopen them
- Receive a due-time reminder dialog with `Выполнил` and `OK`
- Receive a daily summary of today's incomplete tasks at a configured time

## Settings

Open NVDA Settings and configure:

- Todoist API key
- Daily incomplete-task summary time in `HH:MM` format

## Notes

- Due-time reminders are shown for tasks that have a specific time today.
- Daily summaries include active tasks whose due date is today.
- New labels are created without spaces and with a maximum length of 40 characters.

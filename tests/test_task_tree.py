"""Behavior tests with a wx contract double; no Windows/NVDA runtime is simulated."""
import builtins
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Item:
    def __init__(self, text='', parent=None, data=None):
        self.text, self.parent, self.data = text, parent, data
        self.children = []
        self.expanded = False

    def IsOk(self):
        return True


class Window:
    def __init__(self, *args, **kwargs):
        self.bindings = {}
        self.enabled = True
        self.value = kwargs.get('value', '')
        self.selection = -1

    def Bind(self, event, handler):
        self.bindings[event] = handler

    def Enable(self, value):
        self.enabled = value

    def GetValue(self):
        return self.value

    def GetSelection(self):
        return self.selection

    def SetSelection(self, value):
        self.selection = value

    def __getattr__(self, name):
        if name in {'Add', 'SetMinSize', 'SetSizer', 'Layout', 'SetFocus', 'SetLabel',
                    'Show', 'Freeze', 'Thaw'}:
            return lambda *args, **kwargs: None
        raise AttributeError(name)


class TreeCtrl(Window):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style = kwargs.get('style', 0)
        self.selected = None

    def AddRoot(self, text):
        self.root = Item(text)
        return self.root

    def AppendItem(self, parent, text, data=None):
        item = Item(text, parent, data)
        parent.children.append(item)
        return item

    def GetItemData(self, item):
        return item.data

    def SetItemData(self, item, data):
        item.data = data

    def DeleteAllItems(self):
        self.root = None
        self.selected = None

    def GetSelection(self):
        return self.selected

    def SelectItem(self, item):
        self.selected = item

    def UnselectAll(self):
        self.selected = None

    def IsExpanded(self, item):
        return item.expanded

    def Expand(self, item):
        item.expanded = True

    def Collapse(self, item):
        item.expanded = False

    def GetItemParent(self, item):
        return item.parent

    def EnsureVisible(self, item):
        parent = item.parent
        while parent:
            self.Expand(parent)
            parent = parent.parent


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'addon/globalPlugins/todoistNvda'
wx = types.ModuleType('wx')
for name in ('Dialog', 'Panel', 'BoxSizer', 'StaticText', 'ComboBox', 'Button',
             'TextCtrl', 'WrapSizer', 'ListBox'):
    setattr(wx, name, type(name, (Window,), {}))
wx.TreeCtrl = TreeCtrl
for index, name in enumerate(('DEFAULT_DIALOG_STYLE', 'RESIZE_BORDER', 'VERTICAL',
        'HORIZONTAL', 'ALIGN_CENTER_VERTICAL', 'RIGHT', 'EXPAND', 'ALL', 'CB_READONLY',
        'TE_PROCESS_ENTER', 'TE_MULTILINE', 'TE_READONLY', 'LEFT', 'BOTTOM', 'TOP',
        'LB_SINGLE', 'TR_HAS_BUTTONS',
        'TR_LINES_AT_ROOT', 'TR_HIDE_ROOT', 'TR_SINGLE', 'TAB_TRAVERSAL')):
    setattr(wx, name, 1 << index)
for name in ('EVT_CLOSE', 'EVT_COMBOBOX', 'EVT_BUTTON', 'EVT_TEXT_ENTER', 'EVT_LISTBOX',
        'EVT_LISTBOX_DCLICK', 'EVT_KEY_DOWN', 'EVT_CHAR_HOOK', 'EVT_TREE_SEL_CHANGED',
        'EVT_TREE_ITEM_ACTIVATED'):
    setattr(wx, name, name)
wx.NOT_FOUND = -1
wx.WXK_ESCAPE = 27
wx.CallAfter = lambda fn, *args: fn(*args)
modules = {'wx': wx, 'api': types.ModuleType('api'),
           'ui': types.SimpleNamespace(message=Mock()),
           'addonHandler': types.SimpleNamespace(initTranslation=lambda: None)}
pkg = types.ModuleType('tree_test_addon')
pkg.__path__ = [str(PACKAGE)]
modules['tree_test_addon'] = pkg
# Load the actual production modules without importing NVDA's global plugin entry point.
with patch.dict(sys.modules, modules), patch.object(builtins, '_', lambda s: s, create=True):
    dialogs = __import__('tree_test_addon.dialogs', fromlist=['dialogs'])


def task(id, parent=None, **kwargs):
    return dict(id=id, parent_id=parent, content=id, project_id='p', **kwargs)


class TaskTreeTests(unittest.TestCase):
    def setUp(self):
        self.translation = patch.object(builtins, '_', lambda s: s, create=True)
        self.translation.start()
        self.addCleanup(self.translation.stop)
        with patch.object(dialogs.TaskBrowserDialog, '_load_projects'), patch.object(
                dialogs.TaskBrowserDialog, '_load_tasks'):
            self.dialog = dialogs.TaskBrowserDialog(None, client_factory=Mock())

    def render(self, tasks):
        self.dialog._finish_tasks(tasks, [])
        return self.dialog.tasksTree

    def items(self, tree):
        result = {}
        pending = list(tree.root.children)
        while pending:
            item = pending.pop(0)
            result[item.data['id']] = item
            pending.extend(item.children)
        return result

    def test_native_hierarchy_handles_unordered_recursive_tasks_and_orphans(self):
        tree = self.render([task('grandchild', 'child'), task('child', 'parent'),
                            task('parent'), task('orphan', 'missing')])
        self.assertIsInstance(tree, TreeCtrl)
        items = self.items(tree)
        self.assertIs(items['grandchild'].parent, items['child'])
        self.assertIs(items['child'].parent, items['parent'])
        self.assertIs(items['orphan'].parent, tree.root)
        self.assertFalse(items['parent'].expanded)
        self.assertTrue(tree.style & wx.TR_HIDE_ROOT)

    def test_native_arrows_and_tab_are_not_intercepted_and_buttons_retained(self):
        tree = self.render([task('parent'), task('child', 'parent')])
        for key in (37, 38, 39, 40, 9):
            event = Mock()
            event.GetKeyCode.return_value = key
            tree.bindings[wx.EVT_KEY_DOWN](event)
            event.Skip.assert_called_once_with()
        self.assertIn(wx.EVT_TREE_SEL_CHANGED, tree.bindings)
        for name in ('completeButton', 'editTextButton', 'editDueButton', 'labelsButton',
                     'deleteButton', 'subtasksButton', 'closeButton'):
            self.assertIn(wx.EVT_BUTTON, getattr(self.dialog, name).bindings)

    def test_refresh_restores_selection_expansion_and_uses_parent_fallback(self):
        tasks = [task('parent'), task('child', 'parent'), task('grandchild', 'child')]
        tree = self.render(tasks)
        items = self.items(tree)
        tree.Expand(items['parent'])
        tree.Expand(items['child'])
        tree.SelectItem(items['grandchild'])
        self.render([dict(t, content=t['content'] + ' updated') for t in tasks])
        items = self.items(tree)
        self.assertEqual(self.dialog._current_task()['id'], 'grandchild')
        self.assertTrue(items['parent'].expanded)
        self.assertTrue(items['child'].expanded)
        self.render(tasks[:2])
        self.assertEqual(self.dialog._current_task()['id'], 'child')
        tree.Collapse(self.items(tree)['parent'])
        tree.SelectItem(self.items(tree)['parent'])
        self.render(tasks[:2])
        self.assertFalse(self.items(tree)['parent'].expanded)

    def test_search_and_label_filters_promote_matching_descendants(self):
        tree = self.render([task('parent'), task('child', 'parent', labels=['tag']),
                            task('grandchild', 'child', labels=['tag'])])
        self.dialog.searchEdit.value = 'child'
        self.dialog._onSearch(None)
        items = self.items(tree)
        self.assertEqual(set(items), {'child', 'grandchild'})
        self.assertIs(items['child'].parent, tree.root)
        self.assertIs(items['grandchild'].parent, items['child'])
        self.dialog.searchEdit.value = ''
        self.dialog._labelFilter = {'tag'}
        self.dialog._apply_filter()
        self.assertEqual(set(self.items(tree)), {'child', 'grandchild'})

    def test_actions_use_selected_descendant_and_escape_clears_selection(self):
        tree = self.render([task('parent'), task('child', 'parent')])
        tree.SelectItem(self.items(tree)['child'])
        client = Mock()
        self.dialog._run_action = lambda message, action, **kwargs: action(client)
        self.dialog._onComplete(None)
        client.close_task.assert_called_once_with('child')
        self.dialog._completed_mode = True
        self.dialog._onComplete(None)
        client.reopen_task.assert_called_once_with('child')
        payload = dict(content='edited', labels=[], due_date=None, due_datetime=None, clear_due=True)
        self.dialog._open_editor = Mock(return_value=payload)
        for handler in (self.dialog._onEditText, self.dialog._onEditDue, self.dialog._onEditLabels):
            handler(None)
        self.assertEqual(client.update_task.call_count, 3)
        self.assertTrue(all(call.args[0] == 'child' for call in client.update_task.call_args_list))
        event = Mock()
        event.GetKeyCode.return_value = wx.WXK_ESCAPE
        tree.bindings[wx.EVT_KEY_DOWN](event)
        self.assertIsNone(self.dialog._current_task())
        self.assertFalse(self.dialog.completeButton.enabled)
        self.assertTrue(self.dialog.addButton.enabled)

    def test_filter_rebuild_keeps_surviving_selection_and_hidden_expansion(self):
        tasks = [task('parent'), task('child', 'parent'), task('other')]
        tree = self.render(tasks)
        items = self.items(tree)
        tree.Expand(items['parent'])
        tree.SelectItem(items['other'])
        self.dialog.searchEdit.value = 'other'
        self.dialog._apply_filter()
        self.assertEqual(self.dialog._current_task()['id'], 'other')
        self.dialog.searchEdit.value = ''
        self.dialog._apply_filter()
        self.assertTrue(self.items(tree)['parent'].expanded)
        self.assertEqual(self.dialog._current_task()['id'], 'other')

    def test_buttons_delete_and_subtasks_target_selected_node_not_flat_index(self):
        tree = self.render([task('child', 'parent'), task('parent'), task('other')])
        tree.SelectItem(self.items(tree)['child'])
        event = Mock()
        tree.bindings[wx.EVT_TREE_SEL_CHANGED](event)
        self.assertTrue(self.dialog.completeButton.enabled)
        self.assertTrue(self.dialog.subtasksButton.enabled)
        self.assertFalse(self.dialog.addButton.enabled)
        client = Mock()
        self.dialog._run_action = lambda message, action, **kwargs: action(client)
        confirmation = Mock()
        confirmation.ShowModal.return_value = 1
        with patch.object(wx, 'MessageDialog', return_value=confirmation, create=True), \
                patch.multiple(wx, OK=1, CANCEL=2, ICON_WARNING=4, ID_OK=1, create=True):
            self.dialog._onDelete(None)
        client.delete_task.assert_called_once_with('child')
        with patch.object(dialogs, 'TaskBrowserDialog') as browser:
            self.dialog._onOpenSubtasks(None)
            self.assertEqual(browser.call_args.kwargs['parent_task']['id'], 'child')
            browser.return_value.Show.assert_called_once_with()

    def test_subtask_window_adds_under_its_parent_and_focuses_tree(self):
        with patch.object(dialogs.TaskBrowserDialog, '_load_tasks'):
            branch = dialogs.TaskBrowserDialog(None, client_factory=Mock(),
                                               parent_task=task('child', 'parent'))
        branch._finish_tasks([task('grandchild', 'child')], [])
        branch.tasksTree.SetFocus = Mock()
        branch.focus_initial_control()
        branch.tasksTree.SetFocus.assert_called_once_with()
        branch._open_editor = Mock(return_value=dict(content='new subtask', labels=[],
                                                   due_date=None, due_datetime=None))
        client = Mock()
        branch._run_action = lambda message, action, **kwargs: action(client)
        branch._onAddTask(None)
        self.assertEqual(client.add_task.call_args.kwargs['parent_id'], 'child')
        self.assertEqual(client.add_task.call_args.kwargs['project_id'], 'p')

    def test_completed_browser_builds_real_hierarchy_with_reopen_button(self):
        with patch.object(dialogs.TaskBrowserDialog, '_load_projects'):
            completed = dialogs.TaskBrowserDialog(None, client_factory=Mock(), completed_mode=True)
        completed._finish_tasks([task('parent', _completed_at='2026-01-01'),
                                 task('child', 'parent', _completed_at='2026-01-01')], [])
        tree = completed.tasksTree
        items = self.items(tree)
        self.assertIs(items['child'].parent, items['parent'])
        self.assertIn('Completed', items['child'].text)
        tree.SelectItem(items['child'])
        tree.bindings[wx.EVT_TREE_SEL_CHANGED](Mock())
        self.assertTrue(completed.completeButton.enabled)
        self.assertIsNone(completed.addButton)
        self.assertIsNone(completed.deleteButton)
        client = Mock()
        completed._run_action = lambda message, action, **kwargs: action(client)
        completed._onComplete(None)
        client.reopen_task.assert_called_once_with('child')

    def test_deep_hierarchy_and_sibling_order_do_not_depend_on_python_recursion(self):
        tasks = [task(str(index), str(index - 1) if index else None) for index in range(1200)]
        tree = self.render(list(reversed(tasks)))
        items = self.items(tree)
        self.assertEqual(len(items), 1200)
        self.assertIs(items['1199'].parent, items['1198'])
        self.render([task('b', 'p'), task('p'), task('a', 'p')])
        self.assertEqual([item.data['id'] for item in self.items(tree)['p'].children], ['b', 'a'])

    def test_empty_refresh_and_cycles_do_not_lose_tasks_or_crash(self):
        tree = self.render([task('a', 'b'), task('b', 'a'), task('self', 'self')])
        self.assertEqual(set(self.items(tree)), {'a', 'b', 'self'})
        tree.SelectItem(self.items(tree)['a'])
        self.render([])
        self.assertIsNone(self.dialog._current_task())
        self.assertFalse(self.dialog.completeButton.enabled)

    def test_top_level_loader_retains_hierarchy_across_api_pages(self):
        client = dialogs.TodoistClient('test-key-not-a-secret')
        client._request = Mock(side_effect=[
            {'results': [task('grandchild', 'child')], 'next_cursor': 'page2'},
            {'results': [task('parent'), task('child', 'parent')], 'next_cursor': None},
        ])
        client.get_labels = Mock(return_value=[])
        self.dialog._client_factory = lambda: client
        queued = []
        with patch.object(dialogs, '_call_in_thread', side_effect=queued.append):
            self.dialog._load_tasks()
        self.assertEqual(len(queued), 1)
        queued[0]()
        items = self.items(self.dialog.tasksTree)
        self.assertIs(items['grandchild'].parent, items['child'])
        self.assertIs(items['child'].parent, items['parent'])
        self.assertEqual(client._request.call_args_list[1].kwargs['params']['cursor'], 'page2')

    def test_load_failure_and_closed_dialog_do_not_replace_tree(self):
        tree = self.render([task('parent')])
        client = Mock()
        client.get_labels.return_value = []
        client.get_tasks.side_effect = RuntimeError('test offline error')
        self.dialog._client_factory = lambda: client
        queued = []
        with patch.object(dialogs, '_call_in_thread', side_effect=queued.append):
            self.dialog._load_tasks()
        self.assertEqual(len(queued), 1)
        with patch.object(self.dialog, '_show_error') as show_error:
            queued[0]()
            show_error.assert_called_once()
            self.assertEqual(str(show_error.call_args.args[0]), 'test offline error')
        self.assertEqual(set(self.items(tree)), {'parent'})
        self.dialog._closed = True
        self.dialog._safe_ui(self.dialog._finish_tasks, [task('other')], [])
        self.assertEqual(set(self.items(tree)), {'parent'})

    def test_child_browser_loads_all_descendants_in_worker_and_completed_path(self):
        all_tasks = [task('parent'), task('child', 'parent'), task('grandchild', 'child'), task('other')]
        self.dialog._parent_task = all_tasks[0]
        client = Mock()
        client.get_tasks.return_value = all_tasks
        client.get_completed_tasks.return_value = all_tasks
        client.get_labels.return_value = []
        self.dialog._client_factory = lambda: client
        for completed in (False, True):
            self.dialog._completed_mode = completed
            queued = []
            with patch.object(dialogs, '_call_in_thread', side_effect=queued.append):
                self.dialog._load_tasks()
            self.assertEqual(len(queued), 1)
            queued[0]()
            self.assertEqual(set(self.items(self.dialog.tasksTree)), {'child', 'grandchild'})
        client.get_tasks.assert_called_once_with('p')
        client.get_completed_tasks.assert_called_once_with(project_id='p')
        client.get_subtasks.assert_not_called()


if __name__ == '__main__':
    unittest.main()

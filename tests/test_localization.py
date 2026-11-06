"""Gettext catalog checks; native Windows/NVDA execution is not implied."""
import ast
import gettext
import io
from pathlib import Path
import string
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class LocalizationTests(unittest.TestCase):
    def catalog(self):
        from build_translations import compile_catalog
        return gettext.GNUTranslations(io.BytesIO(compile_catalog(
            ROOT / 'addon/locale/ru/LC_MESSAGES/nvda.po')))

    def test_all_source_messages_have_complete_russian_translations(self):
        catalog = self.catalog()
        messages = set()
        formatter = string.Formatter()
        for path in (ROOT / 'addon/globalPlugins/todoistNvda').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == '_'):
                    continue
                text = ast.literal_eval(node.args[0])
                messages.add(text)
                self.assertTrue(text.isascii(), text)
                self.assertIn(text, catalog._catalog)
                translated = catalog.gettext(text)
                self.assertTrue(translated)
                if not text.startswith('Todoist') or text not in ('Todoist', 'Todoist...'):
                    self.assertNotEqual(text, translated)
                fields = lambda value: {field for _, field, _, _ in formatter.parse(value) if field}
                self.assertEqual(fields(text), fields(translated), text)
        self.assertEqual(messages, set(catalog._catalog) - {''})

    def test_native_gettext_language_selection_and_fallback(self):
        from build_translations import compile_catalog
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'ru/LC_MESSAGES/nvda.mo'
            target.parent.mkdir(parents=True)
            target.write_bytes(compile_catalog(ROOT / 'addon/locale/ru/LC_MESSAGES/nvda.po'))
            for language, expected in [('ru', 'Добавить проект'), ('ru_RU', 'Добавить проект'),
                                       ('en', 'Add project'), ('en_US', 'Add project'),
                                       ('de', 'Add project')]:
                with self.subTest(language=language):
                    translate = gettext.translation('nvda', directory, [language], fallback=True).gettext
                    self.assertEqual(translate('Add project'), expected)

    def test_module_initialization_localizes_months_using_nvda_binding_contract(self):
        import importlib.util
        import inspect
        import types
        from test_task_tree import modules as base_modules
        for language, translation in [('en', gettext.NullTranslations()), ('ru', self.catalog())]:
            def initialize():
                # NVDA installs the add-on gettext function in each caller module.
                inspect.currentframe().f_back.f_globals['_'] = translation.gettext

            name = 'tree_test_addon.localized_dialogs'
            spec = importlib.util.spec_from_file_location(name,
                ROOT / 'addon/globalPlugins/todoistNvda/dialogs.py')
            module = importlib.util.module_from_spec(spec)
            with self.subTest(language=language), patch.dict(sys.modules, {
                    **base_modules, name: module,
                    'addonHandler': types.SimpleNamespace(initTranslation=initialize)}):
                spec.loader.exec_module(module)
                self.assertEqual(module.MONTH_CHOICES[0], (1, translation.gettext('January')))
                self.assertEqual(module.MONTH_CHOICES[-1], (12, translation.gettext('December')))
                self.assertEqual(module._('Task updated'), translation.gettext('Task updated'))

    def test_compiler_accepts_continuations_and_rejects_incomplete_catalogs(self):
        from build_translations import compile_catalog
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.po'
            path.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
                            'msgid "Hello "\n"world"\nmsgstr "Привет, "\n"мир"\n', encoding='utf-8')
            catalog = gettext.GNUTranslations(io.BytesIO(compile_catalog(path)))
            self.assertEqual(catalog.gettext('Hello world'), 'Привет, мир')
            for bad in ['msgid "Missing"\n', 'msgid "Empty"\nmsgstr ""\n',
                        '#, fuzzy\nmsgid "Hello"\nmsgstr "Привет"\n',
                        'msgid "a"\nmsgstr "b"\n\nmsgid "a"\nmsgstr "c"\n',
                        'msgid "a"\nmsgid_plural "aa"\nmsgstr[0] "b"\n']:
                with self.subTest(bad=bad):
                    path.write_text(bad, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        compile_catalog(path)

    def test_manager_controls_status_and_content_in_both_languages(self):
        import builtins
        from test_task_tree import dialogs, wx, Window, task
        for language, translation in [('en', gettext.NullTranslations()), ('ru', self.catalog())]:
            labels = []
            original = Window.__init__

            def capture(window, *args, **kwargs):
                labels.append(kwargs.get('label', kwargs.get('title', '')))
                original(window, *args, **kwargs)

            with self.subTest(language=language), patch.object(builtins, '_', translation.gettext, create=True), \
                    patch.object(Window, '__init__', capture), \
                    patch.object(dialogs.TaskBrowserDialog, '_load_projects'), \
                    patch.object(dialogs.TaskBrowserDialog, '_load_tasks'):
                dialog = dialogs.TaskBrowserDialog(None, client_factory=Mock())
                expected = ['Add project', 'Search', 'Filter', 'Complete', 'Edit text',
                            'Edit due date', 'Labels', 'Delete', 'Subtasks', 'Completed tasks', 'Close']
                for label in expected:
                    self.assertIn(translation.gettext(label), labels)
                dialog.statusLabel.SetLabel = Mock()
                dialog._finish_tasks([task('raw user task', labels=['raw-label'])], [])
                dialog.statusLabel.SetLabel.assert_called_with(translation.gettext('Tasks: {count}').format(count=1))
                self.assertEqual(dialog.tasksTree.root.children[0].text, 'raw user task #raw-label')
                self.assertEqual(dialogs._task_summary({'content': '', '_completed_at': '2026-11-06'}),
                    f"{translation.gettext('Untitled task')} ({translation.gettext('Completed')}: 2026-11-06)")


if __name__ == '__main__':
    unittest.main()

import importlib
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from jdsh import config
from jdsh.errors import ConfigError


class SettingsTests(unittest.TestCase):
    def test_import_does_not_read_configuration(self):
        with patch.object(Path, 'home', side_effect=AssertionError('import must not locate settings')):
            importlib.reload(config)

    def test_version_uses_distribution_name(self):
        with patch('importlib.metadata.version', return_value='1.2.3') as version:
            importlib.reload(config)
            self.assertEqual(config.VERSION, '1.2.3')
            version.assert_called_once_with('jdsh')
        importlib.reload(config)

    def test_defaults_are_immutable(self):
        settings = config.Settings()
        self.assertEqual((settings.host, settings.port, settings.refresh_rate), ('127.0.0.1', 3128, 1.0))
        with self.assertRaises(FrozenInstanceError):
            settings.port = 1234

    def test_missing_default_files_use_defaults(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'home', return_value=Path(directory)):
            self.assertEqual(config.load_settings(), config.Settings())

    def test_default_names_prefer_conf_without_merging(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'home', return_value=Path(directory)):
            folder = Path(directory) / '.config' / 'jdsh'
            folder.mkdir(parents=True)
            (folder / 'jdsh.conf').write_text('[settings]\nPORT=1234\n', encoding='utf-8')
            (folder / 'jdsh.config').write_text('[settings]\nHOST=alternate\nPORT=5678\n', encoding='utf-8')
            settings = config.load_settings()
            self.assertEqual((settings.host, settings.port), ('127.0.0.1', 1234))

    def test_legacy_documented_name_is_supported(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'home', return_value=Path(directory)):
            folder = Path(directory) / '.config' / 'jdsh'
            folder.mkdir(parents=True)
            (folder / 'jdsh.config').write_text('[settings]\nHOST= example.org \nPORT=65535\nREFRESH_RATE=0.25\n', encoding='utf-8')
            settings = config.load_settings()
            self.assertEqual((settings.host, settings.port, settings.refresh_rate), ('example.org', 65535, 0.25))

    def test_explicit_missing_file_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ConfigError, 'Cannot read settings file'):
                config.load_settings(Path(directory) / 'missing')

    def test_bom_and_case_insensitive_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings'
            path.write_text('\ufeff[settings]\nhost=example.org\nport=1\nrefresh_rate=2.5\n', encoding='utf-8')
            self.assertEqual(config.load_settings(path), config.Settings('example.org', 1, 2.5))

    def test_invalid_values_and_syntax_are_reported_with_path(self):
        values = ['HOST= ', 'PORT=0', 'PORT=65536', 'PORT=no', 'REFRESH_RATE=0',
                  'REFRESH_RATE=-1', 'REFRESH_RATE=nan', 'REFRESH_RATE=inf',
                  'REFRESH_RATE=bad', 'PORT=%(missing)s']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings'
            for value in values + ['malformed']:
                with self.subTest(value=value):
                    path.write_text('[settings]\n' + value, encoding='utf-8')
                    with self.assertRaises(ConfigError) as caught:
                        config.load_settings(path)
                    self.assertIn(str(path), str(caught.exception))

    def test_invalid_preferred_file_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'home', return_value=Path(directory)):
            folder = Path(directory) / '.config' / 'jdsh'
            folder.mkdir(parents=True)
            (folder / 'jdsh.conf').write_text('[settings]\nPORT=bad', encoding='utf-8')
            (folder / 'jdsh.config').write_text('[settings]\nPORT=1234', encoding='utf-8')
            with self.assertRaises(ConfigError):
                config.load_settings()

    def test_unreadable_or_non_utf8_files_are_errors(self):
        with patch.object(Path, 'open', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(ConfigError, 'denied'):
                config.load_settings()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings'
            path.write_bytes(b'\xff')
            with self.assertRaises(ConfigError):
                config.load_settings(path)

"""Compare pre-refactor CLI output, errors, exits and API calls using fake devices."""
import argparse
import contextlib
import io
import subprocess
import types
from unittest.mock import MagicMock, patch
from rich.console import Console
from jdsh import cli, config

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', default='44e9183', help='Local trusted pre-refactor git ref')
args = parser.parse_args()

baseline = types.ModuleType('jdsh._baseline_cli')
baseline.__package__ = 'jdsh'
source = subprocess.check_output(['git', 'show', f'{args.baseline}:src/jdsh/cli.py'], text=True)
exec(compile(source, 'baseline_cli.py', 'exec'), baseline.__dict__)


def run(module, argv, packages, failure):
    device = MagicMock()
    link = {'uuid': 123, 'name': '[red]file[/red].zip', 'bytesLoaded': 512,
            'bytesTotal': 1024, 'speed': 256, 'running': True, 'finished': False,
            'enabled': True, 'eta': 2, 'status': None, 'url': 'https://example.org',
            'advancedStatus': {'AvailableStatus': {'id': 'TRUE'}}}
    device.downloadcontroller.get_current_state.return_value = 'RUNNING'
    device.downloads.query_links.return_value = [link]
    device.linkgrabber.query_links.return_value = [link]
    device.linkgrabber.query_packages.return_value = packages
    device.action.return_value = 12345
    if failure:
        section, method = failure
        getattr(getattr(device, section), method).side_effect = RuntimeError('operation denied')
    client = MagicMock()
    client.connect.return_value = device
    output, stdout, stderr = io.StringIO(), io.StringIO(), io.StringIO()
    console = Console(file=output, force_terminal=False, width=240)
    exit_code = 0
    with patch.object(module, 'JDClient', return_value=client), \
         patch.object(module.config, 'load_settings', return_value=config.Settings()), \
         contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            module.main(argv, console=console)
        except SystemExit as exc:
            exit_code = exc.code
    return output.getvalue(), stdout.getvalue(), stderr.getvalue(), exit_code, device.mock_calls

successes = [
    ['help'], ['status'], ['list'], ['ls'], ['list', '-d'], ['grabber'], ['grabber', '-d'],
    ['add', 'https://a.example https://b.example', 'https://a.example'],
    ['confirm'], ['remove', '123', '8'], ['rm', '123'], ['start'], ['stop'], ['clear'], ['version'],
]
cases = [(argv, [{'uuid': 8}, {'uuid': 3}], None) for argv in successes]
cases.append((['confirm'], [], None))
for argv, section, method in (
    (['status'], 'downloadcontroller', 'get_current_state'),
    (['status'], 'downloads', 'query_links'),
    (['list'], 'downloads', 'query_links'),
    (['grabber'], 'linkgrabber', 'query_links'),
    (['add', 'https://example.org'], 'linkgrabber', 'add_links'),
    (['confirm'], 'linkgrabber', 'query_packages'),
    (['confirm'], 'linkgrabber', 'move_to_downloadlist'),
    (['remove', '123'], 'downloads', 'remove_links'),
    (['start'], 'downloadcontroller', 'start_downloads'),
    (['stop'], 'downloadcontroller', 'stop_downloads'),
    (['clear'], 'downloads', 'cleanup'),
):
    cases.append((argv, [{'uuid': 8}, {'uuid': 3}], (section, method)))
for argv, packages, failure in cases:
    previous = run(baseline, argv, packages, failure)
    current = run(cli, argv, packages, failure)
    if previous != current:
        raise AssertionError((argv, failure, previous, current))
print(f'{len(cases)} CLI output/error/exit/API-call comparisons passed.')

"""LinkGrabber scoping, independent SDK routes, and mutation failure boundaries."""

import io
import json
import unittest
from unittest.mock import MagicMock, patch

from myjdapi.myjdapi import Linkgrabber
from rich.console import Console

from jdsh import arguments, cli, rendering, services
from jdsh.client import GRABBER_LINK_STATE_QUERY
from jdsh.errors import ServiceError


class RecordingDevice:
    def __init__(self, result=None):
        self.result = result
        self.requests = []
        self.linkgrabber = Linkgrabber(self)

    def action(self, endpoint, params):
        self.requests.append((endpoint, params))
        return self.result


class LinkGrabberSelectionTests(unittest.TestCase):
    def test_confirm_selection_uses_sdk_once_and_preserves_namespace_order(self):
        device = RecordingDevice()
        selection = services.confirm_grabber_selection(device, ['2', 1, 2], [3, 3, 1])
        self.assertEqual(selection.link_ids, (2, 1))
        self.assertEqual(selection.package_ids, (3, 1))
        self.assertEqual(device.requests, [('/linkgrabberv2/moveToDownloadlist', [[2, 1], [3, 1]])])

    def test_confirm_cli_mixed_options_all_and_legacy_scope(self):
        for argv, expected in ((['confirm', '2', '--package', '3', '1'], [[2, 1], [3]]),
                               (['confirm', '--package=3'], [[], [3]]),
                               (['confirm', '--all'], [[], [3, 4]]),
                               (['confirm'], [[], [3, 4]])):
            with self.subTest(argv=argv):
                client = MagicMock()
                device = client.connect.return_value
                device.linkgrabber.query_packages.return_value = [{'uuid': 3}, {'uuid': 4}]
                device.linkgrabber.move_to_downloadlist.return_value = None
                output = io.StringIO()
                with patch.object(cli.config, 'load_settings'), patch.object(cli, 'JDClient', return_value=client):
                    cli.main(argv, console=Console(file=output, width=160))
                device.linkgrabber.move_to_downloadlist.assert_called_once_with(*expected)
                self.assertIn('Submitted confirm request', output.getvalue())
                self.assertNotIn('Moved ', output.getvalue())
                device.downloadcontroller.start_downloads.assert_not_called()
                device.downloads.query_links.assert_not_called()
                if argv in (['confirm'], ['confirm', '--all']):
                    device.linkgrabber.query_packages.assert_called_once_with([{'startAt': 0, 'maxResults': -1}])
                else:
                    device.linkgrabber.query_packages.assert_not_called()

    def test_invalid_cli_never_loads_settings(self):
        for argv in (['confirm', '--all', '1'], ['confirm', '--package', '2', '--all'],
                     ['confirm', '0'], ['confirm', '1_2'], ['confirm', '--pack', '1'],
                     ['confirm', '--al'], ['confirm', '--package', '-1'],
                     ['grabber', '--package', '0'], ['grabber', '--job', '１'],
                     ['grabber', '--availability', 'running'], ['grabber', '--host', ' '],
                     ['grabber', '--jo', '1']):
            with self.subTest(argv=argv), patch.object(cli.config, 'load_settings') as config, \
                 patch.object(cli, 'JDClient') as client, patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as caught:
                    cli.main(argv)
                self.assertEqual(caught.exception.code, 2)
                config.assert_not_called()
                client.assert_not_called()

    def test_empty_or_invalid_service_selections_never_query_or_move(self):
        for operation in (lambda d: services.confirm_grabber_selection(d),
                          lambda d: services.confirm_grabber_selection(d, [True]),
                          lambda d: services.confirm_grabber_selection(d, package_ids=['1_2']),
                          lambda d: services.list_grabber_links(d, job_ids=[False]),
                          lambda d: services.list_grabber_links(d, package_ids=[1 << 63])):
            device = RecordingDevice()
            with self.assertRaises(ValueError):
                operation(device)
            self.assertEqual(device.requests, [])

    def test_all_confirm_validates_complete_snapshot_and_deduplicates(self):
        device = MagicMock()
        device.linkgrabber.query_packages.return_value = [{'uuid': 3}, {'uuid': 3}, {'uuid': 4}]
        self.assertEqual(services.confirm_grabber(device), 2)
        device.linkgrabber.move_to_downloadlist.assert_called_once_with([], [3, 4])
        for rows in ([{'uuid': 3}, {'uuid': False}], [{'uuid': 3}, {}]):
            device = MagicMock()
            device.linkgrabber.query_packages.return_value = rows
            with self.assertRaises((ValueError, KeyError)):
                services.confirm_grabber(device)
            device.linkgrabber.move_to_downloadlist.assert_not_called()

    def test_confirm_false_and_exception_never_report_success_or_retry(self):
        for argv in (['confirm', '1'], ['confirm', '--all']):
            for failure in (False, RuntimeError('denied')):
                device = MagicMock()
                device.linkgrabber.query_packages.return_value = [{'uuid': 3}]
                if failure is False:
                    device.linkgrabber.move_to_downloadlist.return_value = False
                else:
                    device.linkgrabber.move_to_downloadlist.side_effect = failure
                output = io.StringIO()
                with patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as caught:
                    cli._execute(lambda: cli.cmd_confirm(device, arguments.parse_args(argv), console=Console(file=output)))
                self.assertEqual(caught.exception.code, 1)
                self.assertEqual(output.getvalue(), '')
                device.linkgrabber.move_to_downloadlist.assert_called_once()
                device.downloadcontroller.start_downloads.assert_not_called()

    def test_grabber_filter_intersection_and_missing_availability(self):
        device = MagicMock()
        links = [dict(uuid=1, name='Archive.zip', host='EXAMPLE.com', availability='ONLINE', packageUUID=3),
                 dict(uuid=2, name='archive2.zip', host='example.com', availability='OFFLINE', packageUUID=4),
                 dict(uuid=3, name='archive3.zip', host='other.com', availability='UNKNOWN', packageUUID=3),
                 dict(uuid=4, name='archive4.zip', host='example.com', packageUUID=3)]
        device.linkgrabber.query_links.return_value = links
        result = services.list_grabber_links(device, search='ARCHIVE', hosts=['example.com'],
                                            availability=['online', 'offline'], package_ids=[3])
        self.assertEqual(result, [links[0]])
        self.assertEqual(services.list_grabber_links(device, availability=['UNKNOWN']), [links[2]])
        self.assertIs(services.list_grabber_links(device, search=' '), links)
        self.assertEqual(links[0]['host'], 'EXAMPLE.com')

    def test_job_and_package_query_fields_match_official_schema_and_sdk(self):
        # https://my.jdownloader.org/developers/: CrawledLinkQuery has singular
        # host, packageUUIDs and jobUUIDs. AddLinksQuery.assignJobID enables association.
        device = RecordingDevice([])
        services.list_grabber_links(device, detail=True, job_ids=[8, 8], package_ids=[3, 3])
        endpoint, params = device.requests[0]
        self.assertEqual(endpoint, '/linkgrabberv2/queryLinks')
        self.assertEqual(params[0]['jobUUIDs'], [8])
        self.assertEqual(params[0]['packageUUIDs'], [3])
        self.assertIs(params[0]['host'], True)
        self.assertNotIn('hosts', params[0])
        self.assertNotIn('password', params[0])
        self.assertEqual(params[0]['maxResults'], -1)
        self.assertIs(params[0]['url'], True)
        self.assertIs(params[0]['variants'], True)
        self.assertNotIn('jobUUIDs', GRABBER_LINK_STATE_QUERY)

    def test_json_only_preserves_detail_fields_and_future_records(self):
        device = MagicMock()
        raw = [{'uuid': 1, 'name': '[red]File', 'future': {'value': None}, 'url': '[blue]URL'}]
        device.linkgrabber.query_links.return_value = raw
        output = io.StringIO()
        with patch('sys.stdout', output):
            cli.cmd_grabber(device, arguments.parse_args(['grabber', '--json']))
        self.assertEqual(json.loads(output.getvalue()), raw)
        self.assertIs(device.linkgrabber.query_links.call_args.args[0][0]['url'], True)

    def test_rendering_preserves_markup_and_separates_no_match_from_empty(self):
        output = io.StringIO()
        rendering.render_grabber([{'uuid': 1, 'name': '[red]name', 'host': '[blue]host',
                                   'url': '[green]url'}], detail=True, console=Console(file=output, width=220))
        for expected in ('[red]name', '[blue]host', '[green]url', 'NOT REPORTED', 'ALL pending packages'):
            self.assertIn(expected, output.getvalue())
        for filtered, expected in ((True, 'No LinkGrabber links match the filters.'),
                                   (False, 'LinkGrabber is empty.')):
            output = io.StringIO()
            rendering.render_grabber([], filtered=filtered, console=Console(file=output))
            self.assertIn(expected, output.getvalue())

    def test_add_returns_only_valid_job_id_and_requests_association(self):
        for response, expected in (({'id': 8}, 8), ({'id': '8'}, 8), (None, None),
                                   ({'id': True}, None), ({'id': 0}, None), ({}, None)):
            device = RecordingDevice(response)
            self.assertEqual(services.add_to_grabber(device, ['https://example.com']), expected)
            self.assertEqual(device.requests, [('/linkgrabberv2/addLinks', [{'links': 'https://example.com',
                              'autostart': False, 'priority': 'DEFAULT', 'assignJobID': True}])])
        device = RecordingDevice(False)
        with self.assertRaises(ServiceError):
            services.add_to_grabber(device, ['https://example.com'])
        self.assertEqual(len(device.requests), 1)

    def test_add_cli_exposes_job_and_false_does_not_print_success(self):
        device = MagicMock()
        device.linkgrabber.add_links.return_value = {'id': 8}
        output = io.StringIO()
        cli.cmd_add(device, arguments.parse_args(['add', 'https://example.com']), console=Console(file=output, width=180))
        self.assertIn('Add job ID: 8', output.getvalue())
        self.assertIn('moves ALL pending packages', output.getvalue())
        self.assertIn('jd confirm --package ID', output.getvalue())
        self.assertIn('jd grabber --job 8', output.getvalue())
        device.linkgrabber.move_to_downloadlist.assert_not_called()
        device.downloadcontroller.start_downloads.assert_not_called()
        device.linkgrabber.add_links.return_value = False
        output = io.StringIO()
        with self.assertRaises(ServiceError):
            cli.cmd_add(device, arguments.parse_args(['add', 'https://example.com']), console=Console(file=output))
        self.assertEqual(output.getvalue(), '')

"""On-demand, read-only selected-link diagnosis using the CLI service."""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import services
from .diagnostics import availability_label
from .errors import ServiceError


class Details:
    def __init__(self):
        self.link_id = None
        self.payload = None
        self.error = None
        self.offset = 0
        self.lines = []
        self.capacity = 1

    @property
    def is_open(self):
        return self.link_id is not None

    def fetch(self, device, link_id):
        self.link_id = link_id
        self.payload, self.error, self.offset = None, None, 0
        try:
            self.payload = services.explain_download(device, link_id)
        except ServiceError as error:
            self.error = str(error)

    def close(self):
        self.link_id = None
        self.payload, self.error = None, None

    def scroll(self, key):
        if key not in ('up', 'down', 'j', 'k', 'pageup', 'pagedown', 'home', 'end'):
            return False
        if key in ('up', 'k'):
            self.offset -= 1
        elif key in ('down', 'j'):
            self.offset += 1
        elif key == 'pageup':
            self.offset -= self.capacity
        elif key == 'pagedown':
            self.offset += self.capacity
        elif key == 'home':
            self.offset = 0
        elif key == 'end':
            self.offset = len(self.lines)
        self._clamp()
        return True

    def _clamp(self):
        self.offset = max(0, min(self.offset, len(self.lines) - self.capacity))

    def panel(self, width, height, *, polling_failed=False):
        text = Text()
        def field(label, value):
            # Treat server content as literal text, including markup and newlines.
            value = 'not provided' if value is None else ' '.join(str(value).splitlines())
            text.append(label + ': ', style='bold')
            text.append(value + '\n')
        field('Link ID', self.link_id)
        field('View', 'Captured on demand; d refreshes')
        if polling_failed:
            field('Warning', 'Status polling unavailable; captured details may be stale')
        if self.error:
            field('Details error', self.error)
        elif self.payload is not None:
            payload = self.payload
            diagnosis = payload['diagnosis']
            field('Name', payload.get('name'))
            field('Controller', payload.get('controllerState'))
            field('Diagnosis', diagnosis.get('state'))
            field('Source', diagnosis.get('source'))
            field('Reason', diagnosis.get('reason'))
            field('Status', payload.get('status'))
            field('Availability', availability_label(payload))
            field('Extraction', payload.get('extractionStatus'))
        self.capacity = max(1, height - 2)
        self.lines = text.wrap(Console(), max(1, width - 4), overflow='fold')
        self._clamp()
        visible = Text('\n').join(self.lines[self.offset:self.offset + self.capacity])
        return Panel(visible, title='Link details / diagnosis', border_style='cyan')

    def footer(self):
        first = self.offset + 1 if self.lines else 0
        last = min(len(self.lines), self.offset + self.capacity)
        return Text(f'Details ID: {self.link_id} | Lines: {first}-{last}/{len(self.lines)}\n'
                    'j/k Scroll | PgUp/Dn | Home/End | d Refresh | q Back | s Start/Stop | ^C Quit')

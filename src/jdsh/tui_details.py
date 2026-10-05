"""On-demand, read-only selected-link diagnosis using the CLI service."""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import services
from .diagnostics import availability_label
from .errors import ServiceError


def display_text(value):
    """Preserve newlines and markup glyphs, neutralizing terminal controls."""
    text = str(value).replace('\r\n', '\n').replace('\r', '\n')
    return ''.join('?' if (ord(char) < 32 and char != '\n') or 127 <= ord(char) <= 159 else char
                   for char in text)


class Details:
    def __init__(self, console=None):
        self.console = Console() if console is None else console
        self.link_id = None
        self.payload = None
        self.error = None
        self.offset = 0
        self.lines = []
        self.capacity = 1
        self.controller_requested = False

    @property
    def is_open(self):
        return self.link_id is not None

    def fetch(self, device, link_id):
        self.link_id = link_id
        self.payload, self.error, self.offset = None, None, 0
        self.controller_requested = False
        try:
            self.payload = services.explain_download(device, link_id)
        except ServiceError as error:
            self.error = str(error)

    def close(self):
        self.link_id = None
        self.payload, self.error = None, None
        self.offset, self.lines, self.capacity = 0, [], 1
        self.controller_requested = False

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
            self.offset = max(0, len(self.lines) - self.capacity)
        self._clamp()
        return True

    def _clamp(self):
        self.offset = max(0, min(self.offset, len(self.lines) - self.capacity))

    def panel(self, width, height, *, polling_failed=False):
        """Wrap using the supplied console, update viewport bounds, and clamp scroll."""
        text = Text()
        def field(label, value):
            value = 'not provided' if value is None else display_text(value)
            text.append(label + ': ', style='bold')
            text.append(value + '\n')
        field('Link ID', self.link_id)
        field('View', 'Captured on demand; d refreshes')
        if polling_failed:
            field('Warning', 'Status polling unavailable; captured details may be stale')
        if self.controller_requested:
            field('Warning', 'Controller action requested; refresh captured details with d')
        if self.error:
            field('Details error', self.error)
        elif self.payload is not None:
            payload = self.payload
            diagnosis = payload.get('diagnosis')
            diagnosis = diagnosis if isinstance(diagnosis, dict) else {}
            field('Name', payload.get('name'))
            field('Controller', payload.get('controllerState'))
            field('Diagnosis', diagnosis.get('state'))
            field('Source', diagnosis.get('source'))
            field('Reason', diagnosis.get('reason'))
            field('Status', payload.get('status'))
            field('Availability', availability_label(payload))
            field('Extraction', payload.get('extractionStatus'))
        self.capacity = max(1, height - 2)
        text.right_crop(1)  # Remove the separator after the last field, not server text.
        self.lines = text.wrap(self.console, max(1, width - 4), overflow='fold')
        self._clamp()
        visible = Text('\n').join(self.lines[self.offset:self.offset + self.capacity])
        return Panel(visible, title='Link details / diagnosis', border_style='cyan')

    def footer(self):
        first = self.offset + 1 if self.lines else 0
        last = min(len(self.lines), self.offset + self.capacity)
        stale = ' | Refresh needed' if self.controller_requested else ''
        return Text(f'Details ID: {self.link_id}{stale} | Lines: {first}-{last}/{len(self.lines)}\n'
                    'j/k Scroll | PgUp/Dn | Home/End | d Refresh | q Back | s Start/Stop | ^C Quit')

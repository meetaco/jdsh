"""Local name search with explicit editing, application and cancellation."""

from rich.text import Text
from rich.cells import cell_len
from .queue_view import filter_links, normalize_search


class Search:
    def __init__(self):
        self.query = None
        self.draft = ''
        self.editing = False

    def begin(self):
        self.draft = self.query or ''
        self.editing = True

    def handle_key(self, key):
        if not self.editing or key is None:
            return False
        if key in ('escape', '\x1b'):
            self.editing = False
        elif key in ('\r', '\n'):
            self.query = normalize_search(self.draft)
            self.editing = False
        elif key in ('\x7f', '\x08'):
            self.draft = self.draft[:-1]
        elif key == '\x15':  # Ctrl+U clears the input for a new search / clearing.
            self.draft = ''
        elif len(key) == 1 and key.isprintable() and len(self.draft) < 256:
            self.draft += key
        # Commands and navigation are consumed while editing, never executed.
        return True

    def filter(self, links):
        return filter_links(links, search=self.query)

    def prompt(self, width):
        tail = self.draft
        if cell_len(tail) > max(1, width - 10):
            while cell_len(tail) > max(1, width - 13):
                tail = tail[1:]
            tail = '...' + tail
        draft = Text('Search: /' + tail + '_')
        draft.truncate(max(1, width), overflow='ellipsis')
        return Text.assemble(draft, '\nEnter Apply | Esc Cancel | Backspace Delete | Ctrl+U Clear | ^C Quit')

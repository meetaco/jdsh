"""Terminal-independent row selection and bounded viewports for both panes."""


class Navigation:
    def __init__(self):
        self.pane = 0
        self.rows = ([], [])
        self.indices = [0, 0]
        self.offsets = [0, 0]
        self.capacity = [1, 1]
        self.selected_id = None

    def sync(self, running, unfinished):
        was_empty = not any(self.rows)
        had_selection = self.selected_id is not None
        self.rows = (running, unfinished)
        if self.selected_id is not None:
            for pane, rows in enumerate(self.rows):
                for index, row in enumerate(rows):
                    if row.get("uuid") == self.selected_id:
                        self.pane, self.indices[pane] = pane, index
                        self._clamp()
                        return
        # If the selected link disappears, keep its nearest ordinal position.
        self._clamp()
        if (had_selection or was_empty) and not self.rows[self.pane] and self.rows[1 - self.pane]:
            self.pane = 1 - self.pane
        self._select()

    def resize(self, capacities):
        self.capacity = [max(1, int(value)) for value in capacities]
        self._clamp()

    def _clamp(self):
        for pane, rows in enumerate(self.rows):
            self.indices[pane] = min(self.indices[pane], max(0, len(rows) - 1))
            self.offsets[pane] = min(self.offsets[pane], max(0, len(rows) - self.capacity[pane]))
            self.offsets[pane] = min(self.offsets[pane], self.indices[pane])
            self.offsets[pane] = max(self.offsets[pane], self.indices[pane] - self.capacity[pane] + 1)

    def _select(self):
        rows = self.rows[self.pane]
        self.selected_id = rows[self.indices[self.pane]].get("uuid") if rows else None
        self._clamp()

    def handle_key(self, key):
        if key not in ("up", "down", "j", "k", "pageup", "pagedown", "home", "end", "\t"):
            return False
        if key == "\t":
            self.pane = 1 - self.pane
        else:
            index = self.indices[self.pane]
            if key in ("up", "k"):
                index -= 1
            elif key in ("down", "j"):
                index += 1
            elif key == "pageup":
                index -= self.capacity[self.pane]
            elif key == "pagedown":
                index += self.capacity[self.pane]
            elif key == "home":
                index = 0
            elif key == "end":
                index = len(self.rows[self.pane]) - 1
            self.indices[self.pane] = max(0, index)
        self._clamp()
        self._select()
        return True

    def visible(self, pane):
        start = self.offsets[pane]
        return self.rows[pane][start:start + self.capacity[pane]]


class KeyDecoder:
    """Decode fragmented ANSI keys; never expose sequence bytes as commands."""

    def __init__(self):
        self.sequence = ""

    def feed(self, text):
        keys = []
        for char in text:
            if not self.sequence:
                if char == "\x1b":
                    self.sequence = char
                else:
                    keys.append(char)
            elif self.sequence == "\x1b":
                self.sequence = self.sequence + char if char in "[O" else ""
            else:
                # CSI ends at a final byte; SS3 has a single final byte.
                if "@" <= char <= "~":
                    code = self.sequence[2:] + char
                    key = {"A": "up", "B": "down", "H": "home", "F": "end",
                           "5~": "pageup", "6~": "pagedown", "1~": "home",
                           "4~": "end", "7~": "home", "8~": "end"}.get(code)
                    if key:
                        keys.append(key)
                    self.sequence = ""
                elif len(self.sequence) < 32:
                    self.sequence += char
                # Overlong parameter bytes are discarded until the final byte.
        return keys


WINDOWS_KEYS = {"H": "up", "P": "down", "I": "pageup", "Q": "pagedown",
                "G": "home", "O": "end"}

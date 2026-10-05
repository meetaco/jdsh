"""Terminal-independent row selection and bounded viewports for both panes."""

import time


class Navigation:
    def __init__(self):
        self.pane = 0
        self.rows = ([], [])
        self.indices = [0, 0]
        self.offsets = [0, 0]
        self.capacity = [1, 1]
        self.selected_id = None
        self.pane_ids = [None, None]

    def sync(self, running, unfinished):
        was_empty = not any(self.rows)
        had_selection = self.selected_id is not None
        self.rows = (running, unfinished)
        for pane, rows in enumerate(self.rows):
            if self.pane_ids[pane] is not None:
                for index, row in enumerate(rows):
                    if row.get("uuid") == self.pane_ids[pane]:
                        self.indices[pane] = index
                        break
        if self.selected_id is not None:
            for pane, rows in enumerate(self.rows):
                for index, row in enumerate(rows):
                    if row.get("uuid") == self.selected_id:
                        self.pane, self.indices[pane] = pane, index
                        self._select()
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
            # The window must start at/before selection as well as fit the list.
            self.offsets[pane] = min(self.offsets[pane], self.indices[pane])
            self.offsets[pane] = max(self.offsets[pane], self.indices[pane] - self.capacity[pane] + 1)

    def _select(self):
        rows = self.rows[self.pane]
        self.selected_id = rows[self.indices[self.pane]].get("uuid") if rows else None
        self._clamp()
        for pane, rows in enumerate(self.rows):
            self.pane_ids[pane] = rows[self.indices[pane]].get("uuid") if rows else None

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
    """Decode fragmented ANSI keys with a bounded lifetime for incomplete input."""

    def __init__(self, clock=time.monotonic, timeout=0.15):
        self.clock, self.timeout = clock, timeout
        self.sequence = ""
        self.last_byte_at = 0.0
        self.overlong = False

    def reset(self):
        self.sequence, self.overlong = "", False

    def expire(self):
        if self.sequence and self.clock() - self.last_byte_at >= self.timeout:
            self.reset()

    def feed(self, text):
        self.expire()
        keys = []
        for char in text:
            if self.sequence and (char == "\x1b" or ord(char) < 32):
                # A new ESC/control key cannot be a CSI parameter; reprocess it.
                self.reset()
            if not self.sequence:
                if char == "\x1b":
                    self.sequence = char
                else:
                    keys.append(char)
            elif self.sequence == "\x1b":
                if char in "[O":
                    self.sequence += char
                else:
                    self.reset()
                    keys.append(char)
            elif "@" <= char <= "~":
                code = self.sequence[2:] + char
                key = {"A": "up", "B": "down", "H": "home", "F": "end",
                       "5~": "pageup", "6~": "pagedown", "1~": "home",
                       "4~": "end", "7~": "home", "8~": "end"}.get(code)
                if key and not self.overlong:
                    keys.append(key)
                self.reset()
            elif len(self.sequence) < 32:
                self.sequence += char
            else:
                self.overlong = True
            self.last_byte_at = self.clock()
        return keys


WINDOWS_KEYS = {"H": "up", "P": "down", "I": "pageup", "Q": "pagedown",
                "G": "home", "O": "end"}

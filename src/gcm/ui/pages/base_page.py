"""Shared shell for feature pages: an accessible heading plus a body area.

Each page module (users_page.py, groups_page.py, ...) supplies its own
heading/summary text and, once implemented, replaces `body_layout`'s
placeholder content with real controls -- the heading semantics (QLabel
tagged as an accessible Heading) stay the same everywhere so screen-reader
users get a consistent "what page am I on" cue across the app.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPage(QWidget):
    def __init__(self, title: str, summary: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(title)

        layout = QVBoxLayout(self)

        heading = QLabel(title)
        heading.setAccessibleName(title)
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        body = QLabel(summary)
        body.setAccessibleName(f"{title} status")
        body.setWordWrap(True)
        layout.addWidget(body)

        self.body_layout = layout
        layout.addStretch(1)

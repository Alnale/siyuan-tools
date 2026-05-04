from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QFont, QColor
from PySide6.QtCore import QRegularExpression


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._build_rules()

    def _build_rules(self):
        # Headings — warm white, bold
        heading_format = QTextCharFormat()
        heading_format.setForeground(QColor("#e8eaf0"))
        heading_format.setFontWeight(QFont.Weight.Bold)
        for level in range(1, 7):
            pattern = QRegularExpression(rf"^{'#' * level}\s+.+$")
            self.rules.append((pattern, heading_format))

        # Bold
        bold_format = QTextCharFormat()
        bold_format.setFontWeight(QFont.Weight.Bold)
        bold_format.setForeground(QColor("#e8eaf0"))
        self.rules.append((QRegularExpression(r"\*\*[^*]+\*\*"), bold_format))
        self.rules.append((QRegularExpression(r"__[^_]+__"), bold_format))

        # Italic
        italic_format = QTextCharFormat()
        italic_format.setFontItalic(True)
        italic_format.setForeground(QColor("#9b9fb0"))
        self.rules.append((QRegularExpression(r"(?<!\*)\*(?!\*)[^*]+\*(?!\*)"), italic_format))
        self.rules.append((QRegularExpression(r"(?<!_)_(?!_)[^_]+_(?!_)"), italic_format))

        # Strikethrough
        strikethrough_format = QTextCharFormat()
        strikethrough_format.setFontStrikeOut(True)
        strikethrough_format.setForeground(QColor("#4a4e5a"))
        self.rules.append((QRegularExpression(r"~~[^~]+~~"), strikethrough_format))

        # Inline code — amber
        code_inline_format = QTextCharFormat()
        code_inline_format.setForeground(QColor("#e2a84b"))
        code_inline_format.setFontFamily("Cascadia Code, Consolas, Courier New, monospace")
        code_inline_format.setBackground(QColor("#1a1e28"))
        self.rules.append((QRegularExpression(r"`[^`\n]+`"), code_inline_format))

        # Links — soft blue
        link_format = QTextCharFormat()
        link_format.setForeground(QColor("#6b8cce"))
        link_format.setFontUnderline(True)
        self.rules.append((QRegularExpression(r"\[([^\]]+)\]\([^)]+\)"), link_format))

        # Images — muted green
        image_format = QTextCharFormat()
        image_format.setForeground(QColor("#5aad6b"))
        self.rules.append((QRegularExpression(r"!\[([^\]]*)\]\([^)]+\)"), image_format))

        # Blockquote — muted italic
        blockquote_format = QTextCharFormat()
        blockquote_format.setForeground(QColor("#7a7e90"))
        blockquote_format.setFontItalic(True)
        self.rules.append((QRegularExpression(r"^>\s+.+"), blockquote_format))

        # List markers — muted green
        list_format = QTextCharFormat()
        list_format.setForeground(QColor("#5aad6b"))
        self.rules.append((QRegularExpression(r"^\s*[-*+]\s"), list_format))
        self.rules.append((QRegularExpression(r"^\s*\d+\.\s"), list_format))

        # Horizontal rule
        hr_format = QTextCharFormat()
        hr_format.setForeground(QColor("#2a2e3a"))
        self.rules.append((QRegularExpression(r"^[-*_]{3,}\s*$"), hr_format))

        # Fenced code blocks
        self._fenced_code_start = QRegularExpression(r"^```")
        self._fenced_code_end = QRegularExpression(r"^```\s*$")
        self._fenced_code_format = QTextCharFormat()
        self._fenced_code_format.setForeground(QColor("#e2a84b"))
        self._fenced_code_format.setFontFamily("Cascadia Code, Consolas, Courier New, monospace")
        self._fenced_code_format.setBackground(QColor("#1a1e28"))

    def highlightBlock(self, text: str):
        self.setCurrentBlockState(0)

        in_code_block = self.previousBlockState() == 1

        if in_code_block:
            self.setFormat(0, len(text), self._fenced_code_format)
            if self._fenced_code_end.match(text).hasMatch():
                self.setCurrentBlockState(0)
            else:
                self.setCurrentBlockState(1)
            return

        if self._fenced_code_start.match(text).hasMatch():
            self.setFormat(0, len(text), self._fenced_code_format)
            if not self._fenced_code_end.match(text).hasMatch():
                self.setCurrentBlockState(1)
            return

        for pattern, fmt in self.rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

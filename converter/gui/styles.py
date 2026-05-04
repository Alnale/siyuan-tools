STYLESHEET = """
/* ═══════════════════════════════════════════════════════════
   Midnight Editorial — DOCX to Markdown Converter
   Deep dark surfaces, warm amber accents, layered depth
   ═══════════════════════════════════════════════════════════ */

QMainWindow {
    background-color: #0f1117;
}

/* ── Toolbar ─────────────────────────────────────────────── */

QToolBar {
    background-color: #161920;
    border-bottom: 1px solid #232733;
    padding: 6px 10px;
    spacing: 8px;
}

QToolBar::separator {
    width: 1px;
    background-color: #2a2e3a;
    margin: 4px 6px;
}

QToolBar QToolButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 7px 16px;
    font-size: 13px;
    color: #c4c7d4;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
}

QToolBar QToolButton:hover {
    background-color: #1e2230;
    border-color: #2a2e3a;
    color: #e2a84b;
}

QToolBar QToolButton:pressed {
    background-color: #252a38;
    color: #f0c060;
}

QToolBar QToolButton:disabled {
    color: #3a3e4a;
}

/* ── Status Bar ──────────────────────────────────────────── */

QStatusBar {
    background-color: #12141b;
    border-top: 1px solid #1e2230;
    font-size: 12px;
    color: #6b6f80;
    padding: 2px 8px;
}

QStatusBar::item {
    border: none;
}

/* ── Tab Widget ──────────────────────────────────────────── */

QTabWidget::pane {
    border: 1px solid #232733;
    background-color: #13151c;
    border-radius: 0px;
    border-bottom-left-radius: 6px;
    border-bottom-right-radius: 6px;
    border-top: none;
    margin-top: -1px;
}

QTabBar::tab {
    background-color: #161920;
    border: 1px solid #232733;
    border-bottom: none;
    padding: 9px 22px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: 13px;
    color: #6b6f80;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
}

QTabBar::tab:selected {
    background-color: #13151c;
    color: #e2a84b;
    font-weight: bold;
    border-bottom: 2px solid #e2a84b;
}

QTabBar::tab:hover:!selected {
    background-color: #1a1e28;
    color: #9b9fb0;
}

/* ── Primary Button (Convert) ────────────────────────────── */

QPushButton#convertButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #c48a2a, stop:1 #e2a84b);
    color: #0f1117;
    border: none;
    border-radius: 8px;
    padding: 11px 24px;
    font-size: 14px;
    font-weight: bold;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
}

QPushButton#convertButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #d49a3a, stop:1 #f0c060);
}

QPushButton#convertButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #a07020, stop:1 #c48a2a);
}

QPushButton#convertButton:disabled {
    background: #2a2e3a;
    color: #4a4e5a;
}

/* ── Secondary Button (Clear) ────────────────────────────── */

QPushButton#clearButton {
    background-color: transparent;
    border: 1px solid #2a2e3a;
    border-radius: 6px;
    padding: 9px 18px;
    font-size: 13px;
    color: #6b6f80;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
}

QPushButton#clearButton:hover {
    border-color: #d45858;
    color: #d45858;
    background-color: rgba(212, 88, 88, 0.06);
}

QPushButton#clearButton:pressed {
    background-color: rgba(212, 88, 88, 0.12);
}

/* ── File Info Labels ────────────────────────────────────── */

QLabel#fileInfoLabel {
    color: #565a6a;
    font-size: 12px;
    padding: 2px 0;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}

QLabel#fileNameLabel {
    color: #e8eaf0;
    font-size: 15px;
    font-weight: bold;
    padding: 4px 0;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
}

/* ── Progress Bar ────────────────────────────────────────── */

QProgressBar {
    border: 1px solid #232733;
    border-radius: 4px;
    background-color: #1a1e28;
    text-align: center;
    height: 6px;
    color: transparent;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #c48a2a, stop:1 #e2a84b);
    border-radius: 3px;
}

/* ── Radio Buttons (Format Toggle) ───────────────────────── */

QRadioButton {
    spacing: 6px;
    font-size: 13px;
    color: #8b8fa3;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
}

QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 2px solid #3a3e4a;
    background-color: #13151c;
}

QRadioButton::indicator:checked {
    border-color: #e2a84b;
    background-color: #e2a84b;
}

QRadioButton::indicator:hover {
    border-color: #6b6f80;
}

/* ── File List ───────────────────────────────────────────── */

QListWidget {
    background-color: #13151c;
    border: 1px solid #232733;
    border-radius: 6px;
    font-size: 12px;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    outline: none;
}

QListWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #1e2230;
}

QListWidget::item:selected {
    background-color: #1e2230;
    color: #e2a84b;
}

QListWidget::item:hover:!selected {
    background-color: #161920;
}

/* ── Drop Zone ───────────────────────────────────────────── */

QLabel#dropZoneLabel {
    font-size: 14px;
    color: #565a6a;
    padding: 48px 20px;
    border: 2px dashed #2a2e3a;
    border-radius: 12px;
    background-color: #161920;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
}

/* ── PDF Page Separator ──────────────────────────────────── */

QLabel#pdfPageSeparator {
    color: #565a6a;
    font-size: 11px;
    padding: 4px 0;
}

/* ── Format Section Header ───────────────────────────────── */

QLabel#formatSectionLabel {
    color: #565a6a;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
    padding: 0;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}
"""

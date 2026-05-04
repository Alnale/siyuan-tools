# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

思源笔记工具集 — a toolkit for [SiYuan Notes](https://b3log.org/siyuan/) with two independent parts:

- **Node.js CLI** (`import.js`, `crawler.js`): Markdown/text import and web crawling via SiYuan's HTTP API
- **Python GUI** (`converter/`): PySide6 desktop app for DOC/DOCX/PDF → Markdown conversion with SiYuan integration

Both parts share `config.json` for API credentials and text processing settings. All user-facing strings are in Chinese.

## Commands

### Node.js CLI
```bash
npm install                           # Install dependencies (cheerio, turndown)

# Import tool
node import.js notebooks              # List SiYuan notebooks
node import.js file <path> --notebook <ID>
node import.js dir <dir> --path /docs --pipeline pdf-clean
node import.js text "title" "content" --notebook <ID>
node import.js process <file>         # Run text processing only (stdout)
node import.js rules                  # List all text processing rules

# Crawler
node crawler.js targets               # List crawl targets from crawl-targets.json
node crawler.js run                    # Run all enabled targets
node crawler.js url <URL> --selector "article"
node crawler.js feed <RSS-URL>        # Fetch RSS/Atom feed
node crawler.js schedule              # Start cron-based crawl daemon
```

### Python GUI
```bash
cd converter
pip install -r requirements.txt       # PySide6, PyMuPDF, pywin32, etc.
python main.py                        # Launch GUI
```

## Architecture

### Node.js Layer

- **`utils.js`** — Shared utilities: `fixGitBashPath()` (fixes Git Bash `/`-path mangling on Windows) and `parseArgs()` (CLI argument parser)
- **`import.js`** — Core import tool. Contains `SiYuanClient` (HTTP API wrapper), `TextProcessor` (text transformation engine with priority-ordered rules), `MarkdownParser` (block-level analysis), and import functions (file/dir/text/batch). Exports `{ SiYuanClient, TextProcessor, MarkdownParser, loadConfig, getUser }`
- **`crawler.js`** — Web crawler. Imports from `import.js`. Key classes: `RateLimitedFetcher` (concurrent request throttling), `HtmlExtractor` (cheerio-based content extraction), `MarkdownConverter` (turndown HTML→MD), `FeedParser` (RSS/Atom), `PaginationHandler`, `CrawlPipeline` (orchestrator), `CronMatcher` (lightweight cron). Targets defined in `crawl-targets.json`
- **`config.json`** — Shared config: user API credentials, import defaults, text processing rule toggles, named pipelines (e.g. `pdf-clean`, `web-paste`, `full-clean`), crawler settings

### Python Layer (`converter/`)

- **`core/converter.py`** — `PandocConverter`: subprocess wrapper around Pandoc for DOCX→MD
- **`core/pdf_converter.py`** — `PdfConverter`: PyMuPDF-based PDF→Markdown with image extraction
- **`core/doc_to_pdf.py`** — `DocToPdfConverter`: DOC/DOCX→PDF via Microsoft Word COM (pywin32)
- **`core/siyuan_client.py`** — `SiYuanClient`: Python mirror of the Node.js API client, plus `upload_assets_from_markdown()` for image re-uploading
- **`core/siyuan_config.py`** — Reads SiYuan config from `../config.json`
- **`core/siyuan_worker.py`** — QThread workers for async SiYuan import
- **`core/worker.py`** — QThread workers: `ConversionWorker`, `BatchWorker`, `PdfBatchWorker`
- **`core/temp_manager.py`** — Temp file lifecycle management
- **`gui/main_window.py`** — Main window: file list (left), preview panel (right), drag-drop support, batch conversion, SiYuan import integration
- **`gui/preview_panel.py`** — Tabbed preview: rendered HTML, raw Markdown editor, PDF viewer
- **`gui/drop_zone.py`** — Drag-and-drop file input widget
- **`gui/import_dialog.py`** — Dialog for selecting files from timestamped output folders to import into SiYuan
- **`gui/styles.py`** — Dark theme stylesheet (QSS)
- **`gui/markdown_highlighter.py`** — Syntax highlighting for the raw editor

### Text Processing Pipeline

The `TextProcessor` in `import.js` is the shared text transformation engine. Rules are registered with an ID, priority, category, and toggle function. Rules execute in priority order. Named pipelines in `config.json` select subsets of rules:

- `pdf-clean` — Clean PDF copy artifacts (newlines, spaces)
- `web-paste` — Clean web-pasted content (superscripts, links, HTML)
- `formula` — LaTeX formula conversion only
- `full-clean` — All cleanup rules combined
- `academic` — Academic paper import (formulas + superscripts + whitespace)
- `web-clean` — Web crawl cleanup (whitespace + formulas + auto-link)

Crawler targets can specify a pipeline via `"pipeline": "web-clean"` in `crawl-targets.json`.

### Conversion Flow (Python GUI)

1. User drops DOC/DOCX/PDF files
2. DOC/DOCX → PDF via Word COM, then PDF → Markdown via PyMuPDF
3. Alternatively, DOCX → Markdown directly via Pandoc
4. PDF → Markdown via PyMuPDF
5. Output saved to `siyuan-tools/output/output_YYYYMMDD_HHMMSS/` with timestamp subfolders
6. Optional: import Markdown (+ images) into SiYuan via API

## Key Conventions

- `config.json` contains API tokens — do not commit real tokens. The committed version uses placeholder values
- `fixGitBashPath()` must be applied to any user-supplied path argument in CLI tools (Git Bash converts `/path` to `C:/Program Files/Git/path`)
- Node.js uses CommonJS (`require`), no build step
- Python requires Microsoft Word + pywin32 for DOC/DOCX→PDF; Pandoc is optional (DOCX only)
- Output directory: `siyuan-tools/output/` with `output_YYYYMMDD_HHMMSS` subfolders

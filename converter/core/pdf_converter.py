import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

import pymupdf
from pymupdf import layout as pymupdf_layout

# Activate the ONNX layout analyzer once at import time
pymupdf_layout.activate()

_LIST_RE = re.compile(
    r"^(\s*)"
    r"(?:"
    r"(\d{1,3}[.)、])"
    r"|(（\d{1,3}）)"
    r"|([•●○◆◇▪▸►‣∙⊙○◦])"
    r"|([-*+])"
    r")\s+"
)

_SENTENCE_END_RE = re.compile(
    r'[。！？…；：）】」』》＞\s]$'
)

# PyMuPDF layout analysis may return "figure" or "picture" for image regions
_IMAGE_LABELS = frozenset({"figure", "picture"})


@dataclass
class LayoutRegion:
    x0: float
    y0: float
    x1: float
    y1: float
    label: str
    heading_level: int = 0  # computed after grouping


def _get_layout_regions(page) -> list[LayoutRegion]:
    """Get AI-detected layout regions for a page."""
    try:
        raw = pymupdf._get_layout(page)
    except ValueError as e:
        logger.debug("布局分析失败: %s", e)
        return []
    regions = []
    for item in raw:
        if len(item) >= 5:
            regions.append(LayoutRegion(
                x0=item[0], y0=item[1],
                x1=item[2], y1=item[3],
                label=item[4],
            ))
    return regions


def _assign_header_levels(page, regions: list[LayoutRegion]) -> list[LayoutRegion]:
    """Assign heading levels to section-headers based on font size."""
    headers = [r for r in regions if r.label == "section-header"]
    if not headers:
        return regions

    # Get font sizes for each header region
    header_sizes: list[tuple[LayoutRegion, float]] = []
    for h in headers:
        rect = pymupdf.Rect(h.x0, h.y0, h.x1, h.y1)
        try:
            blocks = page.get_text("dict", clip=rect, flags=pymupdf.TEXT_PRESERVE_WHITESPACE)["blocks"]
        except ValueError:
            blocks = []
        max_size = 12.0
        for b in blocks:
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    s = span.get("size", 12)
                    if s > max_size:
                        max_size = s
        header_sizes.append((h, max_size))

    # Get unique sizes sorted descending
    unique_sizes = sorted(set(s for _, s in header_sizes), reverse=True)
    size_to_level = {s: i + 1 for i, s in enumerate(unique_sizes[:4])}

    for h, s in header_sizes:
        h.heading_level = size_to_level.get(s, 2)

    return regions


def _extract_region_text(page, region: LayoutRegion, pad: int = 6) -> str:
    """Extract text from a region with natural line breaks preserved."""
    rect = pymupdf.Rect(
        region.x0 - pad, region.y0 - pad,
        region.x1 + pad, region.y1 + pad,
    )
    try:
        blocks = page.get_text("dict", clip=rect, flags=pymupdf.TEXT_PRESERVE_WHITESPACE)["blocks"]
    except ValueError as e:
        logger.debug("提取文本失败: %s", e)
        return ""

    lines = []
    for b in blocks:
        if b.get("type") != 0:
            continue
        for line_data in b.get("lines", []):
            parts = []
            for span in line_data.get("spans", []):
                t = span.get("text", "")
                if t:
                    parts.append(t)
            if parts:
                line_text = "".join(parts).strip()
                if line_text:
                    lines.append(line_text)

    if not lines:
        return ""

    # Merge lines broken mid-Chinese-character or mid-word (no trailing punctuation + no leading space)
    merged = [lines[0]]
    for line in lines[1:]:
        prev = merged[-1]
        # Don't merge if previous line looks like code
        if _is_code_line(prev):
            merged.append(line)
            continue
        # Merge if previous line doesn't end with sentence-ending punctuation
        # AND current line doesn't start with a list marker or number or code pattern
        if (not _SENTENCE_END_RE.search(prev)
            and not _LIST_RE.match(line)
            and not re.match(r'^[\d]', line)
            and not line.startswith('#')
            and not _is_code_line(line)):
            merged[-1] += line
        else:
            merged.append(line)

    return "\n".join(merged).strip()


def _table_to_markdown(table_data) -> str:
    rows = []
    try:
        raw = table_data.extract()
    except ValueError as e:
        logger.debug("提取表格失败: %s", e)
        return ""
    for row in raw:
        cells = [str(c).replace("\n", " ").strip() if c is not None else "" for c in row]
        rows.append(cells)

    if not rows or not rows[0]:
        return ""

    col_count = max(len(r) for r in rows)
    rows = [r + [""] * (col_count - len(r)) for r in rows]

    lines = ["| " + " | ".join(rows[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _rect_overlap_area(r1: tuple, r2: tuple) -> float:
    """Calculate overlap area between two rectangles (x0,y0,x1,y1)."""
    x_overlap = max(0, min(r1[2], r2[2]) - max(r1[0], r2[0]))
    y_overlap = max(0, min(r1[3], r2[3]) - max(r1[1], r2[1]))
    return x_overlap * y_overlap


def _is_in_table(region: LayoutRegion, table_rects: list[tuple]) -> bool:
    """Check if a region overlaps significantly with any table."""
    r = (region.x0, region.y0, region.x1, region.y1)
    area = max(1, (region.x1 - region.x0) * (region.y1 - region.y0))
    for tr in table_rects:
        overlap = _rect_overlap_area(r, tr)
        if overlap / area > 0.5:
            return True
    return False


def _find_page_images(page) -> list[dict]:
    """获取页面嵌入的图片列表。"""
    try:
        raw = page.get_images(full=True)
    except (ValueError, RuntimeError) as e:
        logger.debug("获取图片列表失败: %s", e)
        return []
    images = []
    for item in raw:
        if len(item) >= 4:
            images.append({
                "xref": item[0],
                "width": item[2],
                "height": item[3],
            })
    return images


def _extract_figure_image(
    doc,
    page,
    region: LayoutRegion,
    page_images: list[dict],
    media_dir: str,
    page_idx: int,
    fig_idx: int,
) -> str | None:
    """提取 figure 区域的图片，返回文件名；失败返回 None。"""
    try:
        fig_rect = (region.x0, region.y0, region.x1, region.y1)
        fig_area = max(1, (region.x1 - region.x0) * (region.y1 - region.y0))

        # 优先：匹配嵌入图片
        best_xref = None
        best_overlap = 0.0
        for img in page_images:
            try:
                rects = page.get_image_rects(img["xref"])
            except (ValueError, RuntimeError):
                continue
            for rect in rects:
                img_rect = (rect.x0, rect.y0, rect.x1, rect.y1)
                overlap = _rect_overlap_area(fig_rect, img_rect)
                ratio = overlap / fig_area
                if ratio > best_overlap:
                    best_overlap = ratio
                    best_xref = img["xref"]

        if best_xref is not None and best_overlap >= 0.3:
            img_data = doc.extract_image(best_xref)
            if img_data and img_data.get("image"):
                ext = img_data.get("ext", "png")
                filename = f"page{page_idx}_fig{fig_idx}.{ext}"
                filepath = os.path.join(media_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(img_data["image"])
                return filename

        # 降级：截取区域为 PNG（高精度渲染）
        pad = 2
        rect = pymupdf.Rect(
            region.x0 - pad, region.y0 - pad,
            region.x1 + pad, region.y1 + pad,
        )
        pixmap = page.get_pixmap(clip=rect, dpi=300)
        filename = f"page{page_idx}_fig{fig_idx}.png"
        filepath = os.path.join(media_dir, filename)
        pixmap.save(filepath)
        return filename

    except (ValueError, RuntimeError, OSError) as e:
        logger.debug("保存图片失败: %s", e)
        return None


def _find_figure_caption(
    figure_region: LayoutRegion,
    all_regions: list[LayoutRegion],
    page,
    region_idx: int,
) -> tuple[str | None, int | None]:
    """查找 figure 下方的图注文字。返回 (图注文字, 被消费区域索引)。"""
    if region_idx + 1 >= len(all_regions):
        return None, None

    next_region = all_regions[region_idx + 1]
    if next_region.label != "text":
        return None, None

    # 垂直间距检查
    if next_region.y0 < figure_region.y1 - 5 or next_region.y0 > figure_region.y1 + 30:
        return None, None

    # 水平重叠检查
    x_overlap = max(0, min(figure_region.x1, next_region.x1) - max(figure_region.x0, next_region.x0))
    fig_width = max(1, figure_region.x1 - figure_region.x0)
    if x_overlap / fig_width < 0.5:
        return None, None

    caption = _extract_region_text(page, next_region)
    if caption:
        return caption, region_idx + 1
    return None, None


def _merge_adjacent_text(texts: list[str]) -> list[str]:
    """Merge adjacent text blocks that belong to the same paragraph."""
    merged = []
    buffer = ""

    def flush():
        nonlocal buffer
        if buffer.strip():
            merged.append(buffer.strip())
        buffer = ""

    for text in texts:
        text = text.strip()
        if not text:
            flush()
            continue

        if _LIST_RE.match(text):
            flush()
            m = _LIST_RE.match(text)
            content = text[m.end():]
            if m.group(2) or m.group(3):
                merged.append(f"1. {content}")
            else:
                merged.append(f"- {content}")
            continue

        if buffer:
            if _SENTENCE_END_RE.search(buffer):
                flush()
                buffer = text
            else:
                buffer += text
        else:
            buffer = text

    flush()
    return merged


def _is_code_line(line: str) -> bool:
    """Check if a single line looks like C/C++ code."""
    stripped = line.strip()
    if not stripped:
        return False
    # Preprocessor directives
    if re.match(r'^\s*#\s*(include|define|ifdef|ifndef|endif|pragma|if|else|elif|undef)\b', stripped):
        return True
    # Type/keyword declarations
    if re.match(r'^\s*(void|int|char|float|double|struct|enum|union|typedef|static|const|extern|unsigned|long|short|signed|register|volatile)\b', stripped):
        return True
    # Control flow
    if re.match(r'^\s*(if|else|for|while|do|switch|case|default|return|break|continue|goto)\b', stripped):
        return True
    # Braces alone on a line
    if re.match(r'^\s*[{}]\s*$', stripped):
        return True
    # Lines ending with semicolon (strong code indicator)
    if stripped.endswith(';') and len(stripped) > 3:
        return True
    # Lines ending with comma (enum/array/initializer continuation)
    if re.match(r'^\s*\w+.*,\s*$', stripped) and not re.search(r'[一-鿿]', stripped):
        return True
    # Closing brace with optional punctuation
    if re.match(r'^\s*}\s*[;,]?\s*$', stripped):
        return True
    # Function call / printf / scanf
    if re.match(r'^\s*(printf|scanf|malloc|free|sleep|getch|exit|main)\s*\(', stripped):
        return True
    # Pointer operations
    if re.match(r'^\s*\w+\s*->\s*\w+', stripped):
        return True
    # Lines that are purely code tokens with at least one code-specific character — no Chinese
    if (re.match(r'^[\s\w{}()\[\];,.<>!=&|+\-*/%^~?:\'"\\]+$', stripped)
            and len(stripped) > 2
            and re.search(r'[{}();,\[\]]', stripped)):
        return True
    return False


_CODE_FENCE_RE = re.compile(r'^\s*```')


def _wrap_code_block(text: str) -> str:
    """If the text looks like C code, wrap it in a fenced code block.
    Finds the start of code by scanning for a run of code-like lines,
    then uses brace-depth tracking to include continuation lines."""
    lines = text.split("\n")
    non_empty = [(i, l) for i, l in enumerate(lines) if l.strip()]
    if len(non_empty) < 3:
        return text

    # Check if enough lines look like code
    code_count = sum(1 for _, l in non_empty if _is_code_line(l))
    if code_count / len(non_empty) < 0.3:
        return text

    # Find code start: first line that is code-like
    code_start = 0
    for i, line in enumerate(lines):
        if _is_code_line(line):
            code_start = i
            break

    # From code_start, collect lines using brace-depth tracking
    result_lines = []
    brace_depth = 0
    seen_opening_brace = False  # whether we've seen a { in this block
    for line in lines[code_start:]:
        stripped = line.strip()
        if not stripped:
            result_lines.append(line)
            continue
        if brace_depth > 0:
            brace_depth += stripped.count('{') - stripped.count('}')
            result_lines.append(line)
        elif _is_code_line(line):
            result_lines.append(line)
            delta = stripped.count('{') - stripped.count('}')
            brace_depth = max(0, brace_depth + delta)
            if '{' in stripped:
                seen_opening_brace = True
            # A closing brace at depth 0 that opens no brace is a continuation
            # from a previous page's code. Include following non-code lines
            # until we find a real code boundary.
            if brace_depth == 0 and stripped == '}' and not seen_opening_brace:
                brace_depth = 1  # treat as still inside code
        else:
            break

    if len([l for l in result_lines if l.strip()]) < 3:
        return text

    return "```c\n" + "\n".join(result_lines).strip() + "\n```"


def _merge_paragraphs_raw(parts: list[str]) -> list[str]:
    """Merge consecutive text blocks into paragraphs, preserving headings, lists, and code blocks.
    Returns groups where consecutive list items are joined by single newlines."""
    merged: list[str] = []
    buffer = ""
    list_buffer: list[str] = []

    def flush_text():
        nonlocal buffer
        if buffer.strip():
            merged.append(buffer.strip())
        buffer = ""

    def flush_list():
        nonlocal list_buffer
        if list_buffer:
            merged.append("\n".join(list_buffer))
            list_buffer = []

    for part in parts:
        is_heading = part.startswith("#")
        is_list = bool(_LIST_RE.match(part)) or part.startswith("1. ") or part.startswith("- ")
        is_code = _CODE_FENCE_RE.match(part)

        if is_heading or is_code:
            flush_text()
            flush_list()
            merged.append(part)
            continue

        if is_list:
            flush_text()
            list_buffer.append(part)
            continue

        # Regular text block
        flush_list()
        # Keep each text block as its own paragraph (don't merge across regions)
        if buffer:
            flush_text()
        buffer = part

    flush_text()
    flush_list()
    return merged


# 匹配页面分隔符：--- 后跟 <!-- 第 N 页 -->
_PAGE_SEP_RE = re.compile(r'\n*---\s*\n+<!--\s*第\s*\d+\s*页\s*-->\s*\n*')


def _merge_cross_page_code(md: str) -> str:
    """合并被页面分隔符隔开的连续 ```c 代码块。"""
    # 分割出所有代码块和间隔
    parts = re.split(r'(```[^\n]*\n.*?```)', md, flags=re.DOTALL)
    if len(parts) < 3:
        return md

    result = [parts[0]]
    i = 1
    while i < len(parts):
        part = parts[i]
        # 代码块可能前导空白（因为 re.split 保留了间隔中的尾部空白）
        stripped_part = part.lstrip()
        if stripped_part.startswith('```'):
            code_block = stripped_part
            leading = part[:len(part) - len(stripped_part)]
            if leading:
                result.append(leading)
            # 提取代码块的语言标签
            lang_match = re.match(r'```([^\n]*)\n', code_block)
            lang = lang_match.group(1).strip() if lang_match else ''
            code_content = code_block[len(lang_match.group(0)):-3]
            # 循环合并：持续检查后续 gap+code 是否可合并
            j = i + 1
            while j + 1 < len(parts):
                gap = parts[j]
                stripped_gap = gap.strip()
                if stripped_gap == '' or _PAGE_SEP_RE.fullmatch('\n' + stripped_gap + '\n'):
                    next_part = parts[j + 1].lstrip()
                    if next_part.startswith('```'):
                        next_block = next_part
                        next_lang_match = re.match(r'```([^\n]*)\n', next_block)
                        next_lang = next_lang_match.group(1).strip() if next_lang_match else ''
                        if lang == next_lang:
                            next_content = next_block[len(next_lang_match.group(0)):-3]
                            code_content = code_content + '\n' + next_content
                            j += 2  # 跳过 gap 和已合并的代码块
                            continue
                    # gap 是空的或页面分隔符，但下一个不是代码块——跳过 gap 继续检查
                    j += 1
                    continue
                break
            merged_block = f'```{lang}\n{code_content}\n```'
            result.append(merged_block)
            i = j  # 跳过所有已合并的部分
        else:
            result.append(part)
            i += 1

    return ''.join(result)


class PdfConverter:
    _initialized = False

    def convert(
        self,
        input_path: str,
        extract_media_dir: str | None = None,
    ) -> tuple[str, str]:
        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")

        # 未指定媒体目录时自动生成（延迟创建，有图片时才 mkdir）
        if not extract_media_dir:
            input_stem = os.path.splitext(os.path.basename(input_path))[0]
            input_dir = os.path.dirname(input_path)
            extract_media_dir = os.path.join(input_dir, f"{input_stem}_media")

        all_sections: list[str] = []
        doc = pymupdf.open(input_path)

        try:
            for i, page in enumerate(doc):
                page_parts: list[str] = []

                # Step 1: Detect tables first
                table_rects = []
                try:
                    table_finder = page.find_tables()
                except ValueError:
                    table_finder = None
                if table_finder and table_finder.tables:
                    for table in table_finder.tables:
                        md = _table_to_markdown(table)
                        if md.strip():
                            page_parts.append(md)
                        try:
                            bbox = table.bbox
                            table_rects.append(bbox)
                        except (ValueError, RuntimeError):
                            # 跳过无法获取 bbox 的表格（如空表格）
                            pass

                # Step 2: Get AI layout regions
                regions = _get_layout_regions(page)
                if not regions:
                    # Fallback: plain text extraction
                    text = page.get_text("text").strip()
                    if text:
                        page_parts.append(text)
                    if page_parts:
                        if i > 0:
                            all_sections.append(f"\n\n---\n\n<!-- 第 {i + 1} 页 -->\n")
                        all_sections.append("\n\n".join(page_parts))
                    continue

                regions = _assign_header_levels(page, regions)
                regions.sort(key=lambda r: (r.y0, r.x0))

                # 预扫描：是否有图片区域需要提取
                has_figures = any(r.label in _IMAGE_LABELS for r in regions)
                page_images = _find_page_images(page)
                if has_figures or page_images:
                    os.makedirs(extract_media_dir, exist_ok=True)

                figure_counter = 0

                # 收集布局区域已覆盖的图片 rect，用于排除重复
                covered_rects = []
                for r in regions:
                    if r.label in _IMAGE_LABELS:
                        covered_rects.append((r.x0, r.y0, r.x1, r.y1))

                # 收集未被布局区域覆盖的嵌入图片（如 LOGO、校徽等）
                extra_images: list[tuple[float, str, int]] = []  # (y0, filename, fig_num)
                if page_images:
                    for img in page_images:
                        try:
                            rects = page.get_image_rects(img["xref"])
                        except (ValueError, RuntimeError):
                            continue
                        for rect in rects:
                            img_rect = (rect.x0, rect.y0, rect.x1, rect.y1)
                            img_area = max(1, (rect.x1 - rect.x0) * (rect.y1 - rect.y0))
                            already_covered = False
                            for cr in covered_rects:
                                overlap = _rect_overlap_area(img_rect, cr)
                                if overlap / img_area > 0.5:
                                    already_covered = True
                                    break
                            if already_covered:
                                continue
                            try:
                                img_data = doc.extract_image(img["xref"])
                                if img_data and img_data.get("image"):
                                    ext = img_data.get("ext", "png")
                                    filename = f"page{i}_fig{figure_counter}.{ext}"
                                    filepath = os.path.join(extract_media_dir, filename)
                                    with open(filepath, "wb") as f:
                                        f.write(img_data["image"])
                                    extra_images.append((rect.y0, filename, figure_counter))
                                    figure_counter += 1
                            except (ValueError, RuntimeError, OSError) as e:
                                logger.debug("补充提取图片失败: %s", e)

                # Step 3: Extract text from each region，按 y 坐标合并布局区域和补充图片
                raw_parts: list[tuple[str, str]] = []  # (label, text)
                consumed_indices: set[int] = set()
                extra_idx = 0  # 当前待插入的补充图片索引
                for region_idx, region in enumerate(regions):
                    if region_idx in consumed_indices:
                        continue
                    if region.label == "page-footer":
                        continue
                    if _is_in_table(region, table_rects):
                        continue

                    # 在当前区域之前插入 y 坐标更小的补充图片
                    while extra_idx < len(extra_images) and extra_images[extra_idx][0] < region.y0:
                        _, fn, fig_num = extra_images[extra_idx]
                        raw_parts.append(("figure", f"![图 {i + 1}-{fig_num + 1}]({fn})"))
                        extra_idx += 1

                    # 图片区域处理
                    if region.label in _IMAGE_LABELS:
                        img_filename = _extract_figure_image(
                            doc, page, region, page_images,
                            extract_media_dir, i, figure_counter,
                        )
                        caption, cap_idx = _find_figure_caption(
                            region, regions, page, region_idx,
                        )
                        if cap_idx is not None:
                            consumed_indices.add(cap_idx)
                        # 图片区域内也可能包含文字（如封面页学生信息）
                        region_text = _extract_region_text(page, region)
                        if img_filename:
                            alt_text = caption or region_text or f"图 {i + 1}-{figure_counter + 1}"
                            if len(alt_text) > 80:
                                alt_text = alt_text[:80] + "…"
                            raw_parts.append(("figure", f"![{alt_text}]({img_filename})"))
                        elif caption:
                            raw_parts.append(("text", caption))
                        if region_text:
                            raw_parts.append(("text", region_text))
                        figure_counter += 1
                        continue

                    region_text = _extract_region_text(page, region)
                    if not region_text:
                        continue
                    raw_parts.append((region.label, region_text))

                # 追加剩余的补充图片（y 坐标大于所有布局区域）
                while extra_idx < len(extra_images):
                    _, fn, fig_num = extra_images[extra_idx]
                    raw_parts.append(("figure", f"![图 {i + 1}-{fig_num + 1}]({fn})"))
                    extra_idx += 1

                # Step 4: Convert to markdown
                text_parts = []
                for idx, (label, text) in enumerate(raw_parts):
                    if label == "section-header":
                        # Determine heading level from the region
                        level = 2
                        for r in regions:
                            if r.label == "section-header" and _extract_region_text(page, r) == text:
                                level = r.heading_level or 2
                                break
                        text_parts.append(f"{'#' * level} {text}")
                    elif label == "list-item":
                        # Check if this is just a bare marker (e.g. "1." or "•")
                        stripped = text.strip()
                        is_bare_marker = bool(re.match(r'^[\d]{1,3}[.)、]\s*$', stripped))
                        is_bare_bullet = bool(re.match(r'^[•●○◆◇▪▸►‣∙⊙○◦]\s*$', stripped))

                        if is_bare_marker or is_bare_bullet:
                            # Merge with next region as its content
                            continue

                        # Check if previous region was a bare marker
                        prev_was_marker = False
                        if idx > 0:
                            prev_label, prev_text = raw_parts[idx - 1]
                            prev_stripped = prev_text.strip()
                            if prev_label == "list-item" and (
                                re.match(r'^[\d]{1,3}[.)、]\s*$', prev_stripped)
                                or re.match(r'^[•●○◆◇▪▸►‣∙⊙○◦]\s*$', prev_stripped)
                            ):
                                prev_was_marker = True
                                # Use numbered format
                                m = re.match(r'^[\d]+[.)、]', prev_stripped)
                                if m:
                                    text_parts.append(f"1. {text}")
                                else:
                                    text_parts.append(f"- {text}")
                                continue

                        # Regular list item
                        lines = text.split("\n")
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            m = _LIST_RE.match(line)
                            if m:
                                content = line[m.end():]
                                if m.group(2) or m.group(3):
                                    text_parts.append(f"1. {content}")
                                else:
                                    text_parts.append(f"- {content}")
                            else:
                                text_parts.append(f"- {line}")
                    elif label in ("text", "equation"):
                        text_parts.append(_wrap_code_block(text))
                    elif label in _IMAGE_LABELS:
                        text_parts.append(text)  # 已是 ![alt](path) 格式
                    # page-header → skip

                if text_parts:
                    merged = _merge_paragraphs_raw(text_parts)
                    page_parts.append("\n\n".join(merged))

                if page_parts:
                    if i > 0:
                        all_sections.append(f"\n\n---\n\n<!-- 第 {i + 1} 页 -->\n")
                    all_sections.append("\n\n".join(page_parts))
        finally:
            doc.close()

        return _merge_cross_page_code("\n\n".join(all_sections)), extract_media_dir

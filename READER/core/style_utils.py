import copy
import logging
from typing import Optional, List, Any, Union

LOGGER = logging.getLogger('READER.style_utils')

HAS_TEXT_ENGINE = False
try:
    from ballontranslator.utils.textblock import TextBlock
    from ballontranslator.utils.fontformat import FontFormat
    from ballontranslator.ui.text_engine.annotations import to_rich_text_html
    from ballontranslator.ui.text_engine.pipeline_formatting import _load_text_block_document
    HAS_TEXT_ENGINE = True
except ImportError:
    TextBlock = None
    FontFormat = None
    to_rich_text_html = None
    _load_text_block_document = None


def get_reference_fontformat(
    current_page: Optional[Any] = None,
    project_data: Optional[Any] = None,
) -> Optional[Any]:
    """Find the best reference FontFormat from current page, wider project, or BallonsTranslator global config.
    
    Prefers blocks with custom stroke width, non-black stroke color, centered alignment,
    or rich text effects.
    """
    candidates = []

    # 1. Inspect current page blocks
    if current_page and getattr(current_page, 'blocks', None):
        for blk in reversed(current_page.blocks):
            fmt = getattr(blk, 'fontformat', None)
            if fmt is None and isinstance(blk, dict):
                fmt = blk.get('fontformat')
            if fmt:
                candidates.append((fmt, _rate_fontformat_quality(fmt, blk)))

    # 2. Inspect blocks across other pages if current page doesn't have a high quality format
    best_current_score = max([score for _, score in candidates], default=-1)
    if best_current_score < 10 and project_data and getattr(project_data, 'pages', None):
        for page in project_data.pages:
            if page is current_page:
                continue
            for blk in getattr(page, 'blocks', []) or []:
                fmt = getattr(blk, 'fontformat', None)
                if fmt is None and isinstance(blk, dict):
                    fmt = blk.get('fontformat')
                if fmt:
                    candidates.append((fmt, _rate_fontformat_quality(fmt, blk)))
                    if candidates[-1][1] >= 10:
                        break
            if any(score >= 10 for _, score in candidates):
                break

    if candidates:
        # Pick the highest rated candidate
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    # 3. Fallback to BallonsTranslator global config
    try:
        from ballontranslator.utils.config import pcfg
        if pcfg and hasattr(pcfg, 'global_fontformat') and pcfg.global_fontformat:
            return pcfg.global_fontformat
    except Exception as e:
        LOGGER.debug(f"Could not load global_fontformat: {e}")

    # 4. Built-in default fallback for manga speech bubbles
    if FontFormat is not None:
        default_fmt = FontFormat()
        default_fmt.alignment = 1  # Center alignment
        default_fmt.font_size = 24.0
        default_fmt.font_family = "Microsoft YaHei UI"
        default_fmt.stroke_width = 0.6
        default_fmt.srgb = [255, 255, 255]  # White stroke outline
        default_fmt.frgb = [0, 0, 0]        # Black text
        return default_fmt

    return None


def _rate_fontformat_quality(fmt: Any, blk: Any = None) -> int:
    """Score how well-formed and manga-styled a fontformat is."""
    score = 0
    if not fmt:
        return score

    # Check stroke width
    sw = getattr(fmt, 'stroke_width', 0.0) if not isinstance(fmt, dict) else fmt.get('stroke_width', 0.0)
    if sw and float(sw) > 0.1:
        score += 5

    # Check stroke color (distinct from text color)
    srgb = getattr(fmt, 'srgb', None) if not isinstance(fmt, dict) else fmt.get('srgb')
    frgb = getattr(fmt, 'frgb', None) if not isinstance(fmt, dict) else fmt.get('frgb')
    if srgb and frgb and srgb != frgb:
        score += 3

    # Check alignment (manga speech bubbles are center-aligned = 1)
    align = getattr(fmt, 'alignment', 0) if not isinstance(fmt, dict) else fmt.get('alignment', 0)
    if align == 1:
        score += 2

    # Check font family
    ff = getattr(fmt, 'font_family', '') if not isinstance(fmt, dict) else fmt.get('font_family', '')
    if ff and ff not in ('SimHei', 'sans-serif', 'Arial', ''):
        score += 3

    # Check text effects stack
    effects = getattr(fmt, 'text_effects', None) if not isinstance(fmt, dict) else fmt.get('text_effects')
    if effects:
        score += 3

    # Check if block has rich text
    if blk:
        rt = getattr(blk, 'rich_text', '') if not isinstance(blk, dict) else blk.get('rich_text', '')
        if rt:
            score += 4

    return score


def copy_fontformat(src: Any) -> Any:
    """Safely deep-copy or clone a FontFormat or format dict."""
    if src is None:
        return None
    if hasattr(src, 'deepcopy'):
        try:
            return src.deepcopy()
        except Exception:
            pass
    if hasattr(src, 'to_dict') and FontFormat is not None:
        try:
            return FontFormat(**src.to_dict())
        except Exception:
            pass
    return copy.deepcopy(src)


def apply_fontformat_to_block(
    block: Any,
    ref_format: Any,
    generate_rich_text: bool = True,
    preserve_size: bool = False,
) -> None:
    """Apply styling from ref_format onto a target TextBlock or block dict."""
    if block is None or ref_format is None:
        return

    # If block is a TextBlock instance
    if TextBlock and isinstance(block, TextBlock):
        target_fmt = block.fontformat
        existing_size = target_fmt.font_size if preserve_size else None

        if hasattr(ref_format, 'deepcopy'):
            block.fontformat = ref_format.deepcopy()
        elif hasattr(ref_format, 'to_dict'):
            block.fontformat = FontFormat(**ref_format.to_dict())
        elif isinstance(ref_format, dict):
            for k, v in ref_format.items():
                if hasattr(target_fmt, k):
                    try:
                        setattr(target_fmt, k, copy.deepcopy(v))
                    except Exception:
                        pass
        else:
            # Attribute-by-attribute copy
            for attr in (
                'font_family', 'stroke_width', 'srgb', 'frgb', 'underline',
                'italic', 'alignment', 'vertical', 'standard_vertical_roman_alignment',
                'font_weight', 'line_spacing', 'letter_spacing', 'text_effects',
                'text_transform', 'opacity', 'shadow_radius', 'shadow_strength',
                'shadow_color', 'shadow_offset'
            ):
                if hasattr(ref_format, attr) and hasattr(target_fmt, attr):
                    setattr(target_fmt, attr, copy.deepcopy(getattr(ref_format, attr)))

        if preserve_size and existing_size and existing_size > 0:
            block.fontformat.font_size = existing_size

        if generate_rich_text and (block.translation or block.text):
            generate_block_rich_text(block)

    elif isinstance(block, dict):
        ref_dict = ref_format if isinstance(ref_format, dict) else (
            ref_format.to_dict() if hasattr(ref_format, 'to_dict') else {}
        )
        if not ref_dict and hasattr(ref_format, '__dict__'):
            ref_dict = copy.deepcopy(ref_format.__dict__)

        existing_size = block.get('fontformat', {}).get('font_size') if preserve_size else None
        new_fmt = copy.deepcopy(ref_dict)
        if preserve_size and existing_size and existing_size > 0:
            new_fmt['font_size'] = existing_size
        block['fontformat'] = new_fmt

        if generate_rich_text and (block.get('translation') or block.get('text')):
            generate_block_rich_text(block)


def generate_block_rich_text(block: Any) -> str:
    """Construct full HTML rich text from a block's translation/text and fontformat.
    
    Matches BallonsTranslator pipeline_formatting and annotations output.
    """
    if block is None:
        return ""

    if TextBlock and isinstance(block, TextBlock) and _load_text_block_document and to_rich_text_html:
        try:
            # Temporarily clear rich_text to force document rebuild from fontformat & plain text
            old_rt = getattr(block, 'rich_text', '')
            block.rich_text = ""
            doc = _load_text_block_document(block)
            html = to_rich_text_html(
                doc,
                line_spacing_fallback=block.fontformat.line_spacing,
                line_spacing_type_fallback=block.fontformat.line_spacing_type,
            )
            block.rich_text = html
            return html
        except Exception as e:
            LOGGER.debug(f"Failed to generate rich text: {e}")
            if 'old_rt' in locals():
                block.rich_text = old_rt

    # Fallback minimal HTML generator for dict blocks or when text engine is unavailable
    text = ""
    font_family = "Microsoft YaHei UI"
    font_size = 24.0
    italic = False
    bold = False
    frgb = (0, 0, 0)
    line_height = 1.2
    letter_spacing = 1.15

    if isinstance(block, dict):
        text = block.get('translation') or "\n".join(block.get('text', []))
        fmt = block.get('fontformat', {})
        font_family = fmt.get('font_family', font_family)
        font_size = fmt.get('font_size', font_size)
        italic = fmt.get('italic', italic)
        fw = fmt.get('font_weight', 400)
        bold = fw >= 600 if isinstance(fw, (int, float)) else False
        frgb = fmt.get('frgb', frgb)
        line_height = fmt.get('line_spacing', line_height)
        letter_spacing = fmt.get('letter_spacing', letter_spacing)
    elif hasattr(block, 'translation'):
        text = block.translation or "\n".join(block.text or [])
        fmt = getattr(block, 'fontformat', None)
        if fmt:
            font_family = getattr(fmt, 'font_family', font_family)
            font_size = getattr(fmt, 'font_size', font_size)
            italic = getattr(fmt, 'italic', italic)
            fw = getattr(fmt, 'font_weight', 400)
            bold = fw >= 600 if isinstance(fw, (int, float)) else False
            frgb = getattr(fmt, 'frgb', frgb)
            line_height = getattr(fmt, 'line_spacing', line_height)
            letter_spacing = getattr(fmt, 'letter_spacing', letter_spacing)

    if not text:
        return ""

    hex_color = f"#{int(frgb[0]):02x}{int(frgb[1]):02x}{int(frgb[2]):02x}" if len(frgb) >= 3 else "#000000"
    lines = text.split('\n')
    paragraphs = []
    for line in lines:
        p_style = f"margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; line-height: {line_height}; text-align: center;"
        span_style = f"color:{hex_color};"
        if italic:
            span_style += " font-style:italic;"
        if bold:
            span_style += " font-weight:bold;"
        span_style += f" letter-spacing: {letter_spacing - 1.0:.2f}em;"
        paragraphs.append(f'<p style="{p_style}"><span style="{span_style}">{line}</span></p>')

    body_content = "".join(paragraphs)
    html = (
        f'<!DOCTYPE html><html><head><meta name="qrichtext" content="1" /><meta charset="utf-8" />'
        f'<style type="text/css">p, li {{ white-space: pre-wrap; }}</style></head>'
        f'<body style=" font-family:\'{font_family}\'; font-size:{font_size*0.75:.1f}pt; font-weight:{"bold" if bold else "400"}; font-style:{"italic" if italic else "normal"};">'
        f'{body_content}</body></html>'
    )

    if isinstance(block, dict):
        block['rich_text'] = html
    elif hasattr(block, 'rich_text'):
        block.rich_text = html

    return html


def sync_page_blocks_style(
    page: Any,
    target_indices: Optional[List[int]] = None,
    ref_format: Optional[Any] = None,
    project_data: Optional[Any] = None,
) -> int:
    """Apply reference font formatting across specified or all text blocks on a page.
    
    Returns the number of blocks modified.
    """
    if not page or not getattr(page, 'blocks', None):
        return 0

    if ref_format is None:
        ref_format = get_reference_fontformat(current_page=page, project_data=project_data)

    if ref_format is None:
        return 0

    indices = target_indices if target_indices is not None else list(range(len(page.blocks)))
    count = 0
    for idx in indices:
        if 0 <= idx < len(page.blocks):
            blk = page.blocks[idx]
            apply_fontformat_to_block(blk, ref_format, generate_rich_text=True, preserve_size=True)
            count += 1

    return count

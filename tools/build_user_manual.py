"""Build docs/RoseSI-User-Manual.docx from curated user-facing content."""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SHOTS = DOCS / "screenshots"
OUT = DOCS / "RoseSI-User-Manual.docx"
COVER = DOCS / "manual_cover.png"

ROSE = "B23A5B"
ROSE_DARK = "6E233B"
ROSE_LIGHT = "FFF3F7"
INK = "2B2028"
MUTED = "6F5B67"
BORDER = "E8CAD5"
FONT = "Microsoft YaHei"
FONT_BOLD = "Microsoft YaHei"
LATIN = "Segoe UI"
MONO = "Consolas"


def east_asia(run, name=FONT):
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)
    rfonts.set(qn("w:ascii"), LATIN if name != MONO else MONO)
    rfonts.set(qn("w:hAnsi"), LATIN if name != MONO else MONO)


def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def cell_margins(table, top=90, bottom=90, left=120, right=120):
    tbl_pr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for side, value in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), str(value))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tbl_pr.append(mar)


def table_borders(table, color=BORDER, size=4, inside=True):
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    edges = ["top", "left", "bottom", "right"]
    if inside:
        edges += ["insideH", "insideV"]
    for edge in edges:
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(size))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    for edge in ("insideH", "insideV"):
        if inside:
            continue
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    tbl_pr.append(borders)


def keep_with_next(p):
    p.paragraph_format.keep_with_next = True


def add_bottom_border(p, color=ROSE, size=8, space=2):
    p_pr = p._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    p_pr.append(borders)


def add_field(paragraph, instr):
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = instr
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr_el)
    run._r.append(fld_sep)
    run._r.append(fld_end)


def add_rich(p, text, size=None, color=None, bold=False):
    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if not part:
            continue
        is_bold = part.startswith("**") and part.endswith("**")
        run = p.add_run(part[2:-2] if is_bold else part)
        east_asia(run)
        if size:
            run.font.size = Pt(size)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
        if bold or is_bold:
            run.bold = True


def body(text, after=5, before=0, size=10.5):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.line_spacing = 1.35
    add_rich(p, text, size=size, color=INK)
    for run in p.runs:
        if run.font.name is None:
            east_asia(run)
    return p


def bullet(text, bold_prefix=None):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.3
    if bold_prefix:
        r = p.add_run(bold_prefix)
        east_asia(r)
        r.bold = True
        r.font.size = Pt(10.5)
        r.font.color.rgb = RGBColor.from_string(INK)
    add_rich(p, text, size=10.5, color=INK)


def h1(text):
    p = doc.add_heading(level=1)
    p.paragraph_format.page_break_before = True
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(8)
    keep_with_next(p)
    r = p.add_run(text)
    east_asia(r)
    r.font.size = Pt(17)
    r.font.color.rgb = RGBColor.from_string(ROSE_DARK)
    r.bold = True
    add_bottom_border(p, ROSE, 6, 2)
    return p


def h2(text):
    p = doc.add_heading(level=2)
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    keep_with_next(p)
    r = p.add_run(text)
    east_asia(r)
    r.font.size = Pt(12.5)
    r.font.color.rgb = RGBColor.from_string(ROSE_DARK)
    r.bold = True
    return p


def h3(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    keep_with_next(p)
    r = p.add_run(text)
    east_asia(r)
    r.font.size = Pt(11)
    r.bold = True
    r.font.color.rgb = RGBColor.from_string(ROSE)
    return p


def no_split(row):
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:cantSplit")) is None:
        el = OxmlElement("w:cantSplit")
        tr_pr.append(el)


def add_table(headers, rows, widths=None, font_size=9.2, header_fill=ROSE_DARK):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table_borders(table)
    cell_margins(table)
    hdr = table.rows[0]
    no_split(hdr)
    tr_pr = hdr._tr.get_or_add_trPr()
    th = OxmlElement("w:tblHeader")
    th.set(qn("w:val"), "true")
    tr_pr.append(th)
    for i, text in enumerate(headers):
        cell = hdr.cells[i]
        cell.width = Cm(widths[i]) if widths else Cm(16.4 / len(headers))
        shade(cell, header_fill)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(text)
        east_asia(r)
        r.font.size = Pt(font_size)
        r.bold = True
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for row_index, row in enumerate(rows):
        table_row = table.add_row()
        no_split(table_row)
        cells = table_row.cells
        for i, text in enumerate(row):
            cell = cells[i]
            cell.width = Cm(widths[i]) if widths else Cm(16.4 / len(headers))
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            if row_index % 2 == 1:
                shade(cell, "FDF7F9")
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            add_rich(p, str(text), size=font_size, color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def callout(title, text, fill=ROSE_LIGHT, border=ROSE):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table_borders(table, color=border, size=4, inside=False)
    cell_margins(table, 110, 110, 170, 150)
    cell = table.rows[0].cells[0]
    cell.width = Cm(16.4)
    shade(cell, fill)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(title)
    east_asia(r)
    r.bold = True
    r.font.size = Pt(10)
    r.font.color.rgb = RGBColor.from_string(ROSE_DARK)
    p2 = cell.add_paragraph()
    p2.paragraph_format.space_after = Pt(0)
    p2.paragraph_format.line_spacing = 1.3
    add_rich(p2, text, size=9.8, color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_image(filename, width_in, caption):
    path = SHOTS / filename
    if not path.exists():
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(path), width=Inches(width_in))
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_after = Pt(8)
    r = cap.add_run(caption)
    east_asia(r)
    r.font.size = Pt(8.5)
    r.font.color.rgb = RGBColor.from_string(MUTED)


def code(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.4)
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(6)
    p_pr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "F5F0F7")
    p_pr.append(shd)
    r = p.add_run(text)
    east_asia(r, MONO)
    r.font.size = Pt(8.5)
    r.font.color.rgb = RGBColor.from_string("4A3844")


def page_break():
    # Section starts are controlled by Heading 1 page_break_before, which
    # avoids blank pages when a chapter happens to end at a page boundary.
    return


def make_cover():
    w, h = 1654, 2339
    top = (18, 10, 34)
    bottom = (54, 18, 48)
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=c)

    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-350, -250, 780, 880), fill=(155, 54, 105, 115))
    gd.ellipse((930, 320, 1880, 1270), fill=(85, 46, 150, 95))
    gd.ellipse((250, 1450, 1500, 2300), fill=(120, 30, 80, 55))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    draw = ImageDraw.Draw(img)

    # faint rings
    # (kept intentionally off: the rose glow is enough on the dark cover)

    rose = Image.open(ROOT / "packaging" / "app.png").convert("RGBA")
    rose = rose.resize((300, 300), Image.LANCZOS)
    img.alpha_composite(rose, (w // 2 - 150, 370))

    yahei = "C:/Windows/Fonts/msyh.ttc"
    yahei_bold = "C:/Windows/Fonts/msyhbd.ttc"
    segoe_bold = "C:/Windows/Fonts/segoeuib.ttf"
    segoe = "C:/Windows/Fonts/segoeui.ttf"
    f_kicker = ImageFont.truetype(segoe, 27)
    f_title = ImageFont.truetype(segoe_bold, 168)
    f_sub = ImageFont.truetype(yahei, 45)
    f_small = ImageFont.truetype(yahei, 27)
    f_quote = ImageFont.truetype(yahei, 33)
    f_bottom = ImageFont.truetype(yahei, 24)

    draw.text((w // 2, 170), "U S E R   M A N U A L", font=f_kicker, fill=(238, 164, 191, 220), anchor="ma")
    draw.text((w // 2, 765), "RoseSI", font=f_title, fill=(255, 248, 252), anchor="ma")
    draw.text((w // 2, 955), "日语实时字幕与同传工具", font=f_sub, fill=(242, 204, 220), anchor="ma")
    draw.line((w // 2 - 250, 1045, w // 2 + 250, 1045), fill=(255, 126, 166, 180), width=2)
    draw.text((w // 2, 1085), "用 户 手 册", font=f_quote, fill=(255, 182, 208), anchor="ma")
    draw.text((w // 2, 1175), "版本 1.2.0", font=f_small, fill=(214, 178, 198), anchor="ma")

    draw.text((w // 2, 1600), "让日语直播，变成你能跟上的中文。", font=f_quote, fill=(246, 224, 235, 235), anchor="ma")
    draw.text((w // 2, 1665), "实时字幕 · 术语库 · 语料库 · 五十音图", font=f_small, fill=(190, 156, 180), anchor="ma")

    draw.line((180, 2085, w - 180, 2085), fill=(255, 120, 160, 70), width=1)
    draw.text((w // 2, 2135), "Windows 10 / 11 x64   ·   本地优先   ·   代码 MIT", font=f_bottom, fill=(190, 165, 184), anchor="ma")
    draw.text((w // 2, 2180), "2026 年 10 月", font=f_small, fill=(150, 125, 150), anchor="ma")

    COVER.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(COVER, "PNG", optimize=True)


def setup_styles():
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor.from_string(INK)
    rpr = normal.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), FONT)
    rfonts.set(qn("w:ascii"), LATIN)
    rfonts.set(qn("w:hAnsi"), LATIN)
    normal.paragraph_format.line_spacing = 1.35
    normal.paragraph_format.space_after = Pt(4)

    for name, size, color, before, after in (
        ("Heading 1", 17, ROSE_DARK, 14, 8),
        ("Heading 2", 12.5, ROSE_DARK, 10, 4),
    ):
        st = doc.styles[name]
        st.font.name = FONT
        st.font.size = Pt(size)
        st.font.color.rgb = RGBColor.from_string(color)
        st.font.bold = True
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.paragraph_format.keep_with_next = True
        st_rpr = st.element.get_or_add_rPr()
        st_rf = st_rpr.find(qn("w:rFonts"))
        if st_rf is None:
            st_rf = OxmlElement("w:rFonts")
            st_rpr.append(st_rf)
        st_rf.set(qn("w:eastAsia"), FONT)
        st_rf.set(qn("w:ascii"), LATIN)
        st_rf.set(qn("w:hAnsi"), LATIN)


def setup_sections():
    cover = doc.sections[0]
    cover.page_width = Cm(21.0)
    cover.page_height = Cm(29.7)
    cover.left_margin = Cm(0.0)
    cover.right_margin = Cm(0.0)
    cover.top_margin = Cm(0.0)
    cover.bottom_margin = Cm(0.0)

    body_section = doc.add_section(WD_SECTION.NEW_PAGE)
    body_section.page_width = Cm(21.0)
    body_section.page_height = Cm(29.7)
    body_section.left_margin = Cm(2.2)
    body_section.right_margin = Cm(2.2)
    body_section.top_margin = Cm(2.0)
    body_section.bottom_margin = Cm(1.8)
    body_section.header_distance = Cm(0.9)
    body_section.footer_distance = Cm(0.9)

    body_section.header.is_linked_to_previous = False
    body_section.footer.is_linked_to_previous = False
    header = body_section.header.paragraphs[0]
    header.paragraph_format.tab_stops.clear_all()
    header.paragraph_format.tab_stops.add_tab_stop(Cm(16.6), WD_TAB_ALIGNMENT.RIGHT)
    header.paragraph_format.space_after = Pt(2)
    r = header.add_run("RoseSI 用户手册")
    east_asia(r)
    r.font.size = Pt(8.5)
    r.font.color.rgb = RGBColor.from_string(MUTED)
    header.add_run("\t\t")
    r = header.add_run("v1.2.0")
    east_asia(r)
    r.font.size = Pt(8.5)
    r.font.color.rgb = RGBColor.from_string(MUTED)
    add_bottom_border(header, BORDER, 4, 1)

    footer = body_section.footer.paragraphs[0]
    footer.paragraph_format.tab_stops.clear_all()
    footer.paragraph_format.tab_stops.add_tab_stop(Cm(16.6), WD_TAB_ALIGNMENT.RIGHT)
    r = footer.add_run("RoseSI · Windows 10 / 11")
    east_asia(r)
    r.font.size = Pt(8)
    r.font.color.rgb = RGBColor.from_string(MUTED)
    footer.add_run("\t\t")
    r = footer.add_run("第 ")
    east_asia(r)
    r.font.size = Pt(8)
    r.font.color.rgb = RGBColor.from_string(MUTED)
    add_field(footer, "PAGE")
    r = footer.add_run(" 页")
    east_asia(r)
    r.font.size = Pt(8)
    r.font.color.rgb = RGBColor.from_string(MUTED)

    pg_num = OxmlElement("w:pgNumType")
    pg_num.set(qn("w:start"), "1")
    body_section._sectPr.append(pg_num)

    # Cover header/footer intentionally empty.
    cover.header.is_linked_to_previous = False
    cover.footer.is_linked_to_previous = False


def add_cover():
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.left_indent = Cm(-0.37)
    p.add_run().add_picture(str(COVER), width=Cm(20.86))


def add_toc():
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("目录")
    east_asia(r)
    r.font.size = Pt(22)
    r.bold = True
    r.font.color.rgb = RGBColor.from_string(ROSE_DARK)
    add_bottom_border(p, ROSE, 8, 2)
    body("本手册按“先安装、再使用、最后排查”的顺序编写。Word 的导航窗格也可以按标题快速跳转。", after=8)
    rows = [
        ("01", "认识 RoseSI", "适用场景、三种显示模式、系统要求"),
        ("02", "下载与安装", "标准版 / Lite、分卷合并、校验、安装"),
        ("03", "第一次使用", "API Key 或本地模型、音频源、开始同传"),
        ("04", "字幕窗", "专注 / 双语 / 学习、回到最新、多屏、穿透"),
        ("05", "五十音图", "打开方式、搜索、点击复制、置顶"),
        ("06", "工作台", "侧栏、实时预览、记录、导出、设置"),
        ("07", "术语库", "288 条基础库、复制、自建库、导入导出"),
        ("08", "语料库与候选审核", "命中、候选规则、AI 预审、审核"),
        ("09", "快捷键", "开始、工作台、穿透、五十音图"),
        ("10", "数据与隐私", "数据目录、DPAPI、云端/本地边界"),
        ("11", "常见问题", "没声音、没字幕、漏句、延迟、报错"),
        ("12", "更新与许可", "卸载、备份、MIT、模型许可证"),
    ]
    table = doc.add_table(rows=1, cols=3)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table_borders(table, BORDER, 4, True)
    cell_margins(table, 85, 85, 100, 100)
    widths = [1.5, 5.1, 9.8]
    for i, text in enumerate(("章", "标题", "内容")):
        cell = table.rows[0].cells[i]
        cell.width = Cm(widths[i])
        shade(cell, "F8E9EF")
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(text)
        east_asia(r)
        r.font.size = Pt(9)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string(ROSE_DARK)
    for idx, (num, title, desc) in enumerate(rows):
        table_row = table.add_row()
        no_split(table_row)
        cells = table_row.cells
        for i, text in enumerate((num, title, desc)):
            cell = cells[i]
            cell.width = Cm(widths[i])
            if idx % 2 == 1:
                shade(cell, "FDF8FA")
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(text)
            east_asia(r)
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor.from_string(INK if i != 0 else ROSE)
    page_break()


def add_content():
    page_break()
    # 1
    h1("01  认识 RoseSI")
    body("RoseSI 是一个 Windows 桌面端的日语实时字幕 / 同传工具：把浏览器、播放器或会议软件里的日语声音，识别成日文字幕，再翻译成简体中文，显示在一个常驻置顶的独立字幕窗里。所有术语库、语料库和会话记录都保存在本机 SQLite；翻译可以选择完全本地的 HY-MT，也可以使用 DeepSeek 云端模型。")
    body("它适合看日语直播、Vtuber、生肉视频、线上会议，也适合日语学习和复盘。字幕窗只负责“看”，完整操作在「工作台」里完成。")
    h2("三种显示模式")
    add_table(
        ("模式", "当前句", "历史句", "适合"),
        (
            ("专注", "只显示译文，26–32 px，原文完全隐藏", "隐藏", "直播全屏观看、只想知道中文意思"),
            ("双语", "原文小、译文大", "只保留一行译文摘要", "日常默认；既能听到语气，也能快速读中文"),
            ("学习", "原文和译文都完整显示，字号接近", "完整保留", "复盘、查词、对照学习"),
        ),
        widths=[2.2, 7.0, 4.4, 2.8],
    )
    h2("系统要求")
    add_table(
        ("项目", "建议"),
        (
            ("系统", "Windows 10 2004+ / Windows 11，64 位"),
            ("显卡", "NVIDIA 显卡 6 GB 显存以上推荐；CPU 也能跑，但延迟更高"),
            ("内存", "8 GB 最低，16 GB 更稳"),
            ("磁盘", "标准版安装后约 5.6 GB；Lite 约 3.4 GB，模型另下载"),
            ("网络", "使用 DeepSeek 或首次下载模型时需要；纯本地翻译不需要网络"),
        ),
        widths=[3.2, 13.2],
    )
    body("RoseSI 是原生窗口，不是浏览器页面。字幕窗可以一直置顶，工作台是另一个窗口；两者分开，互不挡字幕。")

    page_break()
    # 2
    h1("02  下载与安装")
    h2("2.1 标准版和 Lite 怎么选")
    add_table(
        ("版本", "内置模型", "安装包", "安装后", "适合"),
        (
            ("标准版", "Parakeet + HY-MT", "3.41 GB，两个分卷", "约 5.6 GB", "开箱即用，不想首次再等下载"),
            ("Lite 在线版", "不含模型", "约 1.14 GB，单文件", "约 3.4 GB", "下载/磁盘有限，愿意首次下载模型"),
        ),
        widths=[2.6, 4.6, 3.6, 2.4, 3.2],
    )
    body("Lite 首次启动时，在「设置 → 本地识别」下载 Parakeet（约 1.2 GB），在「翻译服务 → 本地模型」下载 HY-MT（约 1.1 GB）。两个都下载后，离线也能用；只使用 DeepSeek 的话，可以不下载 HY-MT。")
    callout("关于解压版", "当前 GitHub Release 只提供标准安装版和 Lite 安装版，没有独立的解压包。标准安装版按当前用户安装，不要求管理员权限；如果确实需要免安装目录，可以按 README 的「打包与分发」自行生成 dist/RoseSI 后打包。")
    h2("2.2 下载标准版")
    body("打开 GitHub 的 Releases 页面，下载以下两个文件（必须两个都下）：")
    bullet("RoseSI-1.2.0-Setup.exe.part001", "分卷一：")
    bullet("RoseSI-1.2.0-Setup.exe.part002", "分卷二：")
    body("放到同一个文件夹，在 CMD 中执行：")
    code("copy /b RoseSI-1.2.0-Setup.exe.part001 + RoseSI-1.2.0-Setup.exe.part002 RoseSI-1.2.0-Setup.exe")
    body("然后核对 SHA256（PowerShell）：")
    code("Get-FileHash -Algorithm SHA256 .\\RoseSI-1.2.0-Setup.exe")
    body("标准版完整包的 SHA256 为 1e6d5199a2af10a630d8ea20f180523f09a2cd64c084b14a5aee9012d4736f49；Release 的 SHA256.txt 里还包含两个分卷的校验值。")
    h2("2.3 下载 Lite")
    body("Lite 只有一个 RoseSI-1.2.0-Lite-Setup.exe，不需要合并；下载后核对 SHA256-Lite.txt，再双击安装。")
    h2("2.4 安装")
    body("双击安装包，按向导下一步即可。标准安装版默认安装到当前用户目录，不需要管理员权限；如果 SmartScreen 提示“Windows 已保护你的电脑”，点“更多信息 → 仍要运行”，因为安装包没有购买代码签名证书。")
    body("安装完成后，桌面和开始菜单会出现 RoseSI。首次启动会创建数据目录，不会自带任何 API Key。")

    page_break()
    # 3
    h1("03  第一次使用")
    body("第一次启动建议按下面的顺序设置：翻译 → 识别 → 音频源 → 保存 → 开始。")
    h2("3.1 选择翻译方式")
    add_table(
        ("方式", "需要什么", "优点", "注意"),
        (
            ("DeepSeek 云端", "自己的 DeepSeek API Key", "质量好、延迟低、无需下载大模型", "文本会发到 DeepSeek；按量计费"),
            ("本地 HY-MT", "下载 HY-MT1.5 1.8B（约 1.1 GB）", "完全离线、不产生 API 费用", "首次加载需要几秒；质量略低于云端大模型"),
        ),
        widths=[3.0, 5.4, 4.8, 3.2],
    )
    body("在「设置 → 翻译服务」选择翻译方式。用 DeepSeek 就填入自己的 Key，点「测试连接」；用本地模型就点「下载模型」，等状态变成「已就绪」。")
    callout("API Key 安全", "RoseSI 不内置、也不会向服务器上传你的 Key。Key 用 Windows DPAPI 加密后只保存在本机 %LOCALAPPDATA%\\LocalInterpreter\\config.json；换一台电脑需要重新填写。")
    h2("3.2 选择识别模型")
    body("标准版已经内置 Parakeet TDT 0.6B JA，并把它作为日语直播首选；Lite 需要先在「设置 → 本地识别」点「下载模型」。如果 Parakeet 在你的机器上不合适，可以在同一位置切换 faster-whisper、Kotoba 等模型。")
    body("Parakeet 只做“最终句”识别，不显示逐字草稿；它会在你停顿后一次性给出日文，再交给翻译。这样字幕更稳，但第一行出现的时间取决于静音断句。")
    h2("3.3 选择音频源")
    add_table(
        ("音频源", "适用", "说明"),
        (
            ("系统声音", "浏览器、播放器、会议软件", "抓取整个输出设备的环回；最简单"),
            ("麦克风", "现场说话、会议发言", "需要允许麦克风权限"),
            ("浏览器标签页", "只想抓一个网页", "安装附带扩展；适合同时开多个直播"),
        ),
        widths=[3.2, 6.4, 6.8],
    )
    body("如果选择「系统声音」，在列表里选浏览器/播放器实际使用的输出设备，而不是“默认设备”想当然。用蓝牙耳机时尤其要确认声音确实走的是那个设备。")
    h2("3.4 保存并开始")
    body("点右上角「保存并应用」，回到字幕窗点「开始」，或按 Ctrl+Shift+S。第一次加载模型会慢一些（约 3–6 秒），之后模型常驻，再次开始会快很多。")
    add_image("workbench_settings_parakeet.png", 4.9, "设置页中的 Parakeet 状态与模型入口")

    page_break()
    # 4
    h1("04  字幕窗")
    body("字幕窗是 RoseSI 最常驻的窗口：无边框、半透明、始终置顶。拖动顶部可以移动；拖动四边/四角可以调整宽高；右键或点右上角「⋯」可以打开菜单。")
    add_image("overlay.png", 6.2, "双语模式：当前句原文小、译文大；历史句只保留一行译文")
    h2("4.1 三种模式")
    body("点顶部的「专注 / 双语 / 学习」按钮切换，也可以在设置里选默认模式。")
    bullet("只显示当前译文，字号 26–32 px；原文和历史句完全隐藏。适合全屏看直播。", "专注：")
    bullet("当前句原文小、译文大；历史句只保留一行译文摘要，鼠标悬停可看完整原文。适合日常使用。", "双语：")
    bullet("原文和译文都完整显示，字号接近；适合复盘、学习和查词。", "学习：")
    h2("4.2 回到最新")
    body("向上翻历史后，右下角会出现「↓ 回到最新」；点它回到底部。新句子到达时，如果你正在上翻，不会强行拉回底部；想继续跟直播时点一下即可。")
    h2("4.3 术语和记忆命中")
    body("当前句命中术语库或语料库时，译文下方会显示「术语 N · 记忆命中」。语料库整句命中时不会调用 API，延迟接近 0；术语只在当前句命中条目时注入。")
    h2("4.4 工具栏、多屏、穿透")
    bullet("工具栏在运行时会在 2.4 秒后自动变淡，鼠标移上去恢复；可在右键菜单关掉「自动隐藏工具栏」。", "自动隐藏：")
    bullet("右键 → 窗口位置，可以快速移到主屏/副屏的底部或顶部；也可以选择「鼠标所在屏幕」。", "多屏：")
    bullet("按 Ctrl+Alt+T 开启鼠标穿透，字幕窗不再接收鼠标；再按一次恢复。", "穿透：")
    bullet("拖动边缘调整大小；高度会随内容自适应，超过屏幕 82% 时内部滚动。", "调整大小：")

    page_break()
    # 5
    h1("05  五十音图")
    body("五十音图是一个独立小窗口，随时可以打开，不会影响同传。适合听到不熟的假名时快速确认。")
    add_image("kana_window_full.png", 4.4, "五十音图：清音 46 音，平假名 / 片假名并排，下方为罗马字")
    h2("5.1 打开方式")
    bullet("按 Ctrl+Alt+K。", "快捷键：")
    bullet("字幕窗右键菜单 → 五十音图。", "字幕窗：")
    bullet("工作台左侧「あ 五十音图」按钮，或托盘菜单。", "工作台 / 托盘：")
    h2("5.2 使用")
    body("顶部标签切换清音 / 浊音·半浊音 / 拗音；搜索框可以输入假名、罗马字或中文提示，例如 ki、き、キ。左键点格子复制平假名，右键复制片假名；窗口底部会显示“已复制”。")
    body("勾选「置顶」可以让它一直显示在其他窗口上方；按 Esc 关闭。默认窗口已经压缩到一屏，不需要滚轮就能看完整张表。")

    page_break()
    # 6
    h1("06  工作台")
    body("工作台是完整功能窗口，和字幕窗分开。左侧栏分为「同传 / 记录 / 系统」三组，可以折叠成图标栏；底部的「开始同传 / 停止同传」在任何页面都能用。")
    add_image("workbench_dashboard.png", 6.2, "工作台：分组侧栏、全局开始/停止、实时预览和运行状态")
    h2("6.1 页面")
    add_table(
        ("页面", "用途"),
        (
            ("实时同传", "查看本次字幕流、ASR/翻译/端到端延迟、音频源、识别语言和引擎状态"),
            ("术语库", "切换/编辑术语库，导入导出，启用单条术语"),
            ("语料库", "已审核/待审核/已拒绝；整句记忆和候选审核"),
            ("会话记录", "每次同传自动保存，可回看、搜索、导出"),
            ("导出", "SRT/TXT/Markdown/JSON/CSV/Excel"),
            ("设置", "翻译、识别、音频、字幕窗、快捷键、数据目录"),
        ),
        widths=[3.4, 13.0],
    )
    h2("6.2 侧栏和状态")
    body("点品牌名右侧的「‹」可以收起侧栏，再点「›」展开；状态会记住。语料库有待审核候选时，侧栏「语料库」右侧会出现数字角标。")
    body("底部的状态点表示引擎状态：灰色待机、绿色运行、橙色警告。旁边的版本号可以帮助你确认当前安装的是哪个版本。")

    page_break()
    # 7
    h1("07  术语库")
    body("术语库决定专有名词怎么翻译。RoseSI 内置一个只读的基础术语库「基础术语库 · 日中直播」，共 288 条，覆盖日语直播、Vtuber、Bilibili、游戏和字幕常见说法；其中约 116 条是 Bilibili Vtuber 专用。")
    add_image("workbench_terms.png", 6.2, "内置基础术语库：只读、可按条停用，也可以复制成自己的库")
    h2("7.1 基础库怎么用")
    bullet("默认参与匹配；如果某条不适合你的场景，取消该行的「启用」即可，不需要删除。", "启用：")
    bullet("顶部的「使用术语库」是总开关；关掉后所有术语库都不参与。", "总开关：")
    bullet("点「复制为我的库」，会生成一个可编辑副本；改副本，不会影响内置库。", "复制：")
    body("内置库会随版本更新同步内容，所以不要直接修改它；要定制就复制。")
    h2("7.2 创建和编辑自己的库")
    body("点「新建术语库」，起一个名字；然后「添加术语」或用「导入」批量导入 CSV/Excel。每条术语包含原文、译文、别名（可选）、领域、备注、优先级和启用状态。多个库可以同时启用，匹配时合并参与。")
    table_rows = (
        ("原文", "日语词或短语，例如 スパチャ", "按句中实际出现匹配"),
        ("译文", "中文译法，例如 SC", "会注入翻译提示，不直接替换字幕"),
        ("别名", "同义词/缩写，用逗号分隔", "可选；用于提高命中率"),
        ("优先级", "数字，越大越优先", "重叠命中时优先"),
    )
    add_table(("字段", "说明", "备注"), table_rows, widths=[2.6, 7.0, 6.8])
    h2("7.3 导入导出")
    body("支持 CSV / Excel 导入导出，适合从表格批量维护。导入前建议先备份当前库；导入不会删除已有条目，重复原文会按唯一键更新。")

    page_break()
    # 8
    h1("08  语料库与候选审核")
    body("语料库保存“整句原文 → 整句译文”。命中时直接复用，不走 API，因此延迟接近 0；没有命中时才交给翻译模型。为了避免把错误译文写进正式库，自动学习默认只生成「待审核」候选。")
    h2("8.1 三个标签")
    add_table(
        ("标签", "内容", "可做什么"),
        (
            ("已审核", "真正参与整句匹配的条目", "搜索、编辑、删除、导出"),
            ("待审核", "自动学习生成、等待确认的候选", "编辑译文、通过、拒绝、AI 预审、批量通过"),
            ("已拒绝", "被拒绝或过期的候选", "恢复、彻底删除"),
        ),
        widths=[2.8, 7.6, 6.0],
    )
    add_image("workbench_corpus_pending.png", 6.2, "待审核：左侧候选列表，右侧详情、规则分、术语和 AI 建议")
    h2("8.2 候选是怎么来的")
    body("一次同传结束后，规则会先过滤：太短、太长、纯语气词、纯数字/符号、原文译文相同、目标语言不对、缺术语、重复句等，会被直接丢弃或标记。通过的候选进入待审核，不会自动污染正式语料库。")
    body("「候选学习」开关可以关掉，改为只记录会话、不生成候选。已经审核通过的句子才会参与后续整句匹配。")
    h2("8.3 AI 预审")
    body("在「设置 → AI 语料审核」可以打开 AI 预审，并选择 DeepSeek 模型。点待审核页的「AI 预审」，AI 会给每条候选一个建议：通过 / 需人工 / 拒绝，并给出问题标签和理由。")
    callout("AI 只是建议", "AI 不会直接代替你审核，默认也不会自动写入正式库；自动采纳默认关闭。AI 只收到候选文本，不会收到音频。使用前请确认你接受把文本发送到 DeepSeek。")
    body("「采纳 AI 高置信」只处理 AI 建议通过且无问题的候选；「通过选中」会把候选写入已审核语料库；「拒绝选中」会移到已拒绝。")

    page_break()
    # 9
    h1("09  快捷键")
    add_table(
        ("快捷键", "功能", "说明"),
        (
            ("Ctrl+Shift+S", "开始 / 停止同传", "全局有效；也可点字幕窗或工作台按钮"),
            ("Ctrl+Alt+W", "打开工作台", "从字幕窗切换到完整界面"),
            ("Ctrl+Alt+T", "鼠标穿透", "字幕窗不再挡鼠标；再按恢复"),
            ("Ctrl+Alt+H", "显示 / 隐藏字幕窗", "临时收起，不停止同传"),
            ("Ctrl+Alt+K", "打开五十音图", "随时打开，不影响同传"),
            ("Ctrl+F", "五十音图搜索", "在五十音图窗口内有效"),
            ("Esc", "关闭五十音图", "在五十音图窗口内有效"),
        ),
        widths=[4.0, 5.4, 7.0],
    )
    body("如果快捷键冲突，可以在「设置 → 全局热键」里改成其他组合；保存后立即生效。")

    page_break()
    # 10
    h1("10  数据与隐私")
    h2("10.1 数据放在哪")
    add_table(
        ("内容", "位置"),
        (
            ("配置、API Key（DPAPI 加密）", "%LOCALAPPDATA%\\LocalInterpreter\\config.json"),
            ("会话记录、术语库、语料库", "%LOCALAPPDATA%\\LocalInterpreter\\sessions.db"),
            ("下载的模型", "%LOCALAPPDATA%\\LocalInterpreter\\models\\"),
            ("日志", "%LOCALAPPDATA%\\LocalInterpreter\\logs\\"),
        ),
        widths=[7.2, 9.2],
    )
    body("安装目录只读即可；升级或重装不会删除上面的用户数据。备份时复制整个 LocalInterpreter 目录即可；注意 config.json 里的 Key 使用当前 Windows 用户的 DPAPI 加密，换用户/换机器后需要重新填写。")
    h2("10.2 云端和本地边界")
    bullet("本地 ASR（Parakeet / Whisper）不联网，音频不离开本机。", "识别：")
    bullet("本地 HY-MT 翻译时，原文和译文都不离开本机。", "本地翻译：")
    bullet("选择 DeepSeek 时，字幕文本会发送到 DeepSeek API；不发送音频。", "云端翻译：")
    bullet("AI 预审只用候选文本，不发送音频；可以在设置里关闭。", "AI 审核：")
    body("安装包不包含任何 API Key。首次启动时 config.json 里的 api_key_enc 为空；只有你自己填写后才会写入。")
    h2("10.3 清理数据")
    body("卸载程序只会删除安装目录；如果不再使用，可以手动删除 %LOCALAPPDATA%\\LocalInterpreter。删除前先导出需要的会话记录。")

    page_break()
    # 11
    h1("11  常见问题")
    qa = (
        ("开始后完全没有字幕", "先确认音频源选的是实际发声的设备；再看引擎状态是否绿色。Lite 版需要先下载 Parakeet 和 HY-MT 模型。"),
        ("有日文但没有中文", "检查翻译方式：DeepSeek 是否填了 Key、余额是否足够；本地模型是否已下载并加载。设置页的「测试翻译」可以快速判断。"),
        ("字幕断句太碎或太长", "静音断句会受语速和环境影响。可以在设置里调整静音阈值/最大段长；Parakeet 的语义断句会在非终止形后多等一会儿。"),
        ("Parakeet 容易漏句", "旧版曾把短音频补静音到 8 秒，导致 TDT 输出空；新版已移除该补零。请使用 1.2.0 及以上，并确认模型文件完整。"),
        ("延迟很高", "首次加载模型 3–6 秒；之后检查是否是 DeepSeek 网络慢、翻译队列是否积压、显卡是否真的在用 CUDA。工作台的运行状态会显示 ASR、翻译 TTFB、端到端和队列。"),
        ("下载模型失败", "默认走 hf-mirror；网络不稳定时重试，或在设置里手动选择已经下载好的模型目录。模型文件不要改名。"),
        ("DeepSeek 报 401/402", "401 是 Key 无效；402 通常是余额不足。检查 Key 是否复制完整、是否有多余空格。"),
        ("术语没有生效", "确认所属术语库已启用、单条术语已勾选、原文确实出现在当前句；多个库重叠时优先级高的生效。"),
        ("候选人太多 / 不想自动学习", "把「候选学习」改为关闭，或只保留手动添加。待审核候选不会参与匹配，拒绝后可以彻底删除。"),
        ("SmartScreen 拦截 / 杀软报毒", "安装包未购买代码签名证书，SmartScreen 可能提示未知发布者；点「更多信息 → 仍要运行」。如果杀软误报，添加信任或从官方 Release 重新下载并核对 SHA256。"),
    )
    for idx, (q, a) in enumerate(qa, 1):
        h3(f"{idx}. {q}")
        body(a, after=4)

    page_break()
    # 12
    h1("12  更新与许可")
    h2("12.1 更新")
    body("新版本发布后，直接运行新的安装包覆盖安装即可；用户数据在 %LOCALAPPDATA%\\LocalInterpreter，不会被覆盖。升级前建议先导出重要会话，或复制整个数据目录做备份。")
    h2("12.2 卸载")
    body("在 Windows「设置 → 应用 → 已安装的应用」里找到 RoseSI 卸载。卸载不会删除用户数据；如需彻底清理，再手动删除数据目录。")
    h2("12.3 许可证")
    body("RoseSI 的代码采用 MIT License，见仓库根目录 LICENSE。模型权重和第三方运行时不在 MIT 授权范围内：")
    bullet("Tencent HY-MT1.5：Tencent HY Community License（见 LICENSES/HY-MT1.5-License.txt）。", "翻译模型：")
    bullet("Parakeet TDT 0.6B JA：CC-BY-4.0。", "识别模型：")
    bullet("faster-whisper / Whisper、PySide6、llama-cpp-python、ONNX Runtime 等：见 THIRD_PARTY_NOTICES.md 与各自发行许可。", "其他：")
    body("仓库不提交模型权重；安装包内置模型时，请同时遵守对应模型许可证。")
    h2("12.4 免责声明")
    body("本软件按“现状”提供，不对识别/翻译准确性、直播合规性或第三方服务可用性作保证。请遵守直播平台、版权和当地法律；使用云端翻译时，不要发送你不允许外发的文本。")

    appendix = h2("附录：模型与下载")
    appendix.paragraph_format.page_break_before = True
    add_table(
        ("模型", "用途", "大小", "是否内置"),
        (
            ("Parakeet TDT 0.6B JA", "日语 ASR，直播首选", "约 1.2 GB", "标准版内置；Lite 下载"),
            ("HY-MT1.5-1.8B Q4", "本地日→中翻译", "约 1.1 GB", "标准版内置；Lite 下载"),
            ("faster-whisper large-v3-turbo", "兼容/备用 ASR", "约 1.6 GB", "不内置，设置里可下载"),
            ("Kotoba / 其他 Whisper", "日语/兼容模型", "按模型", "不内置，设置里可下载"),
            ("HY-MT1.5-7B Q4", "更高质量的本地翻译", "约 4.6 GB", "不内置，设置里可下载"),
        ),
        widths=[5.6, 5.2, 3.0, 4.0],
    )
    body("模型下载页和直链集中在 packaging/models.json；也可以在设置页直接点「下载模型」。下载后模型保存在 %LOCALAPPDATA%\\LocalInterpreter\\models，升级不会丢失。")


def build():
    global doc
    make_cover()
    doc = Document()
    setup_styles()
    add_cover()
    setup_sections()
    add_toc()
    add_content()
    doc.core_properties.title = "RoseSI 用户手册"
    doc.core_properties.subject = "RoseSI 1.2.0 日语实时字幕与同传工具用户手册"
    doc.core_properties.author = "RoseSI"
    doc.core_properties.keywords = "RoseSI, 同传, 日语字幕, Parakeet, HY-MT"
    doc.core_properties.language = "zh-CN"
    # Ask Word to refresh fields (TOC/page numbers) on open.
    settings = doc.settings.element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)
    doc.save(OUT)
    print(f"saved {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build()

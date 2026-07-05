import os
import re
import logging
import requests
from io import BytesIO
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm, inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether, Flowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf_service")

app = FastAPI(title="XiaoYue Dict PDF Service")

# ─────────────────────────────────────────────────────────────
#  FONT CONFIGURATION & CACHING (Pedagogical SongTi)
# ─────────────────────────────────────────────────────────────
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONT_PATH = os.path.join(FONT_DIR, "ZCOOLXiaoWei-Regular.ttf")
FONT_NAME = "ZCOOLXiaoWei"

def register_chinese_font():
    # Priority: System AR PL Kaiti (Pedagogical), then WenQuanYi ZenHei, then Windows KaiTi/SimSun, then download
    cjk_fonts_to_try = [
        ("/usr/share/fonts/truetype/arphic-gkai00mp/gkai00mp.ttf", None),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttf", None),
        ("C:/Windows/Fonts/simkai.ttf", None),
        ("C:/Windows/Fonts/simsun.ttc", 0),
        ("C:/Windows/Fonts/msyh.ttc", 0),
    ]
    
    for path, index in cjk_fonts_to_try:
        if os.path.exists(path):
            try:
                if index is not None:
                    pdfmetrics.registerFont(TTFont(FONT_NAME, path, subfontIndex=index))
                else:
                    pdfmetrics.registerFont(TTFont(FONT_NAME, path))
                logger.info(f"Registered system CJK font successfully: {path} (index: {index})")
                return FONT_NAME
            except Exception as e:
                logger.error(f"Failed to register system CJK font {path}: {e}")
                
    # Fallback to download ZCOOL XiaoWei if system fonts are not found
    os.makedirs(FONT_DIR, exist_ok=True)
    if not os.path.exists(FONT_PATH):
        try:
            logger.info("Downloading ZCOOL XiaoWei font from Google Fonts...")
            url = "https://github.com/google/fonts/raw/main/ofl/zcoolxiaowei/ZCOOLXiaoWei-Regular.ttf"
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            with open(FONT_PATH, "wb") as f:
                f.write(r.content)
            logger.info("ZCOOL XiaoWei font downloaded successfully.")
        except Exception as e:
            logger.error(f"Failed to download ZCOOL XiaoWei font: {e}. Trying fallback.")
            
    # Register font if file exists
    if os.path.exists(FONT_PATH):
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
            logger.info(f"Registered {FONT_NAME} font successfully.")
            return FONT_NAME
        except Exception as e:
            logger.error(f"Error registering downloaded font: {e}")
            
    logger.warning("No CJK font registered. Fallback to Helvetica.")
    return "Helvetica"

# ─────────────────────────────────────────────────────────────
#  VIETNAMESE FONT: Liberation Serif (metrically identical to Times New Roman)
# ─────────────────────────────────────────────────────────────
VN_FONT = "TimesVN"
VN_FONT_BOLD = "TimesVN-Bold"
VN_FONT_ITALIC = "TimesVN-Italic"

def register_vietnamese_fonts():
    """Register Liberation Serif fonts which are metrically identical to Times New Roman.
    Provides full Vietnamese diacritics support.
    Fallback chain: Liberation Serif → DejaVu Serif → Windows Times New Roman."""
    font_registrations = [
        (VN_FONT, [
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "C:/Windows/Fonts/times.ttf"
        ]),
        (VN_FONT_BOLD, [
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "C:/Windows/Fonts/timesbd.ttf"
        ]),
        (VN_FONT_ITALIC, [
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            "C:/Windows/Fonts/timesi.ttf"
        ])
    ]

    for font_name, candidate_paths in font_registrations:
        registered = False
        for sys_path in candidate_paths:
            if os.path.exists(sys_path):
                try:
                    pdfmetrics.registerFont(TTFont(font_name, sys_path))
                    logger.info(f"Registered Vietnamese font {font_name} from {sys_path}")
                    registered = True
                    break
                except Exception as e:
                    logger.error(f"Failed to register Vietnamese font {font_name} from {sys_path}: {e}")
        if not registered:
            logger.warning(f"Could not register Vietnamese font {font_name}. Vietnamese text may render incorrectly.")

# Register on startup
ACTIVE_FONT = register_chinese_font()
register_vietnamese_fonts()

# ─────────────────────────────────────────────────────────────
#  STROKE DECONSTRUCTION & CACHING
# ─────────────────────────────────────────────────────────────
import json
import httpx
from svg.path import parse_path
from svg.path.path import Move, Line, QuadraticBezier, CubicBezier, Close

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# CJK range check for Chinese characters
CJK_RE = re.compile(r'^[\u4e00-\u9fa5]$')

def get_char_stroke_data(char: str) -> Optional[dict]:
    if not CJK_RE.match(char):
        return None
        
    filename = f"{ord(char)}.json"
    cache_path = os.path.join(CACHE_DIR, filename)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading cache for char '{char}': {e}")
            
    # Fetch from CDN jsDelivr using httpx defensively
    url = f"https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0/{char}.json"
    try:
        with httpx.Client(timeout=5.0) as client:
            logger.info(f"Fetching stroke data for '{char}' from CDN...")
            response = client.get(url)
            if response.status_code == 200:
                data = response.json()
                try:
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False)
                except Exception as e:
                    logger.error(f"Failed to cache stroke data for '{char}': {e}")
                return data
            elif response.status_code == 404:
                logger.warning(f"Character '{char}' not found on CDN (404)")
            else:
                logger.warning(f"Failed to fetch '{char}' from CDN: HTTP {response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"Network error fetching stroke data for '{char}': {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching stroke data for '{char}': {e}")
        
    return None

def draw_svg_path_on_canvas(canvas, path_str: str, x_offset: float, y_offset: float, scale: float):
    try:
        path_obj = parse_path(path_str)
    except Exception as e:
        logger.error(f"Failed to parse SVG path: {e}")
        return
        
    path = canvas.beginPath()
    
    for segment in path_obj:
        if isinstance(segment, Move):
            x = x_offset + segment.end.real * scale
            y = y_offset + (segment.end.imag + 124) * scale
            path.moveTo(x, y)
        elif isinstance(segment, Line):
            x = x_offset + segment.end.real * scale
            y = y_offset + (segment.end.imag + 124) * scale
            path.lineTo(x, y)
        elif isinstance(segment, QuadraticBezier):
            x0, y0 = segment.start.real, segment.start.imag
            x1, y1 = segment.control.real, segment.control.imag
            x2, y2 = segment.end.real, segment.end.imag
            
            cx1 = x0 + (2.0 / 3.0) * (x1 - x0)
            cy1 = y0 + (2.0 / 3.0) * (y1 - y0)
            cx2 = x2 + (2.0 / 3.0) * (x1 - x2)
            cy2 = y2 + (2.0 / 3.0) * (y1 - y2)
            
            canvas_cx1 = x_offset + cx1 * scale
            canvas_cy1 = y_offset + (cy1 + 124) * scale
            canvas_cx2 = x_offset + cx2 * scale
            canvas_cy2 = y_offset + (cy2 + 124) * scale
            canvas_x2 = x_offset + x2 * scale
            canvas_y2 = y_offset + (y2 + 124) * scale
            
            path.curveTo(canvas_cx1, canvas_cy1, canvas_cx2, canvas_cy2, canvas_x2, canvas_y2)
        elif isinstance(segment, CubicBezier):
            canvas_cx1 = x_offset + segment.control1.real * scale
            canvas_cy1 = y_offset + (segment.control1.imag + 124) * scale
            canvas_cx2 = x_offset + segment.control2.real * scale
            canvas_cy2 = y_offset + (segment.control2.imag + 124) * scale
            canvas_x = x_offset + segment.end.real * scale
            canvas_y = y_offset + (segment.end.imag + 124) * scale
            
            path.curveTo(canvas_cx1, canvas_cy1, canvas_cx2, canvas_cy2, canvas_x, canvas_y)
        elif isinstance(segment, Close):
            path.close()
            
    canvas.drawPath(path, fill=True, stroke=False)


# ─────────────────────────────────────────────────────────────
#  PINYIN SYLLABLE SPLITTER (Regex aligner)
# ─────────────────────────────────────────────────────────────
SYLLABLE_RE = re.compile(
    r'(zh|ch|sh|[b-df-hj-np-tv-z])?' # Consonant initial
    r'([aeiouvüāáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜü]{1,3})' # Vowel center
    r'(ng|n|r)?', # Nasal final
    re.IGNORECASE
)

def clean_pinyin_token(token: str) -> str:
    # Remove diacritics/punctuation like periods, commas, question marks, etc.
    # Keep alphanumeric characters and pinyin diacritics
    cleaned = re.sub(r'[.,?!:;\'"()\[\]{}_\-+=/\\|~`@#$%^&*，。、？！：；“”（）《》]', '', token)
    return cleaned.strip()

def align_pinyin(chars: List[str], pinyin_str: str) -> List[str]:
    """
    Aligns pinyin syllables with characters.
    1. Splits by space.
    2. If counts match, returns syllables.
    3. If counts mismatch, splits using a CJK syllable regex.
    """
    pinyin_clean = pinyin_str.strip()
    if not pinyin_clean:
        return [""] * len(chars)
        
    tokens = [t.strip() for t in pinyin_clean.split() if t.strip()]
    if len(tokens) == len(chars):
        result = tokens
    else:
        # Regex fallback
        all_pinyin = "".join(tokens)
        matches = SYLLABLE_RE.findall(all_pinyin)
        syllables = ["".join(m) for m in matches if "".join(m)]
        
        if len(syllables) == len(chars):
            result = syllables
        else:
            # Ultimate padding/truncating fallback
            if len(tokens) < len(chars):
                result = tokens + [""] * (len(chars) - len(tokens))
            else:
                result = tokens[:len(chars)]
                
    # Clean punctuation from each aligned syllable
    return [clean_pinyin_token(s) for s in result]


def estimate_block_height(length: int, extra_rows: int, show_pinyin: bool, show_meaning: bool, show_notes: bool, 
                          has_meaning: bool, has_note: bool, stroke_by_stroke: bool = False, 
                          decomposed_strokes: List[int] = []) -> float:
    # Header height in points (approximate)
    header_pt = 32
    if show_pinyin:
        header_pt += 26
    if show_meaning and has_meaning:
        header_pt += 20
    header_h = header_pt
    
    # Note height in points
    note_h = 0
    if show_notes and has_note:
        note_h = 25
        
    if stroke_by_stroke:
        grid_size = (16.0 / 14.0) * cm
        decon_h = 0.0
        for s in decomposed_strokes:
            # Stroke label height (approx 14 points = 0.5 * cm)
            decon_h += 0.5 * cm + 0.15 * cm
            # Grid rows count: 2 rows if S <= 14, 3 rows if S > 14
            steps = min(s, 27)
            rows = 3 if steps > 14 else 2
            decon_h += rows * grid_size + (rows - 1) * 0.1 * cm
            decon_h += 0.3 * cm
            
        # Complete sentence rows height
        sent_label_h = 0.5 * cm + 0.15 * cm
        cols = 14
        num_chunks = (length + cols - 1) // cols
        if extra_rows == 0:
            sent_rows_h = num_chunks * (3 * grid_size + 2 * 0.1 * cm) + (num_chunks - 1) * 0.3 * cm
        else:
            sent_rows_h = num_chunks * (extra_rows * 2 * grid_size + (2 * extra_rows - 1) * 0.1 * cm) + (num_chunks - 1) * 0.3 * cm
            
        grids_h = decon_h + sent_label_h + sent_rows_h
    else:
        if length <= 3:
            grid_size = 2.0 * cm
            if extra_rows == 0:
                grids_h = 3 * grid_size + 2 * 0.1 * cm
            else:
                grids_h = extra_rows * (2 * grid_size) + (2 * extra_rows - 1) * 0.1 * cm
        else:
            grid_size = (16.0 / 14.0) * cm
            cols = 14
            num_chunks = (length + cols - 1) // cols
            if extra_rows == 0:
                grids_h = num_chunks * (3 * grid_size + 2 * 0.1 * cm) + (num_chunks - 1) * 0.3 * cm
            else:
                grids_h = num_chunks * (extra_rows * (2 * grid_size) + (2 * extra_rows - 1) * 0.1 * cm) + (num_chunks - 1) * 0.3 * cm
        
    total_h = header_h + 0.15 * cm + grids_h
    if note_h > 0:
        total_h += 0.15 * cm + note_h
    total_h += 0.7 * cm
    return total_h

# ─────────────────────────────────────────────────────────────
#  CUSTOM REPORTLAB ELEMENTS
# ─────────────────────────────────────────────────────────────
class TianzigeFlowable(Flowable):
    def __init__(self, chars: List[str], pinyins: List[str], grid_size: float, is_trace: bool = True, 
                 grid_color: str = '#D32F2F', font_name: str = FONT_NAME, 
                 stroke_data: Optional[List[str]] = None, stroke_steps: Optional[List[Optional[int]]] = None,
                 show_pinyin: bool = False):
        Flowable.__init__(self)
        self.chars = chars
        self.pinyins = pinyins
        self.grid_size = grid_size
        self.is_trace = is_trace
        self.grid_color = colors.HexColor(grid_color)
        self.font_name = font_name
        self.stroke_data = stroke_data
        self.stroke_steps = stroke_steps
        
        self.num_grids = len(chars)
        self.width = self.num_grids * self.grid_size
        self.height = self.grid_size
            
    def wrap(self, availWidth, availHeight):
        return self.width, self.height
        
    def draw(self):
        grid_h = self.grid_size
        
        for i in range(self.num_grids):
            x = i * self.grid_size
            y = 0
            
            # 1. Outer Square Border
            self.canv.saveState()
            self.canv.setStrokeColor(self.grid_color)
            self.canv.setLineWidth(0.8)
            self.canv.rect(x, y, self.grid_size, grid_h, stroke=1, fill=0)
            
            # 2. Inner Dashed Cross Lines (+)
            light_color = colors.HexColor(self._get_light_color(self.grid_color.hexval()))
            self.canv.setStrokeColor(light_color)
            self.canv.setLineWidth(0.4)
            self.canv.setDash(2, 2)
            self.canv.line(x, y + grid_h / 2, x + self.grid_size, y + grid_h / 2)
            self.canv.line(x + self.grid_size / 2, y, x + self.grid_size / 2, y + grid_h)
            self.canv.restoreState()
            
            # 3. Stroke rendering or Faint Gray Character for Tracing
            if self.stroke_data and self.stroke_steps and i < len(self.stroke_steps) and self.stroke_steps[i] is not None:
                step = self.stroke_steps[i]
                if step > 0:
                    scale = self.grid_size / 1024.0
                    
                    # If this is step 27 and total strokes >= 28, draw all strokes
                    draw_up_to = step
                    if step == 27 and len(self.stroke_data) >= 28:
                        draw_up_to = len(self.stroke_data)
                        
                    # Draw strokes in light gray
                    self.canv.saveState()
                    self.canv.setFillColor(colors.HexColor('#D3D3D3'))
                    for stroke_idx in range(min(draw_up_to, len(self.stroke_data))):
                        draw_svg_path_on_canvas(self.canv, self.stroke_data[stroke_idx], x, y, scale)
                    self.canv.restoreState()
            elif self.is_trace and i < len(self.chars) and self.chars[i] and self.chars[i].strip():
                char = self.chars[i]
                self.canv.saveState()
                char_font_size = self.grid_size * 0.93
                self.canv.setFont(self.font_name, char_font_size)
                self.canv.setFillColor(colors.HexColor('#D3D3D3')) # Faint grey
                
                # Center character horizontally
                c_width = self.canv.stringWidth(char, self.font_name, char_font_size)
                cx = x + (self.grid_size - c_width) / 2
                # Center character vertically
                cy = y + (grid_h - char_font_size) / 2 + char_font_size * 0.08
                self.canv.drawString(cx, cy, char)
                self.canv.restoreState()
                
    def _get_light_color(self, hex_val):
        hex_clean = hex_val.replace('0x', '').replace('#', '').strip()
        if len(hex_clean) == 6:
            r = int(hex_clean[0:2], 16)
            g = int(hex_clean[2:4], 16)
            b = int(hex_clean[4:6], 16)
            # Mix 75% white to lighten the color
            r_l = int(r + (255 - r) * 0.75)
            g_l = int(g + (255 - g) * 0.75)
            b_l = int(b + (255 - b) * 0.75)
            return f"#{r_l:02X}{g_l:02X}{b_l:02X}"
        return "#FFCDD2"

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas pattern to draw Page X / Y correctly,
    along with thin lines and header titles.
    """
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        show_cover = getattr(self, "show_cover", True)
        if show_cover and self._pageNumber == 1:
            return
            
        self.saveState()
        self.setFont(VN_FONT, 9)
        self.setFillColor(colors.HexColor('#777777'))
        
        x_left = 2.5 * cm
        x_right = 21.0 * cm - 2.5 * cm
        x_center = 10.5 * cm
        
        # 1. Header (Notebook Title & App Name)
        notebook_title = getattr(self, "notebook_title", "Sổ tay tập viết")
        branding_name = getattr(self, "branding_name", "XiaoYue Dict")
        self.drawString(x_left, 29.7 * cm - 3.5 * cm + 0.25 * cm, f"Sổ tay: {notebook_title}")
        if branding_name:
            self.drawRightString(x_right, 29.7 * cm - 3.5 * cm + 0.25 * cm, branding_name)
        
        # Header separator line
        self.setStrokeColor(colors.HexColor('#E0E0E0'))
        self.setLineWidth(0.5)
        self.line(x_left, 29.7 * cm - 3.5 * cm, x_right, 29.7 * cm - 3.5 * cm)
        
        # 2. Footer (Page numbers)
        page_text = f"Trang {self._pageNumber} / {page_count}"
        self.drawCentredString(x_center, 2.0 * cm - 0.5 * cm, page_text)
        self.drawString(x_left, 2.0 * cm - 0.5 * cm, "Luyện viết chữ Điền (Tianzige)")
        
        # Footer separator line
        self.line(x_left, 2.0 * cm, x_right, 2.0 * cm)
        self.restoreState()

# ─────────────────────────────────────────────────────────────
#  API SCHEMAS & REQUEST MODEL
# ─────────────────────────────────────────────────────────────
class WordModel(BaseModel):
    vocabulary: str
    pinyin: Optional[str] = ""
    meaning: Optional[str] = ""
    note: Optional[str] = ""

class OptionsModel(BaseModel):
    grid_color: Optional[str] = "#D32F2F"
    show_pinyin: Optional[bool] = True
    show_meaning: Optional[bool] = True
    show_notes: Optional[bool] = True
    show_cover: Optional[bool] = True
    branding_name: Optional[str] = "XiaoYue Dict"
    extra_rows: Optional[int] = 0
    empty_pages: Optional[int] = 0
    empty_page_grid_size: Optional[str] = "auto"
    stroke_by_stroke: Optional[bool] = False

class GenerateRequest(BaseModel):
    title: str
    words: List[WordModel]
    options: OptionsModel

# ─────────────────────────────────────────────────────────────
#  FASTAPI ENDPOINT
# ─────────────────────────────────────────────────────────────
@app.post("/generate")
def generate_pdf(req: GenerateRequest):
    if not req.words:
        raise HTTPException(status_code=400, detail="Không có từ vựng nào để xuất PDF")
        
    if req.options.stroke_by_stroke:
        for word in req.words:
            raw_vocab = word.vocabulary.strip()
            # Filter vocabulary to only Chinese characters
            hanzi_list = [c for c in raw_vocab if '\u4e00' <= c <= '\u9fff']
            if not hanzi_list:
                hanzi_list = list(raw_vocab)
                
            length = len(hanzi_list)
            if length > 14:
                raise HTTPException(
                    status_code=400,
                    detail=f"Hệ thống phát hiện câu vượt quá 14 chữ Hán: {raw_vocab}."
                )
                
            for char in hanzi_list:
                stroke_data = get_char_stroke_data(char)
                if not stroke_data or 'strokes' not in stroke_data:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Hệ thống phát hiện từ không đúng định dạng hoặc không hỗ trợ phân rã nét: {char}."
                    )
                S = len(stroke_data['strokes'])
                if S > 27:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Hệ thống phát hiện từ không đúng định dạng: {char} ({S} nét) vượt quá giới hạn 27 nét."
                    )
                        
    try:
        buffer = BytesIO()
        
        # A4 margins: Left/Right 2.5cm, Top 3.5cm, Bottom 2.0cm
        # A4 size = 595.27 x 841.89 pt
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=2.5*cm,
            rightMargin=2.5*cm,
            topMargin=3.5*cm,
            bottomMargin=2.0*cm
        )
        
        styles = getSampleStyleSheet()
        
        # Define base styles using Liberation Serif (Times New Roman) for Vietnamese diacritics
        styles.add(ParagraphStyle(
            name='CoverTitle',
            fontName=VN_FONT_BOLD,
            fontSize=32,
            leading=38,
            alignment=1, # Center
            textColor=colors.HexColor('#1B5E20') # Dark Green theme
        ))
        styles.add(ParagraphStyle(
            name='CoverSubtitle',
            fontName=VN_FONT,
            fontSize=16,
            leading=22,
            alignment=1, # Center
            textColor=colors.HexColor('#555555')
        ))
        styles.add(ParagraphStyle(
            name='CoverQuote',
            fontName=ACTIVE_FONT, # Use Pedagogical CJK font for quote
            fontSize=18,
            leading=24,
            alignment=1,
            textColor=colors.HexColor('#2E7D32'),
            spaceBefore=20,
            spaceAfter=20
        ))
        styles.add(ParagraphStyle(
            name='CoverMetadata',
            fontName=VN_FONT,
            fontSize=12,
            leading=17,
            alignment=1,
            textColor=colors.HexColor('#666666')
        ))
        styles.add(ParagraphStyle(
            name='WordTitle',
            fontName=ACTIVE_FONT, # Chinese font for word in header
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#1A237E')
        ))
        styles.add(ParagraphStyle(
            name='WordInfo',
            fontName=VN_FONT,
            fontSize=15,
            leading=32,
            textColor=colors.HexColor('#333333')
        ))
        styles.add(ParagraphStyle(
            name='WordNote',
            fontName=VN_FONT_ITALIC,
            fontSize=15,
            leading=20,
            textColor=colors.HexColor('#666666')
        ))
        styles.add(ParagraphStyle(
            name='StrokeLabel',
            fontName=VN_FONT_BOLD,
            fontSize=11,
            leading=14,
            textColor=colors.HexColor('#2E7D32'),
            spaceBefore=6,
            spaceAfter=4
        ))
        
        story = []
        
        # 1. BUILD COVER PAGE
        if req.options.show_cover:
            story.append(Spacer(1, 4*cm))
            # Border frame
            story.append(Paragraph("SỔ TAY TẬP VIẾT CHỮ HÁN", styles['CoverTitle']))
            story.append(Spacer(1, 0.5*cm))
            story.append(Paragraph("Luyện Tập Viết Chữ Điền (Tianzige)", styles['CoverSubtitle']))
            
            story.append(Spacer(1, 2*cm))
            story.append(Paragraph("“温故而知新，可以为师矣。”", styles['CoverQuote']))
            story.append(Paragraph("(Ôn lại việc cũ để hiểu biết thêm việc mới)", styles['CoverSubtitle']))
            
            story.append(Spacer(1, 4*cm))
            branding_name = req.options.branding_name
            branding_line = f"{branding_name}<br/>" if branding_name else ""
            metadata_html = f"""
            <b>Sổ tay:</b> {req.title}<br/>
            <b>Số lượng từ:</b> {len(req.words)} từ vựng<br/>
            <b>Ngày tạo:</b> {datetime.now().strftime('%d/%m/%Y')}<br/>
            {branding_line}
            """
            story.append(Paragraph(metadata_html, styles['CoverMetadata']))
            story.append(PageBreak())
            
        # 2. BUILD WORKBOOK BLOCKS
        for index, word in enumerate(req.words):
            raw_vocab = word.vocabulary.strip()
            # Filter vocabulary to only Chinese characters
            hanzi_list = [c for c in raw_vocab if '\u4e00' <= c <= '\u9fff']
            if not hanzi_list:
                # Fallback to characters if no Hanzi found (just in case)
                hanzi_list = list(raw_vocab)
                
            pinyin_list = align_pinyin(hanzi_list, word.pinyin)
            length = len(hanzi_list)
            
            # Custom formatting:
            header_text = f"<font face=\"{VN_FONT_BOLD}\" size=\"25\">{index + 1}.</font> &nbsp;<font face=\"{ACTIVE_FONT}\" size=\"25\">{raw_vocab}</font>"
            if req.options.show_pinyin and word.pinyin:
                header_text += f"<br/><font face=\"{VN_FONT}\" size=\"16\">[{word.pinyin}]</font>"
            if req.options.show_meaning and word.meaning:
                header_text += f"<br/><font face=\"{VN_FONT_ITALIC}\" size=\"15\">({word.meaning})</font>"
                
            header_flowable = Paragraph(header_text, styles['WordInfo'])
            header_spacer = Spacer(1, 0.15*cm)
            
            # Find unique hanzi for duplicate check
            unique_hanzi = []
            for c in hanzi_list:
                if '\u4e00' <= c <= '\u9fff' and c not in unique_hanzi:
                    unique_hanzi.append(c)
                    
            if req.options.stroke_by_stroke:
                cols = 14
                grid_size = (16.0 / 14.0) * cm
                
                stroke_elements = []
                decomposed_strokes = []
                
                # 1. Build stroke deconstruction elements
                for char in unique_hanzi:
                    stroke_data = get_char_stroke_data(char)
                    if stroke_data and 'strokes' in stroke_data:
                        S = len(stroke_data['strokes'])
                        if S >= 1:
                            decomposed_strokes.append(S)
                            char_elements = []
                            char_elements.append(Paragraph(f"Nét chữ \"<font face=\"{ACTIVE_FONT}\">{char}</font>\":", styles['StrokeLabel']))
                            
                            M = min(S, 27)
                            # Row 1
                            row1_steps = [k for k in range(1, min(M, 14) + 1)]
                            row1_steps += [None] * (14 - len(row1_steps))
                            r1 = TianzigeFlowable([' '] * 14, [''] * 14, grid_size, is_trace=False, 
                                                 grid_color=req.options.grid_color, font_name=ACTIVE_FONT,
                                                 stroke_data=stroke_data['strokes'], stroke_steps=row1_steps)
                            r1.hAlign = 'CENTER'
                            char_elements.append(r1)
                            char_elements.append(Spacer(1, 0.1 * cm))
                            
                            # Row 2
                            if M > 14:
                                row2_steps = [k for k in range(15, M + 1)]
                                row2_steps += [None] * (14 - len(row2_steps))
                            else:
                                row2_steps = [None] * 14
                                
                            r2 = TianzigeFlowable([' '] * 14, [''] * 14, grid_size, is_trace=False,
                                                 grid_color=req.options.grid_color, font_name=ACTIVE_FONT,
                                                 stroke_data=stroke_data['strokes'], stroke_steps=row2_steps)
                            r2.hAlign = 'CENTER'
                            char_elements.append(r2)
                            char_elements.append(Spacer(1, 0.1 * cm))
                            
                            # Row 3 (empty row)
                            r3 = TianzigeFlowable([' '] * 14, [''] * 14, grid_size, is_trace=False,
                                                 grid_color=req.options.grid_color, font_name=ACTIVE_FONT)
                            r3.hAlign = 'CENTER'
                            char_elements.append(r3)
                            
                            stroke_elements.append((char, char_elements))
                            
                # 2. Build complete sentence elements
                sentence_elements = []
                sentence_elements.append(Paragraph("Viết câu hoàn chỉnh:", styles['StrokeLabel']))
                
                # Split sentence characters into chunks of 14 columns
                chunks_chars = []
                chunks_pinyins = []
                for offset in range(0, length, cols):
                    chunk_c = hanzi_list[offset:offset+cols]
                    chunk_p = pinyin_list[offset:offset+cols]
                    chunks_chars.append(chunk_c + [' '] * (cols - len(chunk_c)))
                    chunks_pinyins.append(chunk_p + [''] * (cols - len(chunk_p)))
                    
                for chunk_idx in range(len(chunks_chars)):
                    if chunk_idx > 0:
                        sentence_elements.append(Spacer(1, 0.3 * cm))
                        
                    chunk_c = chunks_chars[chunk_idx]
                    chunk_p = chunks_pinyins[chunk_idx]
                    
                    if req.options.extra_rows == 0:
                        cr1 = TianzigeFlowable(chunk_c, chunk_p, grid_size, is_trace=True, grid_color=req.options.grid_color, font_name=ACTIVE_FONT)
                        cr1.hAlign = 'CENTER'
                        cr2 = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT)
                        cr2.hAlign = 'CENTER'
                        cr3 = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT)
                        cr3.hAlign = 'CENTER'
                        
                        sentence_elements.extend([cr1, Spacer(1, 0.1 * cm), cr2, Spacer(1, 0.1 * cm), cr3])
                    else:
                        for pair_idx in range(req.options.extra_rows):
                            cr_trace = TianzigeFlowable(chunk_c, chunk_p, grid_size, is_trace=True, grid_color=req.options.grid_color, font_name=ACTIVE_FONT)
                            cr_trace.hAlign = 'CENTER'
                            cr_empty = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT)
                            cr_empty.hAlign = 'CENTER'
                            
                            sentence_elements.extend([cr_trace, Spacer(1, 0.1 * cm), cr_empty])
                            if pair_idx < req.options.extra_rows - 1:
                                sentence_elements.append(Spacer(1, 0.1 * cm))
                                
                # Estimate block height
                has_meaning = bool(word.meaning)
                has_note = bool(word.note)
                total_height = estimate_block_height(
                    length, 
                    req.options.extra_rows, 
                    req.options.show_pinyin, 
                    req.options.show_meaning, 
                    req.options.show_notes, 
                    has_meaning, 
                    has_note,
                    stroke_by_stroke=True,
                    decomposed_strokes=decomposed_strokes
                )
                
                if total_height <= 23.5 * cm:
                    all_elements = []
                    all_elements.append(header_flowable)
                    all_elements.append(header_spacer)
                    for char, char_el in stroke_elements:
                        all_elements.extend(char_el)
                        all_elements.append(Spacer(1, 0.3 * cm))
                    all_elements.extend(sentence_elements)
                    
                    if req.options.show_notes and word.note:
                        all_elements.append(Spacer(1, 0.15 * cm))
                        all_elements.append(Paragraph(f"({word.note})", styles['WordNote']))
                        
                    all_elements.append(Spacer(1, 0.7 * cm))
                    story.append(KeepTogether(all_elements))
                else:
                    unit1_elements = []
                    unit1_elements.append(header_flowable)
                    unit1_elements.append(header_spacer)
                    
                    start_char_idx = 0
                    if stroke_elements:
                        unit1_elements.extend(stroke_elements[0][1])
                        start_char_idx = 1
                        
                    story.append(KeepTogether(unit1_elements))
                    
                    for char_idx in range(start_char_idx, len(stroke_elements)):
                        story.append(KeepTogether([Spacer(1, 0.3 * cm)] + stroke_elements[char_idx][1]))
                        
                    sent_container = [Spacer(1, 0.3 * cm)] + sentence_elements
                    if req.options.show_notes and word.note:
                        sent_container.append(Spacer(1, 0.15 * cm))
                        sent_container.append(Paragraph(f"({word.note})", styles['WordNote']))
                    sent_container.append(Spacer(1, 0.7 * cm))
                    story.append(KeepTogether(sent_container))
            else:
                # Setup columns and grid size based on length
                if length <= 3:
                    grid_size = 2.0 * cm
                    cols = 8
                    chunks_chars = [hanzi_list + [' '] * (cols - length)]
                    chunks_pinyins = [pinyin_list + [''] * (cols - length)]
                else:
                    grid_size = (16.0 / 14.0) * cm
                    cols = 14
                    chunks_chars = []
                    chunks_pinyins = []
                    for offset in range(0, length, cols):
                        chunk_c = hanzi_list[offset:offset+cols]
                        chunk_p = pinyin_list[offset:offset+cols]
                        chunks_chars.append(chunk_c + [' '] * (cols - len(chunk_c)))
                        chunks_pinyins.append(chunk_p + [''] * (cols - len(chunk_p)))
                
                # Estimate block height
                has_meaning = bool(word.meaning)
                has_note = bool(word.note)
                total_height = estimate_block_height(
                    length, 
                    req.options.extra_rows, 
                    req.options.show_pinyin, 
                    req.options.show_meaning, 
                    req.options.show_notes, 
                    has_meaning, 
                    has_note
                )
                
                if total_height <= 23.5 * cm:
                    # Keep the whole block together on a single page
                    all_elements = []
                    all_elements.append(header_flowable)
                    all_elements.append(header_spacer)
                    
                    # Add grids for each chunk
                    for chunk_idx in range(len(chunks_chars)):
                        if chunk_idx > 0:
                            all_elements.append(Spacer(1, 0.3 * cm))
                        
                        chunk_c = chunks_chars[chunk_idx]
                        chunk_p = chunks_pinyins[chunk_idx]
                        
                        if req.options.extra_rows == 0:
                            r1 = TianzigeFlowable(chunk_c, chunk_p, grid_size, is_trace=True, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=req.options.show_pinyin)
                            r1.hAlign = 'CENTER'
                            r2 = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=False)
                            r2.hAlign = 'CENTER'
                            r3 = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=False)
                            r3.hAlign = 'CENTER'
                            
                            all_elements.extend([r1, Spacer(1, 0.1 * cm), r2, Spacer(1, 0.1 * cm), r3])
                        else:
                            for pair_idx in range(req.options.extra_rows):
                                r_trace = TianzigeFlowable(chunk_c, chunk_p, grid_size, is_trace=True, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=req.options.show_pinyin)
                                r_trace.hAlign = 'CENTER'
                                r_empty = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=False)
                                r_empty.hAlign = 'CENTER'
                                
                                all_elements.extend([r_trace, Spacer(1, 0.1 * cm), r_empty])
                                if pair_idx < req.options.extra_rows - 1:
                                    all_elements.append(Spacer(1, 0.1 * cm))
                                    
                    if req.options.show_notes and word.note:
                        all_elements.append(Spacer(1, 0.15 * cm))
                        all_elements.append(Paragraph(f"({word.note})", styles['WordNote']))
                        
                    all_elements.append(Spacer(1, 0.7 * cm))
                    story.append(KeepTogether(all_elements))
                    
                else:
                    # Split flowables into smaller KeepTogether units to prevent layout break
                    unit1_elements = []
                    unit1_elements.append(header_flowable)
                    unit1_elements.append(header_spacer)
                    
                    chunk_c = chunks_chars[0]
                    chunk_p = chunks_pinyins[0]
                    
                    if req.options.extra_rows == 0:
                        r1 = TianzigeFlowable(chunk_c, chunk_p, grid_size, is_trace=True, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=req.options.show_pinyin)
                        r1.hAlign = 'CENTER'
                        r2 = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=False)
                        r2.hAlign = 'CENTER'
                        r3 = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=False)
                        r3.hAlign = 'CENTER'
                        
                        unit1_elements.extend([r1, Spacer(1, 0.1 * cm), r2, Spacer(1, 0.1 * cm), r3])
                        story.append(KeepTogether(unit1_elements))
                        
                        # Subsequent chunks (if any)
                        for chunk_idx in range(1, len(chunks_chars)):
                            c_elements = []
                            c_elements.append(Spacer(1, 0.3 * cm))
                            
                            cc_c = chunks_chars[chunk_idx]
                            cc_p = chunks_pinyins[chunk_idx]
                            
                            cr1 = TianzigeFlowable(cc_c, cc_p, grid_size, is_trace=True, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=req.options.show_pinyin)
                            cr1.hAlign = 'CENTER'
                            cr2 = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=False)
                            cr2.hAlign = 'CENTER'
                            cr3 = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=False)
                            cr3.hAlign = 'CENTER'
                            
                            c_elements.extend([cr1, Spacer(1, 0.1 * cm), cr2, Spacer(1, 0.1 * cm), cr3])
                            
                            if chunk_idx == len(chunks_chars) - 1 and req.options.show_notes and word.note:
                                c_elements.append(Spacer(1, 0.15 * cm))
                                c_elements.append(Paragraph(f"({word.note})", styles['WordNote']))
                            
                            c_elements.append(Spacer(1, 0.7 * cm))
                            story.append(KeepTogether(c_elements))
                            
                        if len(chunks_chars) == 1 and req.options.show_notes and word.note:
                            story.append(KeepTogether([
                                Spacer(1, 0.15 * cm),
                                Paragraph(f"({word.note})", styles['WordNote']),
                                Spacer(1, 0.7 * cm)
                            ]))
                        elif len(chunks_chars) == 1:
                            story.append(Spacer(1, 0.7 * cm))
                    else:
                        # First pair of Chunk 0 goes to Unit 1
                        r_trace = TianzigeFlowable(chunk_c, chunk_p, grid_size, is_trace=True, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=req.options.show_pinyin)
                        r_trace.hAlign = 'CENTER'
                        r_empty = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=False)
                        r_empty.hAlign = 'CENTER'
                        
                        unit1_elements.extend([r_trace, Spacer(1, 0.1 * cm), r_empty])
                        
                        has_more_content = (req.options.extra_rows > 1) or (len(chunks_chars) > 1) or (req.options.show_notes and word.note)
                        if not has_more_content:
                            unit1_elements.append(Spacer(1, 0.7 * cm))
                            
                        story.append(KeepTogether(unit1_elements))
                        
                        # Subsequent pairs and chunks
                        for chunk_idx in range(len(chunks_chars)):
                            chunk_c = chunks_chars[chunk_idx]
                            chunk_p = chunks_pinyins[chunk_idx]
                            
                            start_pair = 1 if chunk_idx == 0 else 0
                            for pair_idx in range(start_pair, req.options.extra_rows):
                                pair_elements = []
                                if chunk_idx > 0 and pair_idx == 0:
                                    pair_elements.append(Spacer(1, 0.3 * cm))
                                else:
                                    pair_elements.append(Spacer(1, 0.1 * cm))
                                    
                                cr_trace = TianzigeFlowable(chunk_c, chunk_p, grid_size, is_trace=True, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=req.options.show_pinyin)
                                cr_trace.hAlign = 'CENTER'
                                cr_empty = TianzigeFlowable([' '] * cols, [''] * cols, grid_size, is_trace=False, grid_color=req.options.grid_color, font_name=ACTIVE_FONT, show_pinyin=False)
                                cr_empty.hAlign = 'CENTER'
                                
                                pair_elements.extend([cr_trace, Spacer(1, 0.1 * cm), cr_empty])
                                
                                is_last_pair = (chunk_idx == len(chunks_chars) - 1) and (pair_idx == req.options.extra_rows - 1)
                                if is_last_pair:
                                    if req.options.show_notes and word.note:
                                        pair_elements.append(Spacer(1, 0.15 * cm))
                                        pair_elements.append(Paragraph(f"({word.note})", styles['WordNote']))
                                    pair_elements.append(Spacer(1, 0.7 * cm))
                                    
                                story.append(KeepTogether(pair_elements))
            
        # 2B. APPEND EMPTY PRACTICE PAGES
        if req.options.empty_pages and req.options.empty_pages > 0:
            if req.options.empty_page_grid_size == "2.0":
                use_big_grids = True
            elif req.options.empty_page_grid_size == "1.0":
                use_big_grids = False
            else: # auto
                cjk_lengths = []
                for w in req.words:
                    raw_vocab = w.vocabulary.strip()
                    hanzi_list = [c for c in raw_vocab if '\u4e00' <= c <= '\u9fff']
                    if not hanzi_list:
                        hanzi_list = list(raw_vocab)
                    cjk_lengths.append(len(hanzi_list))
                
                avg_len = sum(cjk_lengths) / len(cjk_lengths)
                use_big_grids = avg_len <= 3
                
            if use_big_grids:
                grid_size = 2.0 * cm
                cols = 8
                rows = 9
            else:
                grid_size = (16.0 / 14.0) * cm
                cols = 14
                rows = 17
                
            for p_idx in range(req.options.empty_pages):
                story.append(PageBreak())
                
                practice_title_style = ParagraphStyle(
                    name=f'PracticeTitle_{p_idx}',
                    fontName=VN_FONT_BOLD,
                    fontSize=12,
                    leading=14,
                    textColor=colors.HexColor('#2E7D32'),
                    spaceAfter=10
                )
                
                practice_elements = []
                practice_elements.append(Paragraph(f"Trang Luyện Viết Tự Do - Trang {p_idx + 1}", practice_title_style))
                
                for _ in range(rows - 1):
                    empty_grid = TianzigeFlowable(
                        chars=[' '] * cols,
                        pinyins=[''] * cols,
                        grid_size=grid_size,
                        is_trace=False,
                        grid_color=req.options.grid_color,
                        font_name=ACTIVE_FONT,
                        show_pinyin=False
                    )
                    empty_grid.hAlign = 'CENTER'
                    practice_elements.append(empty_grid)
                    practice_elements.append(Spacer(1, 0.1*cm))
                
                empty_grid = TianzigeFlowable(
                    chars=[' '] * cols,
                    pinyins=[''] * cols,
                    grid_size=grid_size,
                    is_trace=False,
                    grid_color=req.options.grid_color,
                    font_name=ACTIVE_FONT,
                    show_pinyin=False
                )
                empty_grid.hAlign = 'CENTER'
                practice_elements.append(empty_grid)
                
                story.append(KeepTogether(practice_elements))

        # 3. BUILD DOCUMENT
        def on_init(canvas_obj, doc_obj):
            canvas_obj.show_cover = req.options.show_cover
            canvas_obj.notebook_title = req.title
            canvas_obj.branding_name = req.options.branding_name
            
        doc.build(story, canvasmaker=NumberedCanvas, onFirstPage=on_init, onLaterPages=on_init)
        
        # 4. RESET STREAM POINTER TO START (CRITICAL!)
        buffer.seek(0)
        
        return StreamingResponse(
            buffer, 
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=so-tay-tap-viet.pdf"
            }
        )
        
    except Exception as e:
        logger.exception("Error rendering PDF")
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống khi tạo PDF: {str(e)}")

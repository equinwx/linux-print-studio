#!/usr/bin/env python3
import sys
import os
import shutil
import zipfile
import copy
import datetime
import io
import time
import subprocess
from collections import OrderedDict
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QFileDialog, QListWidget, 
                             QLabel, QSpinBox, QGraphicsView, QGraphicsScene, 
                             QListWidgetItem, QGraphicsRectItem, QComboBox, QCheckBox,
                             QTabWidget, QFormLayout, QListView, QMessageBox, 
                             QMenu, QGraphicsPixmapItem, QInputDialog, QTreeView,
                             QScrollArea)
from PyQt6.QtGui import (QPixmap, QPainter, QColor, QIcon, QKeySequence, 
                         QShortcut, QPageSize, QPageLayout, QFont, QImage, QPen,
                         QDrag, QFileSystemModel, QImageReader, QTextDocument)
from PyQt6.QtCore import (Qt, QRectF, QSize, QSettings, QSizeF, QMimeData, QPoint, 
                         QDir, QTimer, QRunnable, QThreadPool, pyqtSignal, QObject, QMarginsF)
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog, QPrinterInfo

from PIL import Image, ImageEnhance, ImageOps, ImageFilter
try:
    from PIL import ImageCms
    HAS_CMS = True
except ImportError: HAS_CMS = False
try:
    import fitz
    HAS_FITZ = True
except ImportError: HAS_FITZ = False
try:
    import pypdfium2
    HAS_PYPDFIUM = True
except ImportError: HAS_PYPDFIUM = False

CONFIG = {
    "DEFAULT_THEME": "dark",
    "UI_FONT_SIZE": 13,
    "LEFT_PANEL_WIDTH": 280,
    "RIGHT_PANEL_WIDTH": 325,
    "ENABLE_TERMINAL_LOGS": True,
    "CANVAS_PADDING": 140,
    "ZOOM_STEP": 1.15,
    "DARK_PAPER_TINT": "#CBD5E1",
    "MAX_LIVE_DPI": 600,
    "PIXMAP_CACHE_LIMIT": 64,
    "THUMBNAIL_CACHE_LIMIT": 256,
    "MAX_UNDO_HISTORY": 50,
    "DEBOUNCE_INTERVAL_MS": 40,
    "DEFAULT_PAPER_SIZE": 0,
    "DEFAULT_PHOTO_SIZE": 5,
    "DEFAULT_MARGIN_MM": 10,
    "DEFAULT_SPACING_MM": 5,
    "DEFAULT_BORDERLESS": False,
    "DEFAULT_FIT_MODE": 0,
    "DEFAULT_SHARPENING": 0,
    "DEFAULT_DOC_DPI": 600,
    "DEFAULT_TXT_FONT": "Monospace",
    "DEFAULT_TXT_FONT_SIZE": 10,
    "THUMBNAIL_SIZE": 76,
    "MOUSE_CROP_SENSITIVITY": 0.003,
    "CROP_NUDGE_STEP": 0.04,
    "CROP_NUDGE_MICRO_STEP": 0.01,
}

DOC_CACHE_DIR = f"/tmp/photoprint_doc_cache_{os.getuid()}"
os.makedirs(DOC_CACHE_DIR, exist_ok=True)
IMG_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')
TEXT_EXTENSIONS = ('.txt', '.text', '.log', '.md')
OFFICE_EXTENSIONS = ('.pdf', '.docx', '.doc', '.odt', '.rtf')
DOC_EXTENSIONS = OFFICE_EXTENSIONS + TEXT_EXTENSIONS
ALL_VALID_EXTENSIONS = IMG_EXTENSIONS + DOC_EXTENSIONS

def log_event(message):
    if CONFIG["ENABLE_TERMINAL_LOGS"]:
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def is_doc_file(filepath):
    return filepath.lower().endswith(DOC_EXTENSIONS)

def convert_txt_to_pdf_fast(txt_path, target_pdf, font_family="Monospace", font_size=10):
    try:
        with open(txt_path, 'r', encoding='utf-8', errors='replace') as f: content = f.read()
    except Exception as e: content = f"Error reading text file: {e}"
    doc = QTextDocument(); font = QFont(font_family, font_size)
    if "mono" in font_family.lower(): font.setStyleHint(QFont.StyleHint.Monospace)
    elif "serif" in font_family.lower(): font.setStyleHint(QFont.StyleHint.Serif)
    else: font.setStyleHint(QFont.StyleHint.SansSerif)
    doc.setDefaultFont(font); doc.setPageSize(QSizeF(595.28, 841.89)); doc.setPlainText(content)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat); printer.setOutputFileName(target_pdf)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4)); printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    doc.print(printer)

def ensure_pdf_converted(doc_path, txt_font="Monospace", txt_size=10):
    lower = doc_path.lower()
    if lower.endswith('.pdf'): return doc_path
    try: mtime = os.path.getmtime(doc_path)
    except OSError: mtime = 0
    target_pdf = os.path.join(DOC_CACHE_DIR, f"conv_{abs(hash(doc_path))}_{int(mtime)}_{txt_font}_{txt_size}.pdf")
    if os.path.exists(target_pdf): return target_pdf
    if lower.endswith(TEXT_EXTENSIONS):
        try:
            convert_txt_to_pdf_fast(doc_path, target_pdf, txt_font, txt_size)
            if os.path.exists(target_pdf): return target_pdf
        except Exception as e: log_event(f"Text conversion failed: {e}")
    try:
        subprocess.run(['libreoffice', '--headless', '--convert-to', 'pdf', '--outdir', DOC_CACHE_DIR, doc_path], capture_output=True, text=True, timeout=20)
        stem_name = os.path.splitext(os.path.basename(doc_path))[0] + ".pdf"
        generated_pdf = os.path.join(DOC_CACHE_DIR, stem_name)
        if os.path.exists(generated_pdf):
            if generated_pdf != target_pdf: os.replace(generated_pdf, target_pdf)
            return target_pdf
    except Exception as e: log_event(f"LibreOffice conversion failed: {e}")
    return None

def get_document_page_count(filepath):
    pdf_path = ensure_pdf_converted(filepath)
    if not pdf_path or not os.path.exists(pdf_path): return 1
    if HAS_FITZ:
        try:
            doc = fitz.open(pdf_path); cnt = len(doc); doc.close(); return cnt
        except Exception: pass
    if HAS_PYPDFIUM:
        try:
            doc = pypdfium2.PdfDocument(pdf_path); cnt = len(doc); doc.close(); return cnt
        except Exception: pass
    try:
        res = subprocess.run(['pdfinfo', pdf_path], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            if line.startswith('Pages:'): return int(line.split(':')[1].strip())
    except Exception: pass
    return 1

def get_document_page_size_mm(filepath, page_num=0):
    pdf_path = ensure_pdf_converted(filepath)
    if not pdf_path or not os.path.exists(pdf_path): return 210.0, 297.0
    if HAS_FITZ:
        try:
            doc = fitz.open(pdf_path)
            if page_num < len(doc):
                w, h = round(doc.load_page(page_num).rect.width * 25.4 / 72.0, 1), round(doc.load_page(page_num).rect.height * 25.4 / 72.0, 1)
                doc.close(); return w, h
            doc.close()
        except Exception: pass
    if HAS_PYPDFIUM:
        try:
            pdf = pypdfium2.PdfDocument(pdf_path)
            if page_num < len(pdf):
                page = pdf.get_page(page_num); w_pt, h_pt = page.get_size()
                page.close(); pdf.close(); return round(w_pt * 25.4 / 72.0, 1), round(h_pt * 25.4 / 72.0, 1)
            pdf.close()
        except Exception: pass
    try:
        res = subprocess.run(['pdfinfo', '-f', str(page_num + 1), '-l', str(page_num + 1), pdf_path], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            if 'size:' in line:
                parts = line.split(':')[1].strip().split()
                return round(float(parts[0]) * 25.4 / 72.0, 1), round(float(parts[2]) * 25.4 / 72.0, 1)
    except Exception: pass
    return 210.0, 297.0

def render_document_page(filepath, page_num=0, dpi=300, txt_font="Monospace", txt_size=10):
    pdf_path = ensure_pdf_converted(filepath, txt_font, txt_size)
    if not pdf_path or not os.path.exists(pdf_path): return Image.new("RGBA", (800, 1100), (255, 255, 255, 255))
    if HAS_FITZ:
        try:
            doc = fitz.open(pdf_path)
            if page_num < len(doc):
                pix = doc.load_page(page_num).get_pixmap(dpi=dpi)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("RGBA")
                doc.close(); return img
            doc.close()
        except Exception as e: log_event(f"PyMuPDF render error: {e}")
    if HAS_PYPDFIUM:
        try:
            pdf = pypdfium2.PdfDocument(pdf_path)
            if page_num < len(pdf):
                bitmap = pdf.get_page(page_num).render(scale=dpi / 72.0)
                img = bitmap.to_pil().convert("RGBA")
                page.close(); pdf.close(); return img
            pdf.close()
        except Exception as e: log_event(f"PyPdfium render error: {e}")
    try:
        prefix = os.path.join(DOC_CACHE_DIR, f"page_{os.getpid()}_{abs(hash(filepath))}_{page_num}")
        subprocess.run(['pdftoppm', '-png', '-r', str(dpi), '-f', str(page_num + 1), '-l', str(page_num + 1), pdf_path, prefix], capture_output=True, check=True, timeout=15)
        matches = [f for f in os.listdir(DOC_CACHE_DIR) if f.startswith(os.path.basename(prefix)) and f.endswith('.png')]
        if matches:
            out_png = os.path.join(DOC_CACHE_DIR, sorted(matches)[0])
            with Image.open(out_png) as im: img = im.convert("RGBA")
            os.remove(out_png); return img
    except Exception as e: log_event(f"pdftoppm render error: {e}")
    return Image.new("RGBA", (int(210 * dpi / 25.4), int(297 * dpi / 25.4)), (255, 255, 255, 255))

def process_image_pipeline(img_data, img_w_px, img_h_px, fit_mode, sharp_mode, soft_proof_active, icc_path, render_intent_text, is_monochrome=False, is_matte_simulation=False, render_dpi=300, doc_color_mode="Normal (Original)", txt_font="Monospace", txt_size=10):
    path = img_data['path']; page_num = img_data.get('page', 0); is_doc = is_doc_file(path)
    if is_doc: pil_source = render_document_page(path, page_num=page_num, dpi=render_dpi, txt_font=txt_font, txt_size=txt_size)
    else: pil_source = Image.open(path)
        
    try:
        pil_img = pil_source.convert("RGBA")
        crop_x, crop_y, zoom_scale = img_data.get('crop_x', 0.5), img_data.get('crop_y', 0.5), img_data.get('zoom', 1.0)
        
        is_fill = fit_mode.startswith("Fill")
        if is_doc and is_fill and crop_x == 0.5 and crop_y == 0.5: is_fill = False
        is_stretch = fit_mode.startswith("Stretch")
        
        sw, sh = pil_img.width, pil_img.height
        if is_stretch:
            pil_img = pil_img.resize((img_w_px, img_h_px), Image.Resampling.LANCZOS)
        else:
            b_fit = min(img_w_px / sw, img_h_px / sh)
            b_fill = max(img_w_px / sw, img_h_px / sh)
            S = (b_fill * zoom_scale) if is_fill else (b_fit * zoom_scale)
            
            crop_w, crop_h = max(1.0, img_w_px / S), max(1.0, img_h_px / S)
            left, top = (sw - crop_w) * crop_x, (sh - crop_h) * crop_y
            right, bottom = left + crop_w, top + crop_h
            
            if crop_w <= sw:
                if left < 0: left = 0; right = crop_w
                if right > sw: right = sw; left = sw - crop_w
            if crop_h <= sh:
                if top < 0: top = 0; bottom = crop_h
                if bottom > sh: bottom = sh; top = sh - crop_h
                    
            pil_img = pil_img.crop((int(left), int(top), int(right), int(bottom)))
            if is_fill:
                pil_img = pil_img.resize((img_w_px, img_h_px), Image.Resampling.LANCZOS)
            else:
                pil_img = ImageOps.pad(pil_img, (img_w_px, img_h_px), method=Image.Resampling.LANCZOS, color=(255, 255, 255, 0))

        if is_doc:
            if "High Contrast" in doc_color_mode or img_data.get('high_contrast', False):
                if pil_img.mode != 'RGBA': pil_img = pil_img.convert('RGBA')
                alpha = pil_img.split()[3]
                pil_img = ImageOps.grayscale(pil_img).point(lambda p: 255 if p > 185 else 0).convert("RGBA")
                pil_img.putalpha(alpha)
            elif "Invert" in doc_color_mode:
                if pil_img.mode != 'RGBA': pil_img = pil_img.convert('RGBA')
                r, g, b_ch, a = pil_img.split()
                pil_img = Image.merge("RGBA", (*ImageOps.invert(Image.merge("RGB", (r, g, b_ch))).split(), a))
            elif "Grayscale" in doc_color_mode or is_monochrome:
                if pil_img.mode != 'RGBA': pil_img = pil_img.convert('RGBA')
                alpha = pil_img.split()[3]
                pil_img = ImageOps.grayscale(pil_img).convert("RGBA")
                pil_img.putalpha(alpha)
        else:
            if pil_img.mode != 'RGBA': pil_img = pil_img.convert('RGBA')
            alpha = pil_img.split()[3]
            pil_rgb = pil_img.convert('RGB')
            
            if is_monochrome or img_data.get('gray', False): pil_rgb = ImageOps.grayscale(pil_rgb).convert("RGB")
            elif img_data.get('sepia', False): pil_rgb = ImageOps.colorize(ImageOps.grayscale(pil_rgb), black="#251304", white="#F3E8D0").convert("RGB")
            
            b, c, s = img_data.get('b', 1.0), img_data.get('c', 1.0), img_data.get('s', 1.0)
            if b != 1.0: pil_rgb = ImageEnhance.Brightness(pil_rgb).enhance(b)
            if c != 1.0: pil_rgb = ImageEnhance.Contrast(pil_rgb).enhance(c)
            if s != 1.0 and not (is_monochrome or img_data.get('gray', False)): pil_rgb = ImageEnhance.Color(pil_rgb).enhance(s)
            
            pil_img = pil_rgb.convert("RGBA")
            pil_img.putalpha(alpha)

        if "Low" in sharp_mode: pil_img = pil_img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=50, threshold=3))
        elif "Standard" in sharp_mode: pil_img = pil_img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=85, threshold=3))
        elif "High" in sharp_mode: pil_img = pil_img.filter(ImageFilter.UnsharpMask(radius=2.0, percent=125, threshold=2))

        if not is_doc and soft_proof_active and not is_monochrome:
            transformed = False
            if HAS_CMS and icc_path and os.path.isfile(icc_path):
                try:
                    icc_bytes = getattr(pil_source, 'info', {}).get('icc_profile')
                    in_profile = ImageCms.getOpenProfile(io.BytesIO(icc_bytes)) if icc_bytes else ImageCms.createProfile("sRGB")
                    intent_code = ImageCms.Intent.RELATIVE_COLORIMETRIC if "Relative" in render_intent_text else (ImageCms.Intent.SATURATION if "Saturation" in render_intent_text else (ImageCms.Intent.ABSOLUTE_COLORIMETRIC if "Absolute" in render_intent_text else ImageCms.Intent.PERCEPTUAL))
                    ImageCms.applyTransform(pil_img, ImageCms.buildProofTransform(in_profile, ImageCms.createProfile("sRGB"), ImageCms.getOpenProfile(icc_path), "RGBA", "RGBA", intent=intent_code, proofIntent=intent_code))
                    transformed = True
                except Exception as cms_err: log_event(f"CMS Fallback: {cms_err}")
            if not transformed and is_matte_simulation: pil_img = ImageEnhance.Brightness(ImageEnhance.Contrast(pil_img).enhance(0.92)).enhance(1.03)

        return QImage(pil_img.tobytes("raw", "RGBA"), pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888).copy()
    finally: pil_source.close()

class WorkerSignals(QObject):
    finished = pyqtSignal(int, int, tuple, QImage); failed = pyqtSignal(int, int, str)

class ImageRenderWorker(QRunnable):
    def __init__(self, generation, idx, img_data, img_w_px, img_h_px, fit_mode, sharp_mode, soft_proof_active, icc_path, render_intent_text, is_monochrome, is_matte_simulation, render_dpi, doc_color_mode, txt_font, txt_size, cache_key):
        super().__init__()
        self.signals = WorkerSignals(); self.generation = generation; self.idx = idx; self.img_data = img_data
        self.img_w_px = img_w_px; self.img_h_px = img_h_px; self.fit_mode = fit_mode; self.sharp_mode = sharp_mode
        self.soft_proof_active = soft_proof_active; self.icc_path = icc_path; self.render_intent_text = render_intent_text
        self.is_monochrome = is_monochrome; self.is_matte_simulation = is_matte_simulation; self.render_dpi = render_dpi
        self.doc_color_mode = doc_color_mode; self.txt_font = txt_font; self.txt_size = txt_size; self.cache_key = cache_key
    def run(self):
        try: self.signals.finished.emit(self.generation, self.idx, self.cache_key, process_image_pipeline(self.img_data, self.img_w_px, self.img_h_px, self.fit_mode, self.sharp_mode, self.soft_proof_active, self.icc_path, self.render_intent_text, self.is_monochrome, self.is_matte_simulation, self.render_dpi, self.doc_color_mode, self.txt_font, self.txt_size))
        except Exception as e: self.signals.failed.emit(self.generation, self.idx, str(e))

class ThumbnailSignals(QObject):
    ready = pyqtSignal(int, str, QPixmap)

class ThumbnailWorker(QRunnable):
    def __init__(self, generation, filepath, size, main_window):
        super().__init__()
        self.signals = ThumbnailSignals(); self.generation = generation; self.filepath = filepath; self.size = size; self.main_window = main_window
    def run(self):
        if self.generation != self.main_window.folder_generation: return
        try:
            if self.filepath.lower().endswith(IMG_EXTENSIONS):
                reader = QImageReader(self.filepath); reader.setAutoTransform(True); s = reader.size()
                if s.isValid():
                    s.scale(QSize(self.size, self.size), Qt.AspectRatioMode.KeepAspectRatio); reader.setScaledSize(s)
                    img = reader.read()
                    if not img.isNull(): self.signals.ready.emit(self.generation, self.filepath, QPixmap.fromImage(img))
            else:
                pil_thumb = render_document_page(self.filepath, page_num=0, dpi=72); pil_thumb.thumbnail((self.size, self.size), Image.Resampling.BILINEAR)
                qim = QImage(pil_thumb.tobytes("raw", "RGBA"), pil_thumb.width, pil_thumb.height, QImage.Format.Format_RGBA8888)
                self.signals.ready.emit(self.generation, self.filepath, QPixmap.fromImage(qim)); pil_thumb.close()
        except Exception: pass

class CanvasView(QGraphicsView):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window; self.setAcceptDrops(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing); self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor); self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        
        self.user_zoomed = False; self.drag_start_idx = None; self._is_panning_canvas = False
        self._interact_timer = QTimer(self); self._interact_timer.setSingleShot(True); self._interact_timer.setInterval(400)
        self._interact_timer.timeout.connect(self._commit_interaction)
        self._interact_idx = None; self._interact_item = None; self._interact_pil = None
        self._drag_start_pos = None; self._is_crop_nudging = False; self._zoom_pause_until = 0

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.user_zoomed and self.scene() and self.scene().sceneRect().width() > 0:
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _ensure_fast_preview_loaded(self, idx, search_pos=None):
        if self._interact_idx == idx and self._interact_pil is not None: return True
        pixmap_item = self.main_window.canvas_pixmap_items.get(idx)
        if not pixmap_item or not hasattr(pixmap_item, 'setPixmap'):
            if search_pos:
                for it in self.items(search_pos):
                    if hasattr(it, 'setPixmap') and it.data(0) is not None:
                        pixmap_item = it; idx = it.data(0); break
        if not pixmap_item: return False
            
        self._interact_idx = idx; self._interact_item = pixmap_item
        self.main_window.active_canvas_index = idx; self.main_window.update_selection_highlight()
        try:
            img_data = self.main_window.selected_images_for_print[idx]
            if is_doc_file(img_data['path']): return False
            with Image.open(img_data['path']) as src: src_pil = src.convert("RGBA")
            max_dim = max(src_pil.width, src_pil.height)
            if max_dim > 1600:
                scale = 1600.0 / max_dim
                src_pil = src_pil.resize((max(10, int(src_pil.width * scale)), max(10, int(src_pil.height * scale))), Image.Resampling.BILINEAR)
            self._interact_pil = src_pil; return True
        except Exception as e:
            self._interact_pil = None; self._interact_item = None; self._interact_idx = None; return False

    def _update_live_preview(self):
        if not (getattr(self, '_is_crop_nudging', False) and self._interact_item): return
        if self._interact_idx is None or self._interact_idx >= len(self.main_window.selected_images_for_print): return
        
        img_data = self.main_window.selected_images_for_print[self._interact_idx]
        cx, cy, zoom_scale = img_data.get('crop_x', 0.5), img_data.get('crop_y', 0.5), img_data.get('zoom', 1.0)
        
        try: tw, th = max(10, int(self._interact_item.boundingRect().width())), max(10, int(self._interact_item.boundingRect().height()))
        except RuntimeError: return

        if getattr(self, '_interact_pil', None) is not None:
            try:
                pw, ph, scale_up = tw, th, 1.0
                if max(pw, ph) > 800:
                    scale_up = 800.0 / max(pw, ph); pw = max(10, int(pw * scale_up)); ph = max(10, int(ph * scale_up))
                sw, sh = self._interact_pil.width, self._interact_pil.height
                
                global_fit = self.main_window.combo_fit_mode.currentText()
                item_fit_mode = img_data.get('fit_mode', global_fit)
                fit_mode = "Fit" if (is_doc_file(img_data['path']) and item_fit_mode.startswith("Fill") and cx == 0.5 and cy == 0.5) else item_fit_mode
                is_fill = fit_mode.startswith("Fill")

                b_fit = min(pw / sw, ph / sh); b_fill = max(pw / sw, ph / sh)
                S = (b_fill * zoom_scale) if is_fill else (b_fit * zoom_scale)
                
                cw, ch = max(1.0, pw / S), max(1.0, ph / S)
                l, t = (sw - cw) * cx, (sh - ch) * cy
                r, b = l + cw, t + ch
                
                if cw <= sw:
                    if l < 0: l = 0; r = cw
                    if r > sw: r = sw; l = sw - cw
                if ch <= sh:
                    if t < 0: t = 0; b = ch
                    if b > sh: b = sh; t = sh - ch
                        
                crp = self._interact_pil.crop((int(l), int(t), int(r), int(b)))
                
                if is_fill or fit_mode.startswith("Stretch"): crp = crp.resize((pw, ph), Image.Resampling.NEAREST)
                else: crp = ImageOps.pad(crp, (pw, ph), method=Image.Resampling.NEAREST, color=(255, 255, 255, 0))
                
                if crp.mode != 'RGBA': crp = crp.convert('RGBA')
                alpha = crp.split()[3]
                crp_rgb = crp.convert('RGB')
                
                if img_data.get('gray', False): crp_rgb = ImageOps.grayscale(crp_rgb).convert("RGB")
                elif img_data.get('sepia', False): crp_rgb = ImageOps.colorize(ImageOps.grayscale(crp_rgb), black="#251304", white="#F3E8D0").convert("RGB")
                
                br, ct, sa = img_data.get('b', 1.0), img_data.get('c', 1.0), img_data.get('s', 1.0)
                if br != 1.0: crp_rgb = ImageEnhance.Brightness(crp_rgb).enhance(br)
                if ct != 1.0: crp_rgb = ImageEnhance.Contrast(crp_rgb).enhance(ct)
                if sa != 1.0 and not img_data.get('gray', False): crp_rgb = ImageEnhance.Color(crp_rgb).enhance(sa)
                
                crp = crp_rgb.convert("RGBA")
                crp.putalpha(alpha)
                
                pix = QPixmap.fromImage(QImage(crp.tobytes("raw", "RGBA"), crp.width, crp.height, QImage.Format.Format_RGBA8888))
                if scale_up != 1.0: pix = pix.scaled(tw, th, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
                if hasattr(self._interact_item, 'setPixmap'): self._interact_item.setPixmap(pix)
                self.main_window.update_selected_label()
            except Exception as e: log_event(f"Live preview error: {e}")

    def _commit_interaction(self):
        if getattr(self, '_is_dragging_crop', False): return
        self._interact_pil = None; self._interact_item = None; self._interact_idx = None
        self.main_window.save_history_state(); self.main_window.update_canvas(reset_zoom=False)

    def wheelEvent(self, event):
        mods = event.modifiers()
        if mods == Qt.KeyboardModifier.ControlModifier:
            self.user_zoomed = True
            zoom_factor = CONFIG["ZOOM_STEP"] if event.angleDelta().y() > 0 else 1.0 / CONFIG["ZOOM_STEP"]
            old_pos = self.mapToScene(event.position().toPoint()); self.scale(zoom_factor, zoom_factor)
            self.translate((self.mapToScene(event.position().toPoint()) - old_pos).x(), (self.mapToScene(event.position().toPoint()) - old_pos).y()); return
            
        if (mods & Qt.KeyboardModifier.ShiftModifier) or (mods & Qt.KeyboardModifier.AltModifier):
            if time.time() < getattr(self, '_zoom_pause_until', 0): return event.accept()
            pos = event.position().toPoint(); item = self.itemAt(pos); idx = None
            if item and isinstance(item, QGraphicsPixmapItem) and item.data(0) is not None: idx = item.data(0)
            else:
                for it in self.items(pos):
                    if hasattr(it, 'setPixmap') and it.data(0) is not None: idx = it.data(0); break
            if idx is None or not self._ensure_fast_preview_loaded(idx, pos): return super().wheelEvent(event)
                
            img_data = self.main_window.selected_images_for_print[idx]
            if is_doc_file(img_data['path']): return event.accept()
            
            try:
                pixmap_item = self.main_window.canvas_pixmap_items.get(idx)
                if not pixmap_item: return event.accept()
                tw, th = max(10, pixmap_item.boundingRect().width()), max(10, pixmap_item.boundingRect().height())
            except RuntimeError: return event.accept()
                
            sw, sh = self._interact_pil.width, self._interact_pil.height
            b_fit = min(tw / sw, th / sh); b_fill = max(tw / sw, th / sh)
            t_zoom = b_fill / b_fit if b_fit > 0 else 1.0
            
            new_zoom = img_data.get('zoom', 1.0) * (1.10 ** (event.angleDelta().y() / 120.0))
            fit_mode = img_data.get('fit_mode', self.main_window.combo_fit_mode.currentText()); switched = False
            
            if fit_mode.startswith("Fit"):
                new_zoom = max(1.0, new_zoom)
                if new_zoom >= t_zoom:
                    img_data['fit_mode'] = "Fill (Crop to Fit - Default)"
                    new_zoom = new_zoom / t_zoom; switched = True
            elif fit_mode.startswith("Fill"):
                if new_zoom < 1.0:
                    img_data['fit_mode'] = "Fit (Letterbox Blank Edges)"
                    new_zoom = new_zoom * t_zoom; switched = True
                else: new_zoom = min(10.0, new_zoom)

            if switched: self._zoom_pause_until = time.time() + 0.2
            if new_zoom != img_data.get('zoom', 1.0):
                img_data['zoom'] = round(new_zoom, 3); self._is_crop_nudging = True
                self._update_live_preview(); self._interact_timer.start(400)
            return event.accept()
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        mods = event.modifiers()
        if (mods & Qt.KeyboardModifier.ShiftModifier) or (mods & Qt.KeyboardModifier.AltModifier):
            step = CONFIG["CROP_NUDGE_MICRO_STEP"] if (mods & Qt.KeyboardModifier.ControlModifier) else CONFIG["CROP_NUDGE_STEP"]
            if event.key() == Qt.Key.Key_Left: self.main_window.nudge_crop(-step, 0); return event.accept()
            elif event.key() == Qt.Key.Key_Right: self.main_window.nudge_crop(step, 0); return event.accept()
            elif event.key() == Qt.Key.Key_Up: self.main_window.nudge_crop(0, -step); return event.accept()
            elif event.key() == Qt.Key.Key_Down: self.main_window.nudge_crop(0, step); return event.accept()
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        pos = event.position().toPoint(); item = self.itemAt(pos)
        clicking_photo = item and item.data(0) is not None

        if event.button() == Qt.MouseButton.LeftButton and clicking_photo:
            idx = item.data(0); mods = event.modifiers()
            if (mods & Qt.KeyboardModifier.ShiftModifier) or (mods & Qt.KeyboardModifier.AltModifier):
                img_data = self.main_window.selected_images_for_print[idx]
                if not img_data.get('fit_mode', self.main_window.combo_fit_mode.currentText()).startswith("Fill"):
                    img_data['fit_mode'] = "Fill (Crop to Fit - Default)"

                if self._ensure_fast_preview_loaded(idx, pos):
                    self._is_crop_nudging = True; self._is_dragging_crop = True
                    self._drag_start_pos = pos; self.setCursor(Qt.CursorShape.SizeAllCursor); self._interact_timer.stop()
                    self.drag_start_idx = None 
                return event.accept()
            self.drag_start_pos = pos; self.drag_start_idx = idx
            self.main_window.active_canvas_index = idx; self.main_window.update_selection_highlight()
        elif event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and not clicking_photo):
            self._is_panning_canvas = True; self._pan_start_pos = event.pos(); self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if event.button() == Qt.MouseButton.LeftButton:
                self.drag_start_idx = None; self.main_window.active_canvas_index = None; self.main_window.update_selection_highlight()
            return event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, '_is_dragging_crop', False) and self._interact_item:
            curr_pos = event.position().toPoint(); delta = curr_pos - self._drag_start_pos; self._drag_start_pos = curr_pos
            if self._interact_idx is not None and self._interact_idx < len(self.main_window.selected_images_for_print):
                img_data = self.main_window.selected_images_for_print[self._interact_idx]
                curr_cx, curr_cy, zoom_scale = img_data.get('crop_x', 0.5), img_data.get('crop_y', 0.5), img_data.get('zoom', 1.0)
                
                sw, sh = self._interact_pil.width, self._interact_pil.height
                try: tw, th = max(10, int(self._interact_item.boundingRect().width())), max(10, int(self._interact_item.boundingRect().height()))
                except RuntimeError: return event.accept()
                
                fit_mode = img_data.get('fit_mode', self.main_window.combo_fit_mode.currentText())
                S = (max(tw / sw, th / sh) if fit_mode.startswith("Fill") else min(tw / sw, th / sh)) * zoom_scale
                
                sensitivity_x = 1.0 / (sw * S) if sw * S > 0 else 0.003
                sensitivity_y = 1.0 / (sh * S) if sh * S > 0 else 0.003
                
                img_data['crop_x'] = max(0.0, min(1.0, curr_cx - delta.x() * sensitivity_x))
                img_data['crop_y'] = max(0.0, min(1.0, curr_cy - delta.y() * sensitivity_y))
                self._update_live_preview()
            return event.accept()

        if getattr(self, '_is_panning_canvas', False):
            delta = event.pos() - self._pan_start_pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._pan_start_pos = event.pos()
            return event.accept()
            
        if event.buttons() & Qt.MouseButton.LeftButton and not getattr(self, '_is_dragging_crop', False):
            if hasattr(self, 'drag_start_pos') and getattr(self, 'drag_start_idx', None) is not None:
                pos = event.position().toPoint()
                if (pos - self.drag_start_pos).manhattanLength() > QApplication.startDragDistance():
                    drag = QDrag(self); mime = QMimeData(); mime.setText(f"swap:{self.drag_start_idx}"); drag.setMimeData(mime)
                    pixmap_item = self.main_window.canvas_pixmap_items.get(self.drag_start_idx)
                    if pixmap_item and hasattr(pixmap_item, 'pixmap') and not pixmap_item.pixmap().isNull():
                        pix = pixmap_item.pixmap().scaledToWidth(100, Qt.TransformationMode.SmoothTransformation)
                        drag.setPixmap(pix); drag.setHotSpot(QPoint(pix.width() // 2, pix.height() // 2))
                    self.drag_start_idx = None; drag.exec(Qt.DropAction.MoveAction); return
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        if getattr(self, '_is_dragging_crop', False):
            self._is_dragging_crop = False; self._is_crop_nudging = False; self.setCursor(Qt.CursorShape.ArrowCursor)
            self._commit_interaction(); return event.accept()
        if getattr(self, '_is_panning_canvas', False):
            self._is_panning_canvas = False; self.setCursor(Qt.CursorShape.ArrowCursor)
            return event.accept()
        self.drag_start_idx = None; super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.source() == self.main_window.gallery or (event.mimeData().hasText() and event.mimeData().text().startswith("swap:")): event.acceptProposedAction()
        else: super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.source() == self.main_window.gallery or (event.mimeData().hasText() and event.mimeData().text().startswith("swap:")): event.acceptProposedAction()
        else: super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasText() and event.mimeData().text().startswith("swap:"):
            src_idx = int(event.mimeData().text().split(":")[1])
            target_item = self.scene().itemAt(self.mapToScene(event.position().toPoint()), self.transform())
            if target_item and target_item.data(0) is not None:
                dst_idx = target_item.data(0)
                arr = self.main_window.selected_images_for_print
                arr[src_idx], arr[dst_idx] = arr[dst_idx], arr[src_idx]
                self.main_window.active_canvas_index = dst_idx
                self.main_window.save_history_state(); self.main_window.update_canvas(reset_zoom=False)
            event.acceptProposedAction()
        elif event.source() == self.main_window.gallery:
            item = self.main_window.gallery.currentItem()
            if item: self.main_window.import_file_to_canvas(item.data(Qt.ItemDataRole.UserRole)); event.acceptProposedAction()

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item and item.data(0) is not None:
            idx = item.data(0); data = self.main_window.selected_images_for_print[idx]
            is_doc = is_doc_file(data['path']); menu = QMenu(self)
            
            if is_doc:
                total_p, curr_p = data.get('total_pages', 1), data.get('page', 0)
                act_change_page = menu.addAction(f"📄 Change Document Page (Current: {curr_p + 1}/{total_p})...") if total_p > 1 else None
                act_fit_full = menu.addAction("📐 Fit to Full Page (1-up)"); act_rotate = menu.addAction("🔄 Rotate Page (90°)")
                act_toggle_hc = menu.addAction("🔲 Toggle High-Contrast Text (B&W)")
                menu.addSeparator(); act_reset_crop = menu.addAction("🎯 Reset Framing (Center)"); act_remove = menu.addAction("❌ Remove Document Page")
                
                action = menu.exec(event.globalPos()); state_changed = False
                if act_change_page and action == act_change_page:
                    chosen, ok = QInputDialog.getItem(self, "Select Document Page", "Display Page:", [f"Page {i+1}" for i in range(total_p)], curr_p, False)
                    if ok and chosen: data['page'] = int(chosen.split()[1]) - 1; state_changed = True
                elif action == act_fit_full:
                    self.main_window.combo_photo.setCurrentText("1 Image / Page (Full Sheet)")
                    state_changed = False
                elif action == act_rotate: data['landscape'] = not data.get('landscape', False); state_changed = True
                elif action == act_toggle_hc: data['high_contrast'] = not data.get('high_contrast', False); state_changed = True
                elif action == act_reset_crop: 
                    data['crop_x'] = 0.5; data['crop_y'] = 0.5; data['zoom'] = 1.0
                    if 'fit_mode' in data: del data['fit_mode']
                    state_changed = True
                elif action == act_remove: self.main_window.selected_images_for_print.pop(idx); self.main_window.active_canvas_index = None; state_changed = True
            else:
                size_menu = menu.addMenu("📐 Change Photo Size")
                for name, w, h in self.main_window.photo_presets:
                    if name != "Custom Size": size_menu.addAction(name)
                act_custom_size = size_menu.addAction("Set Custom Size (mm)...")
                menu.addSeparator(); act_reset_crop = menu.addAction("🎯 Reset Framing & Zoom"); menu.addSeparator()
                act_bright = menu.addAction("Brighten (+10%)"); act_dark = menu.addAction("Darken (-10%)")
                act_deepen = menu.addAction("Deepen (Contrast +10%)"); act_lighten = menu.addAction("Lighten (Contrast -10%)")
                act_sat_up = menu.addAction("Saturation (+15%)"); act_sat_down = menu.addAction("Desaturate (-15%)")
                menu.addSeparator(); act_gray = menu.addAction("Toggle Grayscale"); act_sepia = menu.addAction("Toggle Sepia")
                menu.addSeparator(); act_none = menu.addAction("Reset All Edits"); act_remove = menu.addAction("Remove Image")
                
                action = menu.exec(event.globalPos()); state_changed = False
                if action in size_menu.actions():
                    if action == act_custom_size:
                        curr_w, curr_h = data.get('w_code', 50), data.get('h_code', 50)
                        if curr_w < 0: curr_w, curr_h = 50, 50
                        new_w, ok1 = QInputDialog.getInt(self, "Custom Width", "Width in mm (10-500):", int(curr_w), 10, 500)
                        if ok1:
                            new_h, ok2 = QInputDialog.getInt(self, "Custom Height", "Height in mm (10-500):", int(curr_h), 10, 500)
                            if ok2: 
                                self.main_window.spin_custom_w.setValue(new_w)
                                self.main_window.spin_custom_h.setValue(new_h)
                                self.main_window.combo_photo.setCurrentText("Custom Size")
                                state_changed = False
                    else: 
                        self.main_window.combo_photo.setCurrentText(action.text())
                        state_changed = False
                elif action == act_reset_crop: 
                    data['crop_x'] = 0.5; data['crop_y'] = 0.5; data['zoom'] = 1.0
                    if 'fit_mode' in data: del data['fit_mode']
                    state_changed = True
                elif action == act_remove: self.main_window.selected_images_for_print.pop(idx); self.main_window.active_canvas_index = None; state_changed = True
                elif action == act_none:
                    self.main_window.selected_images_for_print[idx] = {
                        "path": data['path'], "page": 0, "total_pages": 1, "w_code": data.get('w_code', 50), "h_code": data.get('h_code', 50), 
                        "landscape": data.get('landscape', False), "b": 1.0, "c": 1.0, "s": 1.0, "gray": False, "sepia": False, "crop_x": 0.5, "crop_y": 0.5, "zoom": 1.0
                    }; state_changed = True
                elif action == act_bright: data['b'] += 0.1; state_changed = True
                elif action == act_dark: data['b'] = max(0.1, data['b'] - 0.1); state_changed = True
                elif action == act_deepen: data['c'] += 0.1; state_changed = True
                elif action == act_lighten: data['c'] = max(0.1, data['c'] - 0.1); state_changed = True
                elif action == act_sat_up: data['s'] += 0.15; state_changed = True
                elif action == act_sat_down: data['s'] = max(0.0, data['s'] - 0.15); state_changed = True
                elif action == act_gray: data['gray'] = not data['gray']; data['sepia'] = False; state_changed = True
                elif action == act_sepia: data['sepia'] = not data['sepia']; data['gray'] = False; state_changed = True
                
            if state_changed: self.main_window.save_history_state(); self.main_window.update_canvas(reset_zoom=False); self.main_window.update_selected_label()

class PhotoPrintApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui_initialized = False
        log_event("Application Initializing...")
        self.setWindowTitle("Linux Native Document & Photo Studio (Professional Workspace)")
        
        self.settings = QSettings("LinuxNativePrint", "PhotoApp")
        self.workspace_root = self.settings.value("workspace_root", os.path.expanduser("~/Pictures"))
        self.current_folder = self.workspace_root
        
        self.is_dark_mode = (CONFIG["DEFAULT_THEME"].lower() == "dark"); self.custom_icc_path = ""
        self.selected_images_for_print = []; self.history = []; self.history_index = -1; self.MAX_HISTORY = CONFIG["MAX_UNDO_HISTORY"]
        self.current_page = 0
        
        self.render_thread_pool = QThreadPool(self); self.render_thread_pool.setMaxThreadCount(max(2, os.cpu_count() or 4))
        self.thumb_thread_pool = QThreadPool(self); self.thumb_thread_pool.setMaxThreadCount(max(2, (os.cpu_count() or 4) // 2))

        self._render_generation = 0; self.canvas_pixmap_items = {}
        self.folder_generation = 0; self.gallery_items_by_path = {}; self.thumbnail_cache = OrderedDict(); self.MAX_THUMB_CACHE = CONFIG.get("THUMBNAIL_CACHE_LIMIT", 256)
        self.pixmap_cache = OrderedDict(); self.MAX_CACHE_SIZE = CONFIG["PIXMAP_CACHE_LIMIT"]
        
        self._layout_timer = QTimer(self); self._layout_timer.setSingleShot(True); self._layout_timer.setInterval(CONFIG["DEBOUNCE_INTERVAL_MS"])
        self._layout_timer.timeout.connect(lambda: self.trigger_layout_change(preserve_zoom=True))
        self._size_debounce_timer = QTimer(self); self._size_debounce_timer.setSingleShot(True); self._size_debounce_timer.setInterval(CONFIG["DEBOUNCE_INTERVAL_MS"])
        self._size_debounce_timer.timeout.connect(self.apply_global_photo_size)
        
        self.active_canvas_index = None; self.clipboard_image_data = None
        self.ruler_items = []; self.cell_border_items = []; self.crop_mark_items = []; self.paper_item = None; self.highlight_item = None
        self.paper_px_width = 0; self.paper_px_height = 0; self.canvas_dpi = 300
        
        self.initUI(); self.apply_theme()
        if os.path.isdir(self.workspace_root): self.load_images_from_folder(self.workspace_root)
        self.save_history_state(); self.ui_initialized = True; log_event("Studio workspace successfully ready.")
        
    def initUI(self):
        central_widget = QWidget(); main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8); main_layout.setSpacing(8)
        
        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel); left_panel.setFixedWidth(CONFIG.get("LEFT_PANEL_WIDTH", 280)) 
        left_layout.setContentsMargins(8, 8, 8, 8); left_layout.setSpacing(8)
        
        workspace_header = QHBoxLayout(); workspace_header.setSpacing(6)
        self.lbl_workspace = QLabel(f"{os.path.basename(self.workspace_root)}"); self.lbl_workspace.setStyleSheet("font-weight: bold; color: #38BDF8;")
        self.btn_up_folder = QPushButton("▲ Up"); self.btn_up_folder.setFixedWidth(56); self.btn_up_folder.clicked.connect(self.go_up_folder); self.btn_up_folder.setEnabled(False)
        btn_set_workspace = QPushButton("Set Root"); btn_set_workspace.clicked.connect(self.change_workspace)
        workspace_header.addWidget(self.lbl_workspace, stretch=1); workspace_header.addWidget(self.btn_up_folder); workspace_header.addWidget(btn_set_workspace)
        left_layout.addLayout(workspace_header)
        
        self.dir_model = QFileSystemModel(); self.dir_model.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs); self.dir_model.setRootPath(self.workspace_root)
        self.tree = QTreeView(); self.tree.setModel(self.dir_model); self.tree.setRootIndex(self.dir_model.index(self.workspace_root)); self.tree.setHeaderHidden(True)
        for i in range(1, 4): self.tree.hideColumn(i) 
        self.tree.clicked.connect(self.on_tree_clicked); left_layout.addWidget(self.tree, stretch=1)
        
        self.gallery = QListWidget(); self.gallery.setViewMode(QListView.ViewMode.IconMode)
        self.gallery.setGridSize(QSize(CONFIG["THUMBNAIL_SIZE"] + 4, CONFIG["THUMBNAIL_SIZE"] + 4)); self.gallery.setIconSize(QSize(CONFIG["THUMBNAIL_SIZE"], CONFIG["THUMBNAIL_SIZE"]))
        self.gallery.setUniformItemSizes(True); self.gallery.setResizeMode(QListView.ResizeMode.Adjust); self.gallery.setMovement(QListView.Movement.Static)
        self.gallery.setDragEnabled(True); self.gallery.setMinimumHeight(260)
        self.gallery.itemDoubleClicked.connect(lambda item: self.import_file_to_canvas(item.data(Qt.ItemDataRole.UserRole)))
        self.gallery.itemSelectionChanged.connect(self.update_selected_label); left_layout.addWidget(self.gallery, stretch=3)
        
        self.label_file_info = QLabel("Selected: None"); self.label_file_info.setStyleSheet("font-weight: bold; font-size: 11px;"); self.label_file_info.setWordWrap(True)
        left_layout.addWidget(self.label_file_info)

        tip_label = QLabel("Drag images or docs to Canvas.\nCtrl+Wheel: Zoom Canvas\nShift/Alt+Drag: Pan Image inside Cell\nShift+Wheel: Zoom Image inside Cell")
        tip_label.setStyleSheet("color: #64748B; font-size: 11px;"); left_layout.addWidget(tip_label)
        self.btn_clear = QPushButton("Clear Canvas"); self.btn_clear.clicked.connect(self.clear_canvas); left_layout.addWidget(self.btn_clear)

        center_panel = QWidget(); center_layout = QVBoxLayout(center_panel); center_layout.setContentsMargins(0, 0, 0, 0); center_layout.setSpacing(6)
        self.pagination_bar = QWidget(); page_bar_layout = QHBoxLayout(self.pagination_bar); page_bar_layout.setContentsMargins(10, 4, 10, 4)
        
        self.btn_prev_page = QPushButton("◀ Prev Sheet"); self.btn_prev_page.setFixedWidth(100); self.btn_prev_page.clicked.connect(self.prev_page)
        self.lbl_page_info = QLabel("Sheet 1 of 1"); self.lbl_page_info.setAlignment(Qt.AlignmentFlag.AlignCenter); self.lbl_page_info.setStyleSheet("font-weight: bold;")
        self.btn_next_page = QPushButton("Next Sheet ▶"); self.btn_next_page.setFixedWidth(100); self.btn_next_page.clicked.connect(self.next_page)
        
        page_bar_layout.addWidget(self.btn_prev_page); page_bar_layout.addStretch(); page_bar_layout.addWidget(self.lbl_page_info); page_bar_layout.addStretch(); page_bar_layout.addWidget(self.btn_next_page)
        center_layout.addWidget(self.pagination_bar)
        
        self.view = CanvasView(self); self.scene = QGraphicsScene(); self.view.setScene(self.scene); center_layout.addWidget(self.view, stretch=1)

        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel); right_panel.setFixedWidth(CONFIG["RIGHT_PANEL_WIDTH"])
        right_layout.setContentsMargins(8, 8, 8, 8); right_layout.setSpacing(8)

        theme_layout = QHBoxLayout()
        self.btn_theme = QPushButton("🌙 Dark Mode" if not self.is_dark_mode else "☀️ Light Mode"); self.btn_theme.clicked.connect(self.toggle_theme)
        theme_layout.addStretch(); theme_layout.addWidget(self.btn_theme); right_layout.addLayout(theme_layout)

        self.tabs = QTabWidget(); right_layout.addWidget(self.tabs)
        
        tab_photo_widget = QWidget(); tab_photo_widget.setObjectName("scrollBg"); self.layout_photo = QFormLayout(tab_photo_widget)
        self.layout_photo.setContentsMargins(6, 8, 6, 8); self.layout_photo.setSpacing(10)

        self.combo_photo = QComboBox()
        self.photo_presets = [
            ("1 Image / Page (Full Sheet)", -1, -1), ("2 Images per Page", -2, -2), ("4 Images per Page", -4, -4), ("6 Images per Page", -6, -6),
            ("Stamp Photo (20 x 25 mm)", 20, 25), ("Small ID (25 x 30 mm)", 25, 30), ("Medium ID (30 x 40 mm)", 30, 40),
            ("Passport - Standard (35 x 45 mm)", 35, 45), ("Passport - US (51 x 51 mm)", 51, 51), ("Passport - India (35 x 35 mm)", 35, 35),
            ("Wallet Size (64 x 89 mm)", 64, 89), ("Square 4x4 in (102 x 102 mm)", 102, 102), ("Standard 4x6 in (102 x 152 mm)", 102, 152), ("Custom Size", 0, 0)
        ]
        for name, w, h in self.photo_presets: self.combo_photo.addItem(name, (w, h))
        self.combo_photo.setCurrentIndex(CONFIG["DEFAULT_PHOTO_SIZE"]); self.combo_photo.currentIndexChanged.connect(self.on_photo_type_changed)
        self.layout_photo.addRow("Slot Size:", self.combo_photo)

        self.spin_custom_w = QSpinBox(); self.spin_custom_w.setRange(10, 500); self.spin_custom_w.setValue(50); self.spin_custom_w.setSuffix(" mm"); self.spin_custom_w.valueChanged.connect(self._size_debounce_timer.start)
        self.label_custom_w = QLabel("Custom Width:")
        self.spin_custom_h = QSpinBox(); self.spin_custom_h.setRange(10, 500); self.spin_custom_h.setValue(50); self.spin_custom_h.setSuffix(" mm"); self.spin_custom_h.valueChanged.connect(self._size_debounce_timer.start)
        self.label_custom_h = QLabel("Custom Height:")
        self.check_photo_landscape = QCheckBox("Swap Preset W/H"); self.check_photo_landscape.stateChanged.connect(self.apply_global_photo_size)
        
        self.layout_photo.addRow(self.label_custom_w, self.spin_custom_w); self.layout_photo.addRow(self.label_custom_h, self.spin_custom_h); self.layout_photo.addRow("", self.check_photo_landscape)

        self.combo_fit_mode = QComboBox(); self.combo_fit_mode.addItems(["Fill (Crop to Fit - Default)", "Fit (Letterbox Blank Edges)", "Stretch (Distort to Fit)"])
        self.combo_fit_mode.setCurrentIndex(CONFIG["DEFAULT_FIT_MODE"]); self.combo_fit_mode.currentIndexChanged.connect(self.apply_global_fit_mode)
        self.layout_photo.addRow("Photo Snapping:", self.combo_fit_mode)

        self.spin_spacing = QSpinBox(); self.spin_spacing.setRange(0, 50); self.spin_spacing.setValue(CONFIG["DEFAULT_SPACING_MM"]); self.spin_spacing.valueChanged.connect(self.schedule_layout_update)
        self.layout_photo.addRow("Gutter (mm):", self.spin_spacing)
        
        self.check_print_borders = QCheckBox("Print Cell Borders (Dashed)"); self.check_print_borders.stateChanged.connect(lambda: self.trigger_layout_change(preserve_zoom=True)); self.layout_photo.addRow("", self.check_print_borders)
        self.check_print_crop_marks = QCheckBox("Print Corner Crop Marks"); self.check_print_crop_marks.stateChanged.connect(lambda: self.trigger_layout_change(preserve_zoom=True)); self.layout_photo.addRow("", self.check_print_crop_marks)

        self.combo_sharpen = QComboBox(); self.combo_sharpen.addItems(["None (Off)", "Low (Matte / Rag Papers)", "Standard (General Photo)", "High (Glossy / Luster)"])
        self.combo_sharpen.setCurrentIndex(CONFIG["DEFAULT_SHARPENING"]); self.combo_sharpen.currentIndexChanged.connect(lambda: self.trigger_layout_change(preserve_zoom=True))
        self.layout_photo.addRow("Sharpening:", self.combo_sharpen)

        self.combo_icc = QComboBox(); self.combo_icc.addItem("sRGB Standard (Driver Managed)"); self.combo_icc.addItem("Simulate Matte Paper Profile")
        if self.custom_icc_path: self.combo_icc.addItem(f"Custom: {os.path.basename(self.custom_icc_path)}")
        self.combo_icc.addItem("Load Custom .ICC Profile..."); self.combo_icc.currentIndexChanged.connect(self.handle_icc_change)
        self.layout_photo.addRow("ICC Profile:", self.combo_icc)

        self.combo_intent = QComboBox(); self.combo_intent.addItems(["Perceptual (Gamut Compression)", "Relative Colorimetric (BPC)", "Saturation (Vivid Tones)", "Absolute Colorimetric"])
        self.combo_intent.currentIndexChanged.connect(lambda: self.trigger_layout_change(preserve_zoom=True)); self.layout_photo.addRow("Render Intent:", self.combo_intent)

        self.check_soft_proof = QCheckBox("Enable Soft Proofing on Canvas"); self.check_soft_proof.stateChanged.connect(lambda: self.trigger_layout_change(preserve_zoom=True)); self.layout_photo.addRow("", self.check_soft_proof)

        scroll_photo = QScrollArea(); scroll_photo.setWidgetResizable(True); scroll_photo.setWidget(tab_photo_widget); scroll_photo.setFrameShape(QScrollArea.Shape.NoFrame)
        self.tabs.addTab(scroll_photo, "1. Photos"); self.on_photo_type_changed()

        tab_doc_widget = QWidget(); tab_doc_widget.setObjectName("scrollBg"); layout_doc = QFormLayout(tab_doc_widget); layout_doc.setContentsMargins(6, 8, 6, 8); layout_doc.setSpacing(10)
        self.combo_doc_dpi = QComboBox(); self.combo_doc_dpi.addItem("300 DPI (Standard Text)", 300); self.combo_doc_dpi.addItem("600 DPI (Ultra Sharp Text)", 600); self.combo_doc_dpi.addItem("1200 DPI (Laser / Studio Text)", 1200)
        self.combo_doc_dpi.setCurrentIndex(1); self.combo_doc_dpi.currentIndexChanged.connect(lambda: self.trigger_layout_change(preserve_zoom=True)); layout_doc.addRow("Text Render DPI:", self.combo_doc_dpi)

        self.combo_doc_color = QComboBox(); self.combo_doc_color.addItems(["Normal (Original)", "High Contrast B&W (Enhance Text)", "Grayscale", "Invert (Save Ink / Dark PDF)"])
        self.combo_doc_color.currentIndexChanged.connect(lambda: self.trigger_layout_change(preserve_zoom=True)); layout_doc.addRow("Document Mode:", self.combo_doc_color)

        self.combo_txt_font = QComboBox(); self.combo_txt_font.addItems(["Monospace", "Sans-Serif (Clean / Modern)", "Serif (Book / Classic)"])
        self.combo_txt_font.currentIndexChanged.connect(lambda: self.trigger_layout_change(preserve_zoom=True)); layout_doc.addRow("Plain Text Font:", self.combo_txt_font)

        self.spin_txt_size = QSpinBox(); self.spin_txt_size.setRange(6, 24); self.spin_txt_size.setValue(CONFIG.get("DEFAULT_TXT_FONT_SIZE", 10)); self.spin_txt_size.setSuffix(" pt")
        self.spin_txt_size.valueChanged.connect(self.schedule_layout_update); layout_doc.addRow("Text Font Size:", self.spin_txt_size)

        scroll_doc = QScrollArea(); scroll_doc.setWidgetResizable(True); scroll_doc.setWidget(tab_doc_widget); scroll_doc.setFrameShape(QScrollArea.Shape.NoFrame)
        self.tabs.addTab(scroll_doc, "2. Documents")

        tab_universal_widget = QWidget(); tab_universal_widget.setObjectName("scrollBg"); layout_universal = QFormLayout(tab_universal_widget); layout_universal.setContentsMargins(6, 8, 6, 8); layout_universal.setSpacing(10)
        self.combo_paper = QComboBox()
        self.paper_sizes = {
            "A4 (210 x 297 mm)": (210, 297, QPageSize.PageSizeId.A4), "A3 (297 x 420 mm)": (297, 420, QPageSize.PageSizeId.A3), "A5 (148 x 210 mm)": (148, 210, QPageSize.PageSizeId.A5),
            "B5 (176 x 250 mm)": (176, 250, QPageSize.PageSizeId.B5), "Letter (216 x 279 mm)": (215.9, 279.4, QPageSize.PageSizeId.Letter), "Legal (216 x 356 mm)": (215.9, 355.6, QPageSize.PageSizeId.Legal),
            "4x6 Photo (102 x 152 mm)": (101.6, 152.4, None), "5x7 Photo (127 x 178 mm)": (127, 177.8, None), "8x10 Photo (203 x 254 mm)": (203.2, 254, None)
        }
        for name, data in self.paper_sizes.items(): self.combo_paper.addItem(name, data)
        self.combo_paper.setCurrentIndex(CONFIG["DEFAULT_PAPER_SIZE"]); self.combo_paper.currentIndexChanged.connect(lambda: [log_event("Paper size changed"), self.trigger_layout_change(preserve_zoom=False)])
        layout_universal.addRow("Printer Paper:", self.combo_paper)
        
        self.check_paper_landscape = QCheckBox("Rotate Paper (Landscape)"); self.check_paper_landscape.stateChanged.connect(lambda: [log_event("Paper orientation toggled"), self.trigger_layout_change(preserve_zoom=False)])
        layout_universal.addRow("", self.check_paper_landscape)

        self.spin_margin = QSpinBox(); self.spin_margin.setRange(0, 50); self.spin_margin.setValue(CONFIG["DEFAULT_MARGIN_MM"]); self.spin_margin.valueChanged.connect(self.schedule_layout_update)
        layout_universal.addRow("Page Margin (mm):", self.spin_margin)

        self.check_borderless = QCheckBox("Borderless (0 mm Bleed)"); self.check_borderless.setChecked(CONFIG["DEFAULT_BORDERLESS"]); self.check_borderless.stateChanged.connect(self.on_borderless_toggled)
        layout_universal.addRow("", self.check_borderless)

        self.combo_target_printer = QComboBox(); self.combo_target_printer.currentIndexChanged.connect(self.refresh_media_types); layout_universal.addRow("Target Printer:", self.combo_target_printer)
        self.combo_media = QComboBox(); self.combo_media.currentIndexChanged.connect(lambda: log_event(f"Media type selected: {self.combo_media.currentText()}")); layout_universal.addRow("Target Media:", self.combo_media)
        self.refresh_printers()
        
        self.combo_dpi = QComboBox(); self.combo_dpi.addItem("300 DPI (Standard Quality)", 300); self.combo_dpi.addItem("600 DPI (High Quality)", 600); self.combo_dpi.addItem("1200 DPI (Ultra / Studio)", 1200)
        self.combo_dpi.currentIndexChanged.connect(lambda: [log_event("DPI Resolution changed"), self.trigger_layout_change(preserve_zoom=True)]); layout_universal.addRow("Output Resolution:", self.combo_dpi)

        self.combo_color = QComboBox(); self.combo_color.addItem("Color", QPrinter.ColorMode.Color); self.combo_color.addItem("Monochrome (Pigment Black)", QPrinter.ColorMode.GrayScale)
        self.combo_color.currentIndexChanged.connect(lambda: [log_event(f"Color mode changed to {self.combo_color.currentText()}"), self.trigger_layout_change(preserve_zoom=True)]); layout_universal.addRow("Color Mode:", self.combo_color)

        scroll_universal = QScrollArea(); scroll_universal.setWidgetResizable(True); scroll_universal.setWidget(tab_universal_widget); scroll_universal.setFrameShape(QScrollArea.Shape.NoFrame)
        self.tabs.addTab(scroll_universal, "3. Print & Sheet")
        
        self.btn_preview = QPushButton("Modern Print Preview"); self.btn_preview.setObjectName("ActionBtn"); self.btn_preview.clicked.connect(self.show_print_preview); right_layout.addWidget(self.btn_preview)
        self.btn_save_pdf = QPushButton("Save Document as PDF"); self.btn_save_pdf.setObjectName("PdfBtn"); self.btn_save_pdf.clicked.connect(self.export_to_pdf); right_layout.addWidget(self.btn_save_pdf)
        self.btn_save_odt = QPushButton("Save Document as ODT"); self.btn_save_odt.setObjectName("OdtBtn"); self.btn_save_odt.clicked.connect(self.export_to_odt); right_layout.addWidget(self.btn_save_odt)
        self.btn_exit = QPushButton("Exit Application"); self.btn_exit.clicked.connect(self.close); right_layout.addWidget(self.btn_exit)
        
        main_layout.addWidget(left_panel); main_layout.addWidget(center_panel, stretch=1); main_layout.addWidget(right_panel)
        self.setCentralWidget(central_widget)
        self.showMaximized(); self.on_photo_type_changed(); self.update_canvas(reset_zoom=False); QTimer.singleShot(100, lambda: self.update_canvas(reset_zoom=True))
        
        QShortcut(QKeySequence("Esc"), self, self.close); QShortcut(QKeySequence("Ctrl+Z"), self, self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo); QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)
        QShortcut(QKeySequence("Ctrl+C"), self, self.copy_canvas_image); QShortcut(QKeySequence("Ctrl+V"), self, self.paste_canvas_image)
        QShortcut(QKeySequence("Delete"), self, self.remove_selected_canvas_image); QShortcut(QKeySequence("Backspace"), self, self.remove_selected_canvas_image)

    def closeEvent(self, event):
        self.render_thread_pool.clear(); self.thumb_thread_pool.clear()
        self.render_thread_pool.waitForDone(200); self.thumb_thread_pool.waitForDone(200)
        if os.path.exists(DOC_CACHE_DIR): shutil.rmtree(DOC_CACHE_DIR, ignore_errors=True)
        super().closeEvent(event)

    def change_workspace(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Set Workspace Root", self.workspace_root)
        if folder_path:
            self.workspace_root = os.path.abspath(folder_path); self.current_folder = self.workspace_root; self.settings.setValue("workspace_root", self.workspace_root)
            self.lbl_workspace.setText(f"{os.path.basename(self.workspace_root)}"); self.lbl_workspace.setToolTip(self.workspace_root)
            self.dir_model.setRootPath(self.workspace_root); self.tree.setRootIndex(self.dir_model.index(self.workspace_root))
            self.gallery.clear(); self.btn_up_folder.setEnabled(False)
            if os.path.isdir(self.workspace_root): self.load_images_from_folder(self.workspace_root)

    def on_tree_clicked(self, index):
        path = self.dir_model.filePath(index)
        if os.path.isdir(path): self.load_images_from_folder(path)

    def go_up_folder(self):
        curr = os.path.abspath(self.current_folder); root = os.path.abspath(self.workspace_root)
        if curr == root or not curr.startswith(root): return
        parent = os.path.dirname(curr)
        if len(parent) < len(root) or not parent.startswith(root): parent = root
        self.load_images_from_folder(parent)
        idx = self.dir_model.index(parent)
        if idx.isValid(): self.tree.setCurrentIndex(idx); self.tree.scrollTo(idx)

    def create_themed_placeholder(self, tag):
        size = CONFIG["THUMBNAIL_SIZE"]; pix = QPixmap(size, size)
        bg_col = QColor("#1E293B") if self.is_dark_mode else QColor("#F1F5F9"); border_col = QColor("#334155") if self.is_dark_mode else QColor("#CBD5E1")
        text_col = QColor("#94A3B8") if self.is_dark_mode else QColor("#64748B")
        pix.fill(Qt.GlobalColor.transparent); p = QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(bg_col); p.setPen(QPen(border_col, 1)); p.drawRoundedRect(1, 1, size - 2, size - 2, 6, 6)
        p.setPen(text_col); p.setFont(QFont("Arial", 10, QFont.Weight.Bold)); p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, tag)
        p.end()
        return QIcon(pix)

    def load_images_from_folder(self, folder_path):
        self.current_folder = os.path.abspath(folder_path); root = os.path.abspath(self.workspace_root)
        if hasattr(self, 'btn_up_folder'): self.btn_up_folder.setEnabled(self.current_folder != root and self.current_folder.startswith(root))
        self.folder_generation += 1; self.thumb_thread_pool.clear(); self.gallery.clear(); self.gallery_items_by_path.clear()
        if not os.path.isdir(self.current_folder): return

        valid_entries = []
        try:
            with os.scandir(self.current_folder) as it:
                for entry in it:
                    if entry.is_file() and entry.name.lower().endswith(ALL_VALID_EXTENSIONS): valid_entries.append((entry.name, entry.path, entry.name.lower()))
        except Exception: return

        valid_entries.sort(key=lambda x: x[0].lower()); thumb_size = CONFIG["THUMBNAIL_SIZE"]; self.gallery.setUpdatesEnabled(False)
        for name, full_path, lower in valid_entries:
            if full_path in self.thumbnail_cache: icon = QIcon(self.thumbnail_cache[full_path])
            else:
                if lower.endswith(IMG_EXTENSIONS): tag = "IMG"
                elif lower.endswith('.pdf'): tag = "PDF"
                elif lower.endswith(TEXT_EXTENSIONS): tag = "TXT"
                else: tag = "DOC"
                icon = self.create_themed_placeholder(tag)
            item = QListWidgetItem(icon, ""); item.setToolTip(name); item.setData(Qt.ItemDataRole.UserRole, full_path)
            self.gallery.addItem(item); self.gallery_items_by_path[full_path] = item
        self.gallery.setUpdatesEnabled(True)

        for name, full_path, lower in valid_entries:
            if full_path not in self.thumbnail_cache:
                worker = ThumbnailWorker(self.folder_generation, full_path, thumb_size, self); worker.signals.ready.connect(self.on_thumbnail_ready); self.thumb_thread_pool.start(worker)

    def on_thumbnail_ready(self, gen, filepath, pixmap):
        if gen != self.folder_generation: return
        if len(self.thumbnail_cache) >= self.MAX_THUMB_CACHE: self.thumbnail_cache.popitem(last=False)
        self.thumbnail_cache[filepath] = pixmap
        if filepath in self.gallery_items_by_path: self.gallery_items_by_path[filepath].setIcon(QIcon(pixmap))

    def update_selected_label(self):
        items = self.gallery.selectedItems()
        if items: self.label_file_info.setText(f"<b>Library Selected:</b> {os.path.basename(items[0].data(Qt.ItemDataRole.UserRole))}")
        elif self.active_canvas_index is not None and self.active_canvas_index < len(self.selected_images_for_print):
            img_data = self.selected_images_for_print[self.active_canvas_index]
            w_code, h_code = img_data.get('w_code', 50), img_data.get('h_code', 50)
            if w_code < 0: w_mm, h_mm = self.calculate_dynamic_size(w_code)
            else: w_mm, h_mm = w_code, h_code
            if img_data.get('landscape', False): w_mm, h_mm = h_mm, w_mm

            fname = os.path.basename(img_data['path']); page_text = f" (Page {img_data.get('page', 0)+1}/{img_data.get('total_pages', 1)})" if is_doc_file(img_data['path']) else ""
            reader = QImageReader(img_data['path']); orig_size = reader.size()
            
            if orig_size.isValid() and w_mm > 0:
                eff_ppi = int(orig_size.width() / (w_mm / 25.4))
                if eff_ppi >= 300: badge = f'<span style="color:#10B981;">● {eff_ppi} PPI (Optimal Lab)</span>'
                elif eff_ppi >= 200: badge = f'<span style="color:#F59E0B;">● {eff_ppi} PPI (Good Quality)</span>'
                else: badge = f'<span style="color:#EF4444;">● {eff_ppi} PPI (Low Resolution)</span>'
            else: badge = f'<span style="color:#10B981;">● Crisp Vector/Doc Quality</span>'

            zoom_val = int(img_data.get('zoom', 1.0) * 100)
            crop_info = f"Framing: {int(img_data.get('crop_x', 0.5)*100)}%, {int(img_data.get('crop_y', 0.5)*100)}% | Zoom: {zoom_val}%"
            self.label_file_info.setText(f"<b>Sheet Item #{self.active_canvas_index + 1}:</b> {fname}{page_text}<br>{badge}<br><small style='color:#64748B;'>{crop_info}</small>")
        else: self.label_file_info.setText("Selected: None")

    def schedule_layout_update(self): self._layout_timer.start()
    def on_borderless_toggled(self): self.spin_margin.setEnabled(not self.check_borderless.isChecked()); self.trigger_layout_change(preserve_zoom=True)

    def apply_global_fit_mode(self):
        mode = self.combo_fit_mode.currentText()
        for img in self.selected_images_for_print:
            img['fit_mode'] = mode
        self.trigger_layout_change(preserve_zoom=True)

    def apply_global_photo_size(self):
        w, h = (self.spin_custom_w.value(), self.spin_custom_h.value()) if self.combo_photo.currentText() == "Custom Size" else self.combo_photo.currentData()
        landscape = self.check_photo_landscape.isChecked()
        for img in self.selected_images_for_print: img['w_code'] = w; img['h_code'] = h; img['landscape'] = landscape
        self.trigger_layout_change(preserve_zoom=True)

    def on_photo_type_changed(self):
        is_custom = (self.combo_photo.currentText() == "Custom Size")
        self.label_custom_w.setVisible(is_custom); self.spin_custom_w.setVisible(is_custom)
        self.label_custom_h.setVisible(is_custom); self.spin_custom_h.setVisible(is_custom)
        if hasattr(self, 'layout_photo'):
            try: self.layout_photo.setRowVisible(self.spin_custom_w, is_custom); self.layout_photo.setRowVisible(self.spin_custom_h, is_custom)
            except Exception: pass
        self.apply_global_photo_size()

    def import_file_to_canvas(self, path):
        if is_doc_file(path):
            total_pages = get_document_page_count(path)
            if total_pages > 1:
                options = [f"All Pages (1 to {total_pages})"] + [f"Page {i+1}" for i in range(total_pages)]
                choice, ok = QInputDialog.getItem(self, "Document Import", f"{os.path.basename(path)} contains {total_pages} pages.\nChoose pages to place:", options, 0, False)
                if not ok: return
                pages_to_add = list(range(total_pages)) if choice.startswith("All") else [int(choice.split()[1]) - 1]
            else: pages_to_add = [0]

            self.combo_photo.blockSignals(True); self.combo_photo.setCurrentIndex(0); self.combo_photo.blockSignals(False)
            for p in pages_to_add:
                self.selected_images_for_print.append({
                    "path": path, "page": p, "total_pages": total_pages, "w_code": -1, "h_code": -1, "landscape": False,
                    "b": 1.0, "c": 1.0, "s": 1.0, "gray": False, "sepia": False, "crop_x": 0.5, "crop_y": 0.5, "zoom": 1.0, "high_contrast": False
                })
        else:
            w_mm, h_mm = self.get_current_layout_dimensions()
            self.selected_images_for_print.append({
                "path": path, "page": 0, "total_pages": 1, "w_code": w_mm, "h_code": h_mm, "landscape": self.check_photo_landscape.isChecked(),
                "b": 1.0, "c": 1.0, "s": 1.0, "gray": False, "sepia": False, "crop_x": 0.5, "crop_y": 0.5, "zoom": 1.0, "high_contrast": False
            })
            
        self.active_canvas_index = len(self.selected_images_for_print) - 1
        self.save_history_state(); self.update_canvas(reset_zoom=False); self.update_selected_label()

    def remove_selected_canvas_image(self):
        if self.active_canvas_index is not None and self.active_canvas_index < len(self.selected_images_for_print):
            self.selected_images_for_print.pop(self.active_canvas_index); self.active_canvas_index = None
            self.save_history_state(); self.update_canvas(reset_zoom=False); self.update_selected_label()

    def clear_canvas(self):
        if self.selected_images_for_print:
            self._render_generation += 1; self.render_thread_pool.clear(); self.selected_images_for_print.clear()
            self.canvas_pixmap_items.clear(); self.pixmap_cache.clear(); self.active_canvas_index = None; self.current_page = 0
            self.save_history_state(); self.update_canvas(reset_zoom=False); self.update_selected_label()

    def nudge_crop(self, dx, dy):
        idx = self.active_canvas_index
        if idx is not None and idx < len(self.selected_images_for_print):
            data = self.selected_images_for_print[idx]; zoom_scale = data.get('zoom', 1.0)
            item_fit_mode = data.get('fit_mode', self.combo_fit_mode.currentText())
            if not item_fit_mode.startswith("Fill"):
                data['fit_mode'] = "Fill (Crop to Fit - Default)"
                
            data['crop_x'] = max(0.0, min(1.0, data.get('crop_x', 0.5) + (dx / zoom_scale)))
            data['crop_y'] = max(0.0, min(1.0, data.get('crop_y', 0.5) + (dy / zoom_scale)))
            if self.view._ensure_fast_preview_loaded(idx): self.view._update_live_preview(); self.view._interact_timer.start(400)
            else: self.update_selected_label()

    def prev_page(self):
        if self.current_page > 0: self.current_page -= 1; self.update_canvas(reset_zoom=False)

    def next_page(self):
        capacity = self.calculate_page_capacity(); total_pages = max(1, (len(self.selected_images_for_print) + capacity - 1) // capacity) if capacity > 0 else 1
        if self.current_page < total_pages - 1: self.current_page += 1; self.update_canvas(reset_zoom=False)

    def calculate_page_capacity(self):
        paper_w_mm, paper_h_mm, _ = self.combo_paper.currentData()
        if self.check_paper_landscape.isChecked(): paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm
        margin_mm = 0 if self.check_borderless.isChecked() else self.spin_margin.value()
        spacing_mm = self.spin_spacing.value()
        def_w_mm, def_h_mm = self.get_current_layout_dimensions()
        pw = paper_w_mm - (margin_mm * 2); ph = paper_h_mm - (margin_mm * 2)
        
        cols = 1
        while (cols * def_w_mm) + ((cols - 1) * spacing_mm) <= pw: cols += 1
        cols -= 1
        if cols < 1: cols = 1

        rows = 1
        while (rows * def_h_mm) + ((rows - 1) * spacing_mm) <= ph: rows += 1
        rows -= 1
        if rows < 1: rows = 1
        return cols * rows

    def calculate_dynamic_size(self, w_code):
        paper_w_mm, paper_h_mm, _ = self.combo_paper.currentData()
        if self.check_paper_landscape.isChecked(): paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm
        margin = 0 if self.check_borderless.isChecked() else self.spin_margin.value()
        spacing = self.spin_spacing.value()
        pw = paper_w_mm - (margin * 2); ph = paper_h_mm - (margin * 2)
        
        if w_code == -1: return pw, ph
        elif w_code == -2: return pw, (ph - spacing) / 2.0
        elif w_code == -4: return (pw - spacing) / 2.0, (ph - spacing) / 2.0
        elif w_code == -6: return (pw - spacing) / 2.0, (ph - 2 * spacing) / 3.0
        return 50, 50 

    def get_current_layout_dimensions(self):
        if self.combo_photo.currentText() == "Custom Size": w = self.spin_custom_w.value(); h = self.spin_custom_h.value()
        else: w, h = self.combo_photo.currentData()
        if w < 0: w, h = self.calculate_dynamic_size(w)
        if self.check_photo_landscape.isChecked(): w, h = h, w
        return w, h

    def handle_icc_change(self):
        text = self.combo_icc.currentText()
        if text == "Load Custom .ICC Profile...":
            search_path = "/usr/share/color/icc" if os.path.exists("/usr/share/color/icc") else os.path.expanduser("~")
            path, _ = QFileDialog.getOpenFileName(self, "Select ICC/ICM Profile", search_path, "Color Profiles (*.icc *.icm)")
            if path:
                self.custom_icc_path = path; self.combo_icc.blockSignals(True); self.combo_icc.clear()
                self.combo_icc.addItem("sRGB Standard (Driver Managed)"); self.combo_icc.addItem("Simulate Matte Paper Profile")
                self.combo_icc.addItem(f"Custom: {os.path.basename(path)}"); self.combo_icc.addItem("Load Custom .ICC Profile...")
                self.combo_icc.setCurrentIndex(2); self.combo_icc.blockSignals(False)
            else: self.combo_icc.setCurrentIndex(0)
        self.trigger_layout_change(preserve_zoom=True)

    def refresh_printers(self):
        self.combo_target_printer.clear(); printers = QPrinterInfo.availablePrinters(); default_printer = QPrinterInfo.defaultPrinter().printerName()
        if not printers: self.combo_target_printer.addItem("No Printers Found", None); return
        for p in printers: self.combo_target_printer.addItem(p.printerName(), p)
        idx = self.combo_target_printer.findText(default_printer)
        if idx >= 0: self.combo_target_printer.setCurrentIndex(idx)

    def refresh_media_types(self):
        printer_info = self.combo_target_printer.currentData()
        if not printer_info: return
        self.combo_media.clear()
        try:
            result = subprocess.run(['lpoptions', '-p', printer_info.printerName(), '-l'], capture_output=True, text=True, timeout=2)
            media_options = []
            for line in result.stdout.split('\n'):
                if line.startswith('MediaType/') or line.startswith('Media/'):
                    parts = line.split(':', 1)
                    if len(parts) > 1: media_options = [c.replace('*', '') for c in parts[1].strip().split()]; break
            if media_options: self.combo_media.addItems(media_options)
            else: self.combo_media.addItem("Driver Default / Generic")
        except Exception: self.combo_media.addItem("Driver Default / Generic")

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode; self.btn_theme.setText("☀️ Light Mode" if self.is_dark_mode else "🌙 Dark Mode")
        self.apply_theme(); self.update_canvas(reset_zoom=False)

    def apply_theme(self):
        f_size = CONFIG["UI_FONT_SIZE"]
        if self.is_dark_mode:
            stylesheet = f"""
                QWidget {{ background-color: #0F172A; color: #F8FAFC; font-family: system-ui, -apple-system, sans-serif; font-size: {f_size}px; }}
                QLabel {{ color: #F8FAFC; font-weight: 600; font-size: {f_size}px; }}
                QCheckBox {{ color: #F1F5F9; font-weight: 500; font-size: {f_size}px; spacing: 8px; }}
                QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 4px; border: 1.5px solid #475569; background-color: #1E293B; }}
                QCheckBox::indicator:hover {{ border-color: #38BDF8; background-color: #273549; }}
                QCheckBox::indicator:checked {{ background-color: #2563EB; border-color: #38BDF8; }}
                QPushButton {{ background-color: #1E293B; border: 1px solid #334155; border-radius: 6px; padding: 7px 12px; font-weight: 600; font-size: {f_size}px; color: #F8FAFC; }}
                QPushButton:hover {{ background-color: #273549; border-color: #64748B; }}
                QPushButton:pressed {{ background-color: #0F172A; border-color: #38BDF8; color: #38BDF8; }}
                QPushButton:disabled {{ background-color: #151F2E; color: #475569; border-color: #1E293B; }}
                QPushButton#ActionBtn {{ background-color: #2563EB; color: #FFFFFF; border: none; padding: 10px; font-size: {f_size+1}px; margin-top: 4px; }}
                QPushButton#ActionBtn:hover {{ background-color: #1D4ED8; border: 1px solid #93C5FD; }}
                QPushButton#ActionBtn:pressed {{ background-color: #1E40AF; }}
                QPushButton#PdfBtn {{ background-color: #059669; color: #FFFFFF; border: none; padding: 10px; font-size: {f_size}px; }}
                QPushButton#PdfBtn:hover {{ background-color: #047857; border: 1px solid #6EE7B7; }}
                QPushButton#PdfBtn:pressed {{ background-color: #064E3B; }}
                QPushButton#OdtBtn {{ background-color: #65A30D; color: #FFFFFF; border: none; padding: 10px; font-size: {f_size}px; }}
                QPushButton#OdtBtn:hover {{ background-color: #4D7C0F; border: 1px solid #BEF264; }}
                QPushButton#OdtBtn:pressed {{ background-color: #3F6212; }}
                QListWidget, QTreeView {{ background-color: #1E293B; border: 1px solid #334155; border-radius: 6px; outline: none; color: #F8FAFC; }}
                QListWidget::item:hover, QTreeView::item:hover {{ background-color: #273549; border-radius: 4px; }}
                QListWidget::item:selected, QTreeView::item:selected {{ background-color: #2563EB; color: #FFFFFF; border-radius: 4px; }}
                QComboBox, QSpinBox {{ background-color: #1E293B; border: 1px solid #334155; border-radius: 6px; padding: 5px 8px; color: #F8FAFC; font-weight: 600; font-size: {f_size}px; }}
                QComboBox:hover, QSpinBox:hover {{ border: 1.5px solid #64748B; background-color: #273549; }}
                QComboBox:focus, QSpinBox:focus {{ border: 1.5px solid #38BDF8; background-color: #1E293B; }}
                QComboBox::drop-down {{ border: none; }}
                QComboBox QAbstractItemView {{ background-color: #1E293B; border: 1px solid #334155; color: #F8FAFC; selection-background-color: #2563EB; selection-color: #FFFFFF; }}
                QTabWidget::pane {{ border: 1px solid #334155; background: #1E293B; border-radius: 6px; }}
                QTabBar::tab {{ background: #0F172A; padding: 8px 12px; margin-right: 2px; border-top-left-radius: 6px; border-top-right-radius: 6px; font-weight: 600; font-size: {f_size-1}px; color: #94A3B8; border: 1px solid transparent; }}
                QTabBar::tab:hover {{ color: #F8FAFC; background-color: #1E293B; border: 1px solid #334155; }}
                QTabBar::tab:selected {{ background: #2563EB; color: #FFFFFF; border: 1px solid #2563EB; }}
                QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0px; }}
                QScrollBar::handle:vertical {{ background: #334155; min-height: 25px; border-radius: 5px; }}
                QScrollBar::handle:vertical:hover {{ background: #475569; }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; border: none; height: 0px; }}
                QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0px; }}
                QScrollBar::handle:horizontal {{ background: #334155; min-width: 25px; border-radius: 5px; }}
                QScrollBar::handle:horizontal:hover {{ background: #475569; }}
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; border: none; width: 0px; }}
                QDialog {{ background-color: #0F172A; }}
                QGraphicsView {{ border: none; }}
                QScrollArea {{ border: none; background-color: transparent; }}
                QWidget#scrollBg {{ background-color: transparent; }}
                QMenu {{ background-color: #1E293B; color: #F8FAFC; border: 1px solid #334155; border-radius: 6px; padding: 4px 0px; }}
                QMenu::item {{ padding: 6px 24px 6px 12px; background-color: transparent; }}
                QMenu::item:selected {{ background-color: #2563EB; color: #FFFFFF; }}
                QMenu::separator {{ height: 1px; background-color: #334155; margin: 4px 0px; }}
            """
            self.scene.setBackgroundBrush(QColor("#020617"))
            self.pagination_bar.setStyleSheet("background-color: #1E293B; border-radius: 6px; border: 1px solid #334155;")
        else:
            stylesheet = f"""
                QWidget {{ background-color: #F8FAFC; color: #0F172A; font-family: system-ui, -apple-system, sans-serif; font-size: {f_size}px; }}
                QLabel {{ color: #0F172A; font-weight: 600; font-size: {f_size}px; }}
                QCheckBox {{ color: #0F172A; font-weight: 500; font-size: {f_size}px; spacing: 8px; }}
                QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 4px; border: 1.5px solid #CBD5E1; background-color: #FFFFFF; }}
                QCheckBox::indicator:hover {{ border-color: #2563EB; background-color: #F1F5F9; }}
                QCheckBox::indicator:checked {{ background-color: #2563EB; border-color: #2563EB; }}
                QPushButton {{ background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px; padding: 7px 12px; font-weight: 600; font-size: {f_size}px; color: #0F172A; }}
                QPushButton:hover {{ background-color: #F1F5F9; border-color: #94A3B8; }}
                QPushButton:pressed {{ background-color: #E2E8F0; border-color: #2563EB; color: #2563EB; }}
                QPushButton:disabled {{ background-color: #F1F5F9; color: #94A3B8; border-color: #E2E8F0; }}
                QPushButton#ActionBtn {{ background-color: #2563EB; color: #FFFFFF; border: none; padding: 10px; font-size: {f_size+1}px; margin-top: 4px; }}
                QPushButton#ActionBtn:hover {{ background-color: #1D4ED8; border: 1px solid #93C5FD; }}
                QPushButton#ActionBtn:pressed {{ background-color: #1E40AF; }}
                QPushButton#PdfBtn {{ background-color: #059669; color: #FFFFFF; border: none; padding: 10px; font-size: {f_size}px; }}
                QPushButton#PdfBtn:hover {{ background-color: #047857; border: 1px solid #6EE7B7; }}
                QPushButton#PdfBtn:pressed {{ background-color: #064E3B; }}
                QPushButton#OdtBtn {{ background-color: #65A30D; color: #FFFFFF; border: none; padding: 10px; font-size: {f_size}px; }}
                QPushButton#OdtBtn:hover {{ background-color: #4D7C0F; border: 1px solid #BEF264; }}
                QPushButton#OdtBtn:pressed {{ background-color: #3F6212; }}
                QListWidget, QTreeView {{ background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px; outline: none; color: #0F172A; }}
                QListWidget::item:hover, QTreeView::item:hover {{ background-color: #F1F5F9; border-radius: 4px; }}
                QListWidget::item:selected, QTreeView::item:selected {{ background-color: #DBEAFE; color: #1E3A8A; border-radius: 4px; }}
                QComboBox, QSpinBox {{ background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 8px; color: #0F172A; font-weight: 600; font-size: {f_size}px; }}
                QComboBox:hover, QSpinBox:hover {{ border: 1.5px solid #94A3B8; background-color: #F1F5F9; }}
                QComboBox:focus, QSpinBox:focus {{ border: 1.5px solid #2563EB; background-color: #FFFFFF; }}
                QComboBox::drop-down {{ border: none; }}
                QComboBox QAbstractItemView {{ background-color: #FFFFFF; border: 1px solid #CBD5E1; color: #0F172A; selection-background-color: #DBEAFE; selection-color: #1E3A8A; }}
                QTabWidget::pane {{ border: 1px solid #CBD5E1; background: #FFFFFF; border-radius: 6px; }}
                QTabBar::tab {{ background: #F1F5F9; padding: 8px 12px; margin-right: 2px; border-top-left-radius: 6px; border-top-right-radius: 6px; font-weight: 600; font-size: {f_size-1}px; color: #64748B; border: 1px solid transparent; }}
                QTabBar::tab:hover {{ color: #0F172A; background-color: #E2E8F0; border: 1px solid #CBD5E1; }}
                QTabBar::tab:selected {{ background: #2563EB; color: #FFFFFF; border: 1px solid #2563EB; }}
                QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0px; }}
                QScrollBar::handle:vertical {{ background: #CBD5E1; min-height: 25px; border-radius: 5px; }}
                QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; border: none; height: 0px; }}
                QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0px; }}
                QScrollBar::handle:horizontal {{ background: #CBD5E1; min-width: 25px; border-radius: 5px; }}
                QScrollBar::handle:horizontal:hover {{ background: #94A3B8; }}
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; border: none; width: 0px; }}
                QDialog {{ background-color: #F8FAFC; }}
                QGraphicsView {{ border: none; }}
                QScrollArea {{ border: none; background-color: transparent; }}
                QWidget#scrollBg {{ background-color: transparent; }}
                QMenu {{ background-color: #FFFFFF; color: #0F172A; border: 1px solid #CBD5E1; border-radius: 6px; padding: 4px 0px; }}
                QMenu::item {{ padding: 6px 24px 6px 12px; background-color: transparent; }}
                QMenu::item:selected {{ background-color: #DBEAFE; color: #1E3A8A; }}
                QMenu::separator {{ height: 1px; background-color: #E2E8F0; margin: 4px 0px; }}
            """
            self.scene.setBackgroundBrush(QColor("#E2E8F0"))
            self.pagination_bar.setStyleSheet("background-color: #FFFFFF; border-radius: 6px; border: 1px solid #CBD5E1;")
        self.setStyleSheet(stylesheet)

    def copy_canvas_image(self):
        if getattr(self, 'active_canvas_index', None) is not None and self.active_canvas_index < len(self.selected_images_for_print):
            self.clipboard_image_data = copy.deepcopy(self.selected_images_for_print[self.active_canvas_index])

    def paste_canvas_image(self):
        if getattr(self, 'clipboard_image_data', None):
            self.selected_images_for_print.append(copy.deepcopy(self.clipboard_image_data))
            self.active_canvas_index = len(self.selected_images_for_print) - 1
            self.save_history_state(); self.update_canvas(reset_zoom=False)

    def save_history_state(self):
        self.history = self.history[:self.history_index + 1]
        self.history.append(copy.deepcopy(self.selected_images_for_print))
        if len(self.history) > self.MAX_HISTORY: self.history.pop(0)
        else: self.history_index += 1

    def undo(self):
        if self.history_index > 0:
            self.history_index -= 1; self.selected_images_for_print = copy.deepcopy(self.history[self.history_index])
            self.active_canvas_index = None; self.update_canvas(reset_zoom=False); self.update_selected_label()

    def redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1; self.selected_images_for_print = copy.deepcopy(self.history[self.history_index])
            self.active_canvas_index = None; self.update_canvas(reset_zoom=False); self.update_selected_label()

    def trigger_layout_change(self, preserve_zoom=False):
        self.update_canvas(reset_zoom=not preserve_zoom)

    def update_selection_highlight(self):
        if self.highlight_item:
            if self.highlight_item.scene() == self.scene: self.scene.removeItem(self.highlight_item)
            self.highlight_item = None
        if self.active_canvas_index is None: return self.update_selected_label()
        for item in self.scene.items():
            if isinstance(item, QGraphicsPixmapItem) and item.data(0) == self.active_canvas_index:
                rect = item.boundingRect(); pos = item.pos()
                self.highlight_item = QGraphicsRectItem(pos.x(), pos.y(), rect.width(), rect.height())
                highlight_color = QColor(56, 189, 248) if self.is_dark_mode else QColor(37, 99, 235)
                pen = QPen(highlight_color, 4); pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                self.highlight_item.setPen(pen); self.highlight_item.setBrush(QColor(0, 0, 0, 0))
                self.highlight_item.setData(0, self.active_canvas_index); self.highlight_item.setZValue(1000)
                self.highlight_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self.scene.addItem(self.highlight_item)
                break
        self.update_selected_label()

    def on_async_render_finished(self, gen, idx, cache_key, qimage):
        pixmap = QPixmap.fromImage(qimage)
        if len(self.pixmap_cache) >= self.MAX_CACHE_SIZE: self.pixmap_cache.popitem(last=False)
        self.pixmap_cache[cache_key] = pixmap
        if gen == self._render_generation and idx in self.canvas_pixmap_items:
            self.canvas_pixmap_items[idx].setPixmap(pixmap)
            if self.active_canvas_index == idx: self.update_selection_highlight()

    def on_async_render_failed(self, gen, idx, error_msg): log_event(f"Async render error {idx}: {error_msg}")

    def draw_rulers(self, px_width, px_height, paper_w_mm, paper_h_mm, cm_px):
        thick = 45 
        ruler_color = QColor(30, 41, 59) if self.is_dark_mode else QColor(241, 245, 249)
        tick_color = QColor(248, 250, 252) if self.is_dark_mode else QColor(15, 23, 42)
        half_tick = QColor(148, 163, 184) if self.is_dark_mode else QColor(100, 116, 139)
        
        top_bg = QGraphicsRectItem(0, -thick, px_width, thick); top_bg.setBrush(ruler_color); top_bg.setPen(QPen(Qt.PenStyle.NoPen)); self.scene.addItem(top_bg); self.ruler_items.append(top_bg)
        left_bg = QGraphicsRectItem(-thick, 0, thick, px_height); left_bg.setBrush(ruler_color); left_bg.setPen(QPen(Qt.PenStyle.NoPen)); self.scene.addItem(left_bg); self.ruler_items.append(left_bg)
        font = QFont("Arial", 11, QFont.Weight.Bold); tick_pen = QPen(tick_color, 2); half_tick_pen = QPen(half_tick, 1)
        
        for i in range(int(paper_w_mm / 10) + 1):
            x = i * cm_px
            tick = self.scene.addLine(x, -15, x, 0, tick_pen); self.ruler_items.append(tick)
            if i > 0:
                txt = self.scene.addText(str(i), font); txt.setDefaultTextColor(tick_color); txt.setPos(x - 8, -42); self.ruler_items.append(txt)
            half_x = x + (cm_px / 2)
            if half_x < px_width: htick = self.scene.addLine(half_x, -8, half_x, 0, half_tick_pen); self.ruler_items.append(htick)

        for i in range(int(paper_h_mm / 10) + 1):
            y = i * cm_px
            tick = self.scene.addLine(-15, y, 0, y, tick_pen); self.ruler_items.append(tick)
            if i > 0:
                txt = self.scene.addText(str(i), font); txt.setDefaultTextColor(tick_color); txt.setPos(-40, y - 12); self.ruler_items.append(txt)
            half_y = y + (cm_px / 2)
            if half_y < px_height: htick = self.scene.addLine(-8, half_y, 0, half_y, half_tick_pen); self.ruler_items.append(htick)

    def draw_corner_crop_marks(self, x, y, w, h):
        gap = int(1.5 * self.PPM); length = int(4.0 * self.PPM); pen = QPen(QColor(0, 0, 0), 1.5) 
        l1 = self.scene.addLine(x - gap - length, y, x - gap, y, pen); l2 = self.scene.addLine(x, y - gap - length, x, y - gap, pen)
        l3 = self.scene.addLine(x + w + gap, y, x + w + gap + length, y, pen); l4 = self.scene.addLine(x + w, y - gap - length, x + w, y - gap, pen)
        l5 = self.scene.addLine(x - gap - length, y + h, x - gap, y + h, pen); l6 = self.scene.addLine(x, y + h + gap, x, y + h + gap + length, pen)
        l7 = self.scene.addLine(x + w + gap, y + h, x + w + gap + length, y + h, pen); l8 = self.scene.addLine(x + w, y + h + gap, x + w, y + h + gap + length, pen)
        self.crop_mark_items.extend([l1, l2, l3, l4, l5, l6, l7, l8])

    def update_canvas(self, reset_zoom=False, dpi_override=None, sync=False, target_page=None):
        if not getattr(self, 'ui_initialized', False): return
        if not hasattr(self, 'combo_dpi'): return 
            
        self._render_generation += 1
        current_gen = self._render_generation
        if not sync: self.render_thread_pool.clear()
            
        old_pixmaps = {}
        for idx, item in self.canvas_pixmap_items.items():
            if item.pixmap() and not item.pixmap().isNull(): old_pixmaps[idx] = item.pixmap()

        self.scene.clear(); self.ruler_items.clear(); self.cell_border_items.clear()
        self.crop_mark_items.clear(); self.canvas_pixmap_items.clear(); self.highlight_item = None
        
        selected_dpi = int(self.combo_dpi.currentData())
        self.DPI = dpi_override if dpi_override is not None else min(selected_dpi, CONFIG["MAX_LIVE_DPI"])
        self.canvas_dpi = self.DPI; self.PPM = self.DPI / 25.4 
        
        paper_w_mm, paper_h_mm, _ = self.combo_paper.currentData()
        if self.check_paper_landscape.isChecked(): paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm
        def_w_mm, def_h_mm = self.get_current_layout_dimensions()

        px_width = int(paper_w_mm * self.PPM); px_height = int(paper_h_mm * self.PPM)
        self.paper_px_width = px_width; self.paper_px_height = px_height
        
        is_borderless = self.check_borderless.isChecked()
        margin_px = 0 if is_borderless else int(self.spin_margin.value() * self.PPM)
        spacing_px = int(self.spin_spacing.value() * self.PPM)
        
        printable_width = px_width - (margin_px * 2)
        printable_height = px_height - (margin_px * 2)
        
        photo_w_px = min(int(def_w_mm * self.PPM), max(1, printable_width))
        photo_h_px = min(int(def_h_mm * self.PPM), max(1, printable_height))
        
        cols = 1
        while (cols * photo_w_px) + ((cols - 1) * spacing_px) <= printable_width: cols += 1
        cols -= 1
        if cols < 1: cols = 1

        max_rows = 1
        while (max_rows * photo_h_px) + ((max_rows - 1) * spacing_px) <= printable_height: max_rows += 1
        max_rows -= 1
        if max_rows < 1: max_rows = 1

        capacity = cols * max_rows
        total_pages = max(1, (len(self.selected_images_for_print) + capacity - 1) // capacity) if capacity > 0 else 1
        
        if target_page is not None: page_to_draw = target_page
        else:
            if self.current_page >= total_pages: self.current_page = max(0, total_pages - 1)
            page_to_draw = self.current_page

        self.lbl_page_info.setText(f"Sheet {page_to_draw + 1} of {total_pages} ({len(self.selected_images_for_print)} Items)")
        self.btn_prev_page.setEnabled(page_to_draw > 0)
        self.btn_next_page.setEnabled(page_to_draw < total_pages - 1)

        grid_w_px = (cols * photo_w_px) + ((cols - 1) * spacing_px)
        grid_h_px = (max_rows * photo_h_px) + ((max_rows - 1) * spacing_px)
        
        offset_x = margin_px + (printable_width - grid_w_px) // 2
        offset_y = margin_px + (printable_height - grid_h_px) // 2

        pad = CONFIG["CANVAS_PADDING"]
        self.scene.setSceneRect(-pad, -pad, px_width + (pad*2), px_height + (pad*2))
        
        self.dimmed_paper_color = QColor(CONFIG.get("DARK_PAPER_TINT", "#CBD5E1")) if self.is_dark_mode else QColor("white")
        self.paper_item = QGraphicsRectItem(0, 0, px_width, px_height)
        self.paper_item.setBrush(self.dimmed_paper_color)
        self.paper_item.setPen(QPen(QColor(100, 116, 139) if self.is_dark_mode else QColor(148, 163, 184), 2))
        self.scene.addItem(self.paper_item)
        self.draw_rulers(px_width, px_height, paper_w_mm, paper_h_mm, int(10 * self.PPM))

        dash_pen = QPen(QColor(100, 116, 139) if self.is_dark_mode else QColor(148, 163, 184), 2, Qt.PenStyle.DashLine)
        
        start_idx = page_to_draw * capacity
        global_fit_mode = self.combo_fit_mode.currentText(); sharp_mode = self.combo_sharpen.currentText()
        soft_proof_active = self.check_soft_proof.isChecked(); render_intent_text = self.combo_intent.currentText()
        is_monochrome = (self.combo_color.currentData() == QPrinter.ColorMode.GrayScale)
        icc_selection = self.combo_icc.currentText()
        active_icc_path = self.custom_icc_path if icc_selection.startswith("Custom:") else ""
        is_matte_simulation = ("Matte" in icc_selection)

        doc_render_dpi = int(self.combo_doc_dpi.currentData()) if hasattr(self, 'combo_doc_dpi') else 600
        doc_color_mode = self.combo_doc_color.currentText() if hasattr(self, 'combo_doc_color') else "Normal (Original)"
        txt_font = self.combo_txt_font.currentText() if hasattr(self, 'combo_txt_font') else "Monospace"
        txt_size = self.spin_txt_size.value() if hasattr(self, 'spin_txt_size') else 10
        
        for local_slot in range(capacity):
            global_idx = start_idx + local_slot
            c = local_slot % cols
            r = local_slot // cols
            
            cx = offset_x + c * (photo_w_px + spacing_px)
            cy = offset_y + r * (photo_h_px + spacing_px)
            
            if global_idx < len(self.selected_images_for_print):
                img_data = self.selected_images_for_print[global_idx]
                
                w_code = img_data.get('w_code')
                if w_code is None:
                    raw_w = int(img_data.get('w_mm', def_w_mm) * self.PPM)
                    raw_h = int(img_data.get('h_mm', def_h_mm) * self.PPM)
                else:
                    h_code = img_data.get('h_code'); landscape = img_data.get('landscape', False)
                    if w_code < 0: w_val, h_val = self.calculate_dynamic_size(w_code)
                    else: w_val, h_val = w_code, h_code
                    if landscape: w_val, h_val = h_val, w_val
                    raw_w = int(w_val * self.PPM); raw_h = int(h_val * self.PPM)

                img_w_px = min(raw_w, max(1, printable_width))
                img_h_px = min(raw_h, max(1, printable_height))
                
                draw_x = cx + (photo_w_px - img_w_px) // 2
                draw_y = cy + (photo_h_px - img_h_px) // 2

                if draw_x < margin_px: draw_x = margin_px
                if draw_y < margin_px: draw_y = margin_px
                if draw_x + img_w_px > margin_px + printable_width: draw_x = margin_px + printable_width - img_w_px
                if draw_y + img_h_px > margin_px + printable_height: draw_y = margin_px + printable_height - img_h_px

                cell = QGraphicsRectItem(draw_x, draw_y, img_w_px, img_h_px)
                cell.setPen(dash_pen); cell.setBrush(QColor(0, 0, 0, 0)); self.scene.addItem(cell)
                self.cell_border_items.append(cell)
                if not is_borderless: self.draw_corner_crop_marks(draw_x, draw_y, img_w_px, img_h_px)

                path = img_data['path']
                try: mtime = os.path.getmtime(path)
                except OSError: mtime = 0
                    
                gray = img_data.get('gray', False); sepia = img_data.get('sepia', False)
                b = round(img_data.get('b', 1.0), 2); c = round(img_data.get('c', 1.0), 2); s = round(img_data.get('s', 1.0), 2)
                crop_x = round(img_data.get('crop_x', 0.5), 3); crop_y = round(img_data.get('crop_y', 0.5), 3)
                zoom_scale = img_data.get('zoom', 1.0); page_num = img_data.get('page', 0); high_contrast = img_data.get('high_contrast', False)
                
                item_fit_mode = img_data.get('fit_mode', global_fit_mode)
                
                cache_key = (
                    path, page_num, mtime, img_w_px, img_h_px, item_fit_mode, gray, sepia, b, c, s, sharp_mode, soft_proof_active, 
                    active_icc_path, render_intent_text, crop_x, crop_y, zoom_scale, is_monochrome, is_matte_simulation, doc_color_mode, high_contrast,
                    doc_render_dpi, txt_font, txt_size
                )

                if sync:
                    try:
                        qim = process_image_pipeline(img_data, img_w_px, img_h_px, item_fit_mode, sharp_mode, soft_proof_active, active_icc_path, 
                            render_intent_text, is_monochrome, is_matte_simulation, render_dpi=self.DPI, doc_color_mode=doc_color_mode, txt_font=txt_font, txt_size=txt_size)
                        pixmap = QPixmap.fromImage(qim)
                    except Exception: continue
                    item = self.scene.addPixmap(pixmap)
                else:
                    if cache_key in self.pixmap_cache:
                        self.pixmap_cache.move_to_end(cache_key)
                        item = self.scene.addPixmap(self.pixmap_cache[cache_key])
                    else:
                        if global_idx in old_pixmaps:
                            old_pix = old_pixmaps[global_idx]
                            if old_pix.width() != img_w_px or old_pix.height() != img_h_px:
                                old_pix = old_pix.scaled(img_w_px, img_h_px, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
                            item = self.scene.addPixmap(old_pix)
                        else:
                            placeholder = QPixmap(img_w_px, img_h_px)
                            placeholder.fill(QColor(0, 0, 0, 0))
                            item = self.scene.addPixmap(placeholder)
                        
                        worker = ImageRenderWorker(current_gen, global_idx, img_data, img_w_px, img_h_px, item_fit_mode, sharp_mode, soft_proof_active, active_icc_path, 
                            render_intent_text, is_monochrome, is_matte_simulation, min(self.DPI, doc_render_dpi), doc_color_mode, txt_font, txt_size, cache_key)
                        worker.signals.finished.connect(self.on_async_render_finished)
                        worker.signals.failed.connect(self.on_async_render_failed)
                        self.render_thread_pool.start(worker)

                item.setPos(draw_x, draw_y); item.setData(0, global_idx); self.canvas_pixmap_items[global_idx] = item
                
                if getattr(self, 'active_canvas_index', None) == global_idx:
                    self.highlight_item = QGraphicsRectItem(draw_x, draw_y, img_w_px, img_h_px)
                    highlight_color = QColor(56, 189, 248) if self.is_dark_mode else QColor(37, 99, 235)
                    pen = QPen(highlight_color, 4); pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin); self.highlight_item.setPen(pen)
                    self.highlight_item.setBrush(QColor(0, 0, 0, 0)); self.highlight_item.setData(0, global_idx); self.highlight_item.setZValue(1000)
                    self.highlight_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    self.scene.addItem(self.highlight_item)

            else:
                cell = QGraphicsRectItem(cx, cy, photo_w_px, photo_h_px)
                cell.setPen(dash_pen); cell.setBrush(QColor(0, 0, 0, 0)); self.scene.addItem(cell)
                self.cell_border_items.append(cell)
                if not is_borderless: self.draw_corner_crop_marks(cx, cy, photo_w_px, photo_h_px)
            
        if reset_zoom and not self.view.user_zoomed:
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def render_paper_to_target(self, target_painter, target_rect=None):
        self.hide_non_printable_elements()
        paper_rect = QRectF(0, 0, self.paper_px_width, self.paper_px_height)
        dest_rect = target_rect if target_rect is not None else paper_rect
        target_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        target_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if hasattr(QPainter.RenderHint, 'LosslessImageRendering'): target_painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)
        self.scene.render(target_painter, target=dest_rect, source=paper_rect)
        self.show_non_printable_elements()

    def configure_printer_settings(self, printer):
        paper_w_mm, paper_h_mm, page_size_id = self.combo_paper.currentData()
        if page_size_id is not None: printer.setPageSize(QPageSize(page_size_id))
        else: printer.setPageSize(QPageSize(QSizeF(paper_w_mm, paper_h_mm), QPageSize.Unit.Millimeter))
        if self.check_paper_landscape.isChecked(): printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        else: printer.setPageOrientation(QPageLayout.Orientation.Portrait)
        printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
        printer.setResolution(int(self.combo_dpi.currentData()))
        printer.setColorMode(self.combo_color.currentData())

    def hide_non_printable_elements(self):
        if self.paper_item: self.paper_item.setBrush(QColor("white")); self.paper_item.setPen(QPen(Qt.PenStyle.NoPen)) 
        for item in self.ruler_items: item.setVisible(False)
        if not self.check_print_borders.isChecked():
            for item in self.cell_border_items: item.setVisible(False)
        if not self.check_print_crop_marks.isChecked():
            for item in self.crop_mark_items: item.setVisible(False)
        if self.highlight_item: self.highlight_item.setVisible(False)
    
    def show_non_printable_elements(self):
        if self.paper_item:
            self.paper_item.setBrush(self.dimmed_paper_color)
            self.paper_item.setPen(QPen(QColor(100, 116, 139) if self.is_dark_mode else QColor(148, 163, 184), 2))
        for item in self.ruler_items: item.setVisible(True)
        for item in self.cell_border_items: item.setVisible(True)
        for item in self.crop_mark_items: item.setVisible(True)
        if self.highlight_item: self.highlight_item.setVisible(True)

    def show_print_preview(self):
        log_event("Opening Studio Multi-Page Print Preview...")
        printer_info = self.combo_target_printer.currentData()
        if printer_info:
            printer = QPrinter(printer_info, QPrinter.PrinterMode.HighResolution)
            printer_name = printer_info.printerName()
        else:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer_name = "Default PDF/Spooler"
            
        self.configure_printer_settings(printer)
        preview_dialog = QPrintPreviewDialog(printer, self)
        preview_dialog.setWindowTitle(f"Studio Multi-Page Print Preview - [{printer_name}]")
        preview_dialog.resize(1240, 840) 
        preview_dialog.setStyleSheet(self.styleSheet()) 
        preview_dialog.paintRequested.connect(self.handle_preview_paint)
        preview_dialog.exec()
        log_event("Closed Print Preview / CUPS Interface.")

    def handle_preview_paint(self, printer):
        capacity = self.calculate_page_capacity()
        total_pages = max(1, (len(self.selected_images_for_print) + capacity - 1) // capacity) if capacity > 0 else 1
        target_rect = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
        painter = QPainter(printer)
        for p in range(total_pages):
            if p > 0: printer.newPage()
            self.update_canvas(reset_zoom=False, sync=True, target_page=p)
            self.render_paper_to_target(painter, target_rect)
        painter.end()
        self.update_canvas(reset_zoom=False)

    def handle_print(self, printer):
        log_event("Rendering pure-white internal canvas to target spooler...")
        target_dpi = int(self.combo_dpi.currentData())
        capacity = self.calculate_page_capacity()
        total_pages = max(1, (len(self.selected_images_for_print) + capacity - 1) // capacity) if capacity > 0 else 1
        target_rect = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
        painter = QPainter(printer)
        for p in range(total_pages):
            if p > 0: printer.newPage()
            self.update_canvas(reset_zoom=False, dpi_override=target_dpi, sync=True, target_page=p)
            self.render_paper_to_target(painter, target_rect)
        painter.end()
        self.update_canvas(reset_zoom=False)

    def export_to_pdf(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Document as PDF", os.path.expanduser("~/Desktop/print_layout.pdf"), "PDF Files (*.pdf)")
        if file_path:
            log_event(f"Initiated PDF Multi-Page Export to {file_path}")
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(file_path)
            self.configure_printer_settings(printer)
            self.handle_print(printer)
            QMessageBox.information(self, "Success", f"Successfully exported {self.lbl_page_info.text()} to PDF:\n{file_path}")

    def export_to_odt(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Document as ODT", os.path.expanduser("~/Desktop/print_layout.odt"), "ODT Files (*.odt)")
        if file_path:
            log_event(f"Initiated Multi-Page ODT Export to {file_path}")
            target_dpi = int(self.combo_dpi.currentData())
            capacity = self.calculate_page_capacity()
            total_pages = max(1, (len(self.selected_images_for_print) + capacity - 1) // capacity) if capacity > 0 else 1
            
            paper_w_mm, paper_h_mm, _ = self.combo_paper.currentData()
            if self.check_paper_landscape.isChecked(): paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm

            tmp_paths = []
            try:
                content_frames = []
                manifest_entries = []
                for p in range(total_pages):
                    self.update_canvas(reset_zoom=False, dpi_override=target_dpi, sync=True, target_page=p)
                    tmp_img_path = f"/tmp/photoprint_export_{os.getpid()}_p{p}.png"
                    tmp_paths.append(tmp_img_path)
                    image = QImage(self.paper_px_width, self.paper_px_height, QImage.Format.Format_ARGB32)
                    image.fill(Qt.GlobalColor.white)
                    painter = QPainter(image)
                    self.render_paper_to_target(painter, QRectF(0, 0, self.paper_px_width, self.paper_px_height))
                    painter.end()
                    image.save(tmp_img_path)
                    
                    rel_img_path = f"Pictures/layout_p{p}.png"
                    content_frames.append(f'''<text:p><draw:frame draw:name="LayoutImage_P{p}" svg:width="{paper_w_mm}mm" svg:height="{paper_h_mm}mm"><draw:image xlink:href="{rel_img_path}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/></draw:frame></text:p>''')
                    manifest_entries.append(f'  <manifest:file-entry manifest:full-path="{rel_img_path}" manifest:media-type="image/png"/>')

                content_xml = f'''<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatibility:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" office:version="1.2"><office:body><office:text>{"".join(content_frames)}</office:text></office:body></office:document-content>'''
                manifest_xml = f'''<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>{"".join(manifest_entries)}</manifest:manifest>'''

                with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as odt:
                    odt.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
                    odt.writestr("content.xml", content_xml)
                    odt.writestr("META-INF/manifest.xml", manifest_xml)
                    for p, pth in enumerate(tmp_paths):
                        odt.write(pth, f"Pictures/layout_p{p}.png")
                
                log_event("ODT Export Complete.")
                QMessageBox.information(self, "Success", f"Successfully exported {total_pages} sheets to ODT:\n{file_path}")
            finally:
                self.update_canvas(reset_zoom=False)
                for pth in tmp_paths:
                    if os.path.exists(pth): os.remove(pth)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setDesktopFileName("linux-print-studio")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for icon_name in ("app_icon.png", "icon.png", "logo.png"):
        icon_path = os.path.join(base_dir, icon_name)
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break
            
    window = PhotoPrintApp()
    if not app.windowIcon().isNull(): window.setWindowIcon(app.windowIcon())
    sys.exit(app.exec())

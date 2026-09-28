# Linux Print Studio

A standalone, privacy-first prepress printing studio engineered natively for Linux. Built to tile, arrange, soft-proof, and print photos, multi-page PDFs, office documents, and plain text files with millimeter precision on local CUPS printers or export to print-ready PDF/ODT documents.

This utility was created for personal workflow needs and is shared freely with the community under the **GNU General Public License v3.0 (GPLv3)**.

---

## Key Features

### 🖨️ Precision Prepress Canvas & Pagination
* **Accurate Metric Workspace**: Millimeter-calibrated rulers and dynamic grid snapping.
* **Automatic Multi-Page Pagination**: Automatically calculates sheet capacity based on slot dimensions, margins, and gutters, distributing items across sequential sheets with instant page navigation.
* **Non-Destructive Viewport**: Infinite pan (Middle-click or Left-drag on canvas background), smooth zoom (`Ctrl` + Wheel), and debounced live recalculations.
* **True Prepress Engine**: Interactive screen previews use capped DPI to conserve memory, while hardware spoolers and PDF exports render at full resolution (300, 600, or 1200 DPI).

### 📸 Tab 1: Photos & Tiling Tools
* **Standard Lab Presets**: Instant sizing for Passport (Standard 35×45mm, US 51×51mm, India 35×35mm), ID cards, Stamp photos, Wallet prints, and custom dimensions (10–500 mm).
* **In-Cell Fine Framing**: Pan and crop inside any cell with `Alt` + Mouse Drag or nudge using `Alt` + Arrow keys (`Shift` for 1% micro-nudging).
* **Guillotine Cutting Guides**: Configurable printable dashed cutting borders and corner crop marks for clean manual trimming.
* **Substrate Sharpening**: Multi-tier unsharp masking calibrated for Matte, Rag, Standard Photo, or Glossy papers.
* **Color Management**: LittleCMS proofing engine with custom `.icc`/`.icm` profile loading, soft-proofing simulation, and rendering intent selection (Perceptual, Relative Colorimetric, Saturation, Absolute).

### 📄 Tab 2: Documents & Typography
* **Universal Document Support**: Seamlessly browse and place `.pdf`, `.docx`, `.doc`, `.odt`, `.rtf`, `.txt`, `.md`, and `.log` files alongside photos.
* **Automatic Full-Page Sizing**: Documents default to Full Page mode (`1-up`) with letterbox protection to prevent margins or headers from being clipped.
* **Multi-Page Extraction**: Double-clicking or dragging a multi-page document prompts you to import either the entire document across sequential sheets or a specific page.
* **In-Cell Page Selector**: Right-click any placed document cell to cycle to a different page number on the fly.
* **High-Contrast Text Binarization**: One-click thresholding converts colored or faint text scans to solid pigment black.
* **Vector Text Typography**: Customizable font family (`Monospace`, `Sans-Serif`, `Serif`) and point sizing for plain text and logs.

### ⚙️ Tab 3: Print & Sheet (Universal Controls)
* **Physical Paper Sizes**: Quick selection for A4, A3, A5, B5, Letter, Legal, 4×6, 5×7, and 8×10.
* **Edge Bleed**: Toggle borderless printing (0 mm bleed) or specify custom sheet margins.
* **Hardware Spooler**: Direct CUPS integration with printer selection and automatic query of proprietary driver media options (`MediaType` / `Media`).
* **Color Output Modes**: Toggle between full RGB color and dedicated monochrome black-and-white.

### ⚡ Smooth Asynchronous Performance
* **Independent Dual Thread Pools**: Background gallery thumbnail generation runs in a dedicated thread pool completely isolated from the canvas rendering engine. Browsing folders with hundreds of files never freezes the UI.
* **RAM-Bounded LRU Caches**: Dual Least-Recently-Used (LRU) memory pools for canvas preview pixmaps and folder thumbnails prevent RAM bloat.
* **Instant Parent Navigation**: Dedicated `▲ Up` button allows rapid traversal through folder hierarchies up to your designated workspace root.

### 🔒 Safety & Privacy by Design
* **100% Non-Destructive**: Every file is opened in **strict read-only mode**. The application will never modify, overwrite, re-encode, or delete source files on your computer.
* **Sandboxed Ephemeral Cache**: Intermediate document renders write exclusively to `/tmp/photoprint_doc_cache_<uid>` and are automatically purged when the program closes.
* **Zero Telemetry**: Completely self-contained, air-gapped, and offline. No network requests, tracking, or telemetry of any kind.

---

## Supported File Formats

| Category | Extensions |
| :--- | :--- |
| **Raster Images** | `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp` |
| **Vector & Office Documents** | `.pdf`, `.docx`, `.doc`, `.odt`, `.rtf` |
| **Plain Text & Notes** | `.txt`, `.text`, `.log`, `.md` |

---

## Installation Guide

Select the commands matching your Linux distribution:

### 1. Debian / Ubuntu / Linux Mint / LMDE
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-pyqt6 python3-pil poppler-utils cups-client libreoffice

# Optional: Accelerated in-process PDF engine
pip install --break-system-packages pypdfium2

```

### 2. Fedora / RHEL / Rocky Linux

```bash
sudo dnf install -y python3 python3-pip python3-qt6 python3-pillow poppler-utils cups-client libreoffice-core libreoffice-writer

# Optional: Accelerated in-process PDF engine
pip install pypdfium2

```

### 3. Arch Linux / Manjaro

```bash
sudo pacman -S --needed python python-pip python-pyqt6 python-pillow poppler libreoffice-fresh cups

# Optional: Accelerated in-process PDF engine
pip install pypdfium2

```

### 4. openSUSE (Tumbleweed / Leap)

```bash
sudo zypper install -y python3 python3-pip python3-PyQt6 python3-Pillow poppler-tools cups-client libreoffice

# Optional: Accelerated in-process PDF engine
pip install pypdfium2

```

---

## Running the Application

### Option A: Direct Launch (System Packages)

If you installed dependencies via your distribution's package manager:

```bash
python3 photoprint.py

```

### Option B: Running in a Python Virtual Environment (Recommended)

To adhere to PEP 668 on modern Linux distributions:

```bash
# 1. Clone or navigate to the repository directory
git clone https://github.com/equinwx/linux-print-studio.git
cd linux-print-studio

# 2. Create and activate a clean virtual environment
python3 -m venv --system-site-packages venv
source venv/bin/activate

# 3. Install requirements
pip install PyQt6 pillow

# Optional: Add fast in-process PDF renderers
pip install pypdfium2 PyMuPDF

# 4. Launch the application
python3 photoprint.py

```

---

## Desktop Integration (App Launcher & Icon)

To integrate the application with your desktop menu and taskbar:

1. **Place an Icon**:
Place any PNG image named `app_icon.png` in the same directory as `photoprint.py`.
2. **Create the Desktop Shortcut**:
```bash
mkdir -p ~/.local/share/applications
nano ~/.local/share/applications/linux-print-studio.desktop

```


3. **Paste the Configuration** (update the paths to match your actual directory):
```ini
[Desktop Entry]
Version=1.0
Type=Application
Name=Linux Print Studio
Comment=Native Prepress Document & Photo Printing Studio
Exec=/usr/bin/python3 /absolute/path/to/linux-print-studio/photoprint.py
Icon=/absolute/path/to/linux-print-studio/app_icon.png
Terminal=false
Categories=Graphics;Photography;Publishing;
StartupWMClass=photoprint

```


4. **Apply Permissions**:
```bash
chmod +x ~/.local/share/applications/linux-print-studio.desktop
update-desktop-database ~/.local/share/applications

```



---

## Keyboard Shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl` + `Z` | Undo last change |
| `Ctrl` + `Y` / `Ctrl` + `Shift` + `Z` | Redo change |
| `Ctrl` + `C` | Copy selected cell to clipboard |
| `Ctrl` + `V` | Paste cell from clipboard |
| `Delete` / `Backspace` | Remove selected photo or document page |
| `Alt` + Mouse Drag | Fine-tune in-cell framing crop |
| `Alt` + Arrow Keys | Nudge framing crop by 4% increments |
| `Alt` + `Shift` + Arrow Keys | Micro-nudge framing crop by 1% increments |
| `Ctrl` + Mouse Wheel | Zoom canvas workspace |
| Middle Mouse Drag | Pan canvas workspace |
| `Esc` | Quit application |

---

## Offline Configuration (`CONFIG`)

The `CONFIG` dictionary at the top of `photoprint.py` allows adjusting defaults without modifying application logic:

```python
CONFIG = {
    "DEFAULT_THEME": "dark",          # Starting theme: "dark" or "light"
    "UI_FONT_SIZE": 13,               # Global UI font size (px)
    "LEFT_PANEL_WIDTH": 280,          # Browser width (calibrated for 3 columns)
    "RIGHT_PANEL_WIDTH": 325,         # Inspector sidebar width
    "ENABLE_TERMINAL_LOGS": True,     # Console logging toggle
    "CANVAS_PADDING": 140,            # Blank padding around canvas paper
    "DARK_PAPER_TINT": "#CBD5E1",     # Eye-comfort soft paper tint on live canvas
    "MAX_LIVE_DPI": 600,              # Display preview DPI cap (saves RAM)
    "PIXMAP_CACHE_LIMIT": 64,         # Canvas preview pixmaps kept in RAM
    "THUMBNAIL_CACHE_LIMIT": 256,     # Decoded thumbnails kept in RAM
    "MAX_UNDO_HISTORY": 50,           # Undo/Redo depth
    "DEFAULT_PAPER_SIZE": 0,          # 0 = A4, 1 = A3, 2 = A5, 3 = B5, 4 = Letter, etc.
    "DEFAULT_PHOTO_SIZE": 5,          # Photo preset default (5 = Small ID)
    "DEFAULT_DOC_DPI": 600,           # Render quality for vector PDF/document text
}

```

---

## License

This project is licensed under the **GNU General Public License v3.0 (GPLv3)**.

You are free to run, study, modify, and redistribute this software. If you distribute modified versions of this program, you must make the source code available under the same GPLv3 terms. See the [LICENSE](https://github.com/equinwx/linux-print-studio/blob/main/LICENSE) file for the full license text.

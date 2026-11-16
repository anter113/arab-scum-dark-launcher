import configparser
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import (QEasingCurve, QEvent, QPointF, QPropertyAnimation,
                          QRectF, Qt, QTimer, QUrl, pyqtProperty, pyqtSignal)
from PyQt5.QtGui import (QColor, QDesktopServices, QFont, QIcon, QImage,
                         QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                         QPolygonF, QRadialGradient, QTransform)
from PyQt5.QtWidgets import (QAbstractButton, QApplication, QGraphicsDropShadowEffect,
                             QLabel, QLineEdit, QMessageBox, QProgressBar,
                             QPushButton, QWidget)

APP_NAME = "Arab SCUM Dark"
APP_VERSION = "0.2.5"
SCUM_APP_ID = "513710"
SERVER_CONNECT = "176.57.173.194:28802"
YOUTUBE_URL = "https://www.youtube.com/@AboAdamH"
# Remote manifest (GitHub raw). Leave empty to use a local mod_manifest.json.
MANIFEST_URL = "https://raw.githubusercontent.com/anter113/arab-scum-dark-mods/main/mod_manifest.json"
# Latest launcher build descriptor (version, url, size, sha256).
LAUNCHER_UPDATE_URL = os.getenv(
    "ARABSCUM_UPDATE_URL",
    "https://raw.githubusercontent.com/anter113/arab-scum-dark-mods/main/launcher_update.json")

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ASSET_DIR = BASE_DIR / "assets"
CFG_DIR = Path(os.getenv("APPDATA", Path.home())) / "ArabScumDark"
CFG_FILE = CFG_DIR / "launcher_config.ini"
LOG_FILE = CFG_DIR / "launcher.log"


def log_line(message):
    try:
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except Exception:
        pass


def show_error(message):
    log_line(message)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message[-1800:], APP_NAME, 0x10)
    except Exception:
        pass


def log_hook(exc_type, exc, tb):
    show_error("Unexpected error:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))


def _thread_hook(args):
    log_hook(args.exc_type, args.exc_value, args.exc_traceback)


def _qt_message_handler(mode, context, message):
    log_line(f"qt[{mode}]: {message}")


def version_tuple(text):
    try:
        return tuple(int(p) for p in re.findall(r"\d+", str(text))[:3])
    except Exception:
        return ()


def cleanup_old_exe():
    if not getattr(sys, "frozen", False):
        return
    try:
        old = Path(sys.executable + ".old")
        if old.exists():
            old.unlink()
    except OSError:
        pass

ACCENT = "#FF2E4D"
HOT = "#3D8BFF"
TEXT = "#E9E5DD"
MUTED = "#8B9199"
INK = "#0B1220"


def display_font(size, spacing=1.5):
    f = QFont("Impact", int(size))
    f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def label_font(size=8.0, spacing=2.2, weight=QFont.DemiBold,
               family="Bahnschrift SemiCondensed"):
    f = QFont(family)
    f.setPointSizeF(size)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def mono_font(size=8.5, spacing=0.5, weight=QFont.Normal):
    f = QFont("Cascadia Mono")
    f.setPointSizeF(size)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t),
                  int(a.alpha() + (b.alpha() - a.alpha()) * t))


def chamfer_path(rect, cut=12, corners=("tr", "bl")):
    r = QRectF(rect)
    tl = cut if "tl" in corners else 0
    tr = cut if "tr" in corners else 0
    br = cut if "br" in corners else 0
    bl = cut if "bl" in corners else 0
    poly = QPolygonF([
        QPointF(r.left() + tl, r.top()),
        QPointF(r.right() - tr, r.top()),
        QPointF(r.right(), r.top() + tr),
        QPointF(r.right(), r.bottom() - br),
        QPointF(r.right() - br, r.bottom()),
        QPointF(r.left() + bl, r.bottom()),
        QPointF(r.left(), r.bottom() - bl),
        QPointF(r.left(), r.top() + tl),
    ])
    path = QPainterPath()
    path.addPolygon(poly)
    path.closeSubpath()
    return path


def steam_roots():
    roots = []
    try:
        import winreg
        for hive, key, value in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(Path(winreg.QueryValueEx(k, value)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    return roots


def _paks_in_game_dir(base):
    for candidate in (base / "Content" / "Paks", base / "SCUM" / "Content" / "Paks"):
        if (candidate.parent.parent / "Binaries" / "Win64" / "SCUM.exe").exists():
            return candidate
    return None


def find_scum_paks():
    libraries = [root / "steamapps" for root in steam_roots()]
    for lib in list(libraries):
        vdf = lib / "libraryfolders.vdf"
        try:
            if vdf.exists():
                for m in re.finditer(r'"path"\s*"([^"]+)"', vdf.read_text(errors="ignore")):
                    libraries.append(Path(m.group(1).replace("\\\\", "\\")) / "steamapps")
        except OSError:
            pass
    libraries.append(Path(r"C:\Program Files (x86)\Steam\steamapps"))
    for lib in libraries:
        try:
            found = _paks_in_game_dir(lib / "common" / "SCUM")
        except OSError:
            found = None
        if found:
            return found
    return None


def valid_paks(path):
    try:
        return path is not None and (path.parent.parent / "Binaries" / "Win64" / "SCUM.exe").exists()
    except OSError:
        return False


def resolve_paks(selected):
    p = Path(selected)
    if p.is_file():
        p = p.parent
    for _ in range(4):
        for rel in ("", "Paks", "Content/Paks", "SCUM/Content/Paks", "SCUM/SCUM/Content/Paks"):
            candidate = p / rel if rel else p
            if candidate.name.lower() == "paks" and candidate.is_dir() and valid_paks(candidate):
                return candidate
        if p.parent == p:
            break
        p = p.parent
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_config():
    cfg = configparser.ConfigParser()
    if CFG_FILE.exists():
        cfg.read(CFG_FILE, encoding="utf-8-sig")
    cfg.setdefault("paths", {})
    cfg.setdefault("settings", {})
    cfg.setdefault("mods", {})
    return cfg


def save_config(cfg):
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)


def inst_env(extra=None):
    # The PyQt5 runtime hook and bootloader point PATH at this process's _MEI
    # temp dir. Children inheriting that load DLLs from it, which blocks the
    # temp dir cleanup on exit; re-executed copies also run inside it.
    mei = (os.environ.get("_PYI_APPLICATION_HOME_DIR") or "").lower()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("_PYI") and k not in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH")}
    if mei:
        env["PATH"] = os.pathsep.join(
            p for p in os.environ.get("PATH", "").split(os.pathsep)
            if not p.lower().startswith(mei))
    if extra:
        env.update(extra)
    return env


class Toggle(QAbstractButton):
    def __init__(self, checked=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 20)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"posLevel", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def get_posLevel(self):
        return self._pos

    def set_posLevel(self, value):
        self._pos = float(value)
        self.update()

    posLevel = pyqtProperty(float, fget=get_posLevel, fset=set_posLevel)

    def nextCheckState(self):
        super().nextCheckState()
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if self.isChecked() else 0.0)
        self._anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        track = chamfer_path(r, 5)
        p.setPen(Qt.NoPen)
        p.setBrush(mix(QColor(255, 255, 255, 26), QColor(255, 46, 77, 235), self._pos))
        p.drawPath(track)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(255, 255, 255, 34))
        p.drawPath(track)

        p.setPen(QColor(255, 255, 255, 46))
        for gx in (r.left() + 15, r.left() + 22, r.left() + 29):
            p.drawLine(QPointF(gx, r.bottom() - 4), QPointF(gx, r.bottom()))

        kw, kh = 14, 14
        x = r.left() + 3 + (r.width() - kw - 6) * self._pos
        knob = QPolygonF([QPointF(x + 4, r.center().y() - kh / 2),
                          QPointF(x + kw, r.center().y() - kh / 2),
                          QPointF(x + kw - 4, r.center().y() + kh / 2),
                          QPointF(x, r.center().y() + kh / 2)])
        p.setPen(Qt.NoPen)
        p.setBrush(mix(QColor("#C9CED6"), QColor(INK), self._pos))
        p.drawPolygon(knob)
        p.setPen(QPen(mix(QColor(61, 139, 255, 70), QColor(61, 139, 255, 230), self._pos), 1.6))
        p.drawLine(QPointF(x + 9.5, r.center().y() - 3), QPointF(x + 7.5, r.center().y() + 3))
        p.end()


class CreditPlate(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(172, 22)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = chamfer_path(r, 7)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(6, 8, 11, 178))
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(255, 255, 255, 34))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(61, 139, 255, 210))
        p.drawRect(QRectF(r.left(), r.center().y() - 5, 2, 10))

        p.setFont(mono_font(6.4, 0.8))
        lead = "DEVELOPMENT BY : "
        p.setPen(QColor(150, 158, 168))
        p.drawText(QRectF(10, r.top(), r.width() - 10, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, lead)
        p.setPen(QColor(ACCENT))
        p.drawText(QRectF(10 + p.fontMetrics().width(lead) + 2, r.top(), 80, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, "ANTER")
        p.end()


class Dot(QWidget):
    def __init__(self, color="#6BE08A", size=10):
        super().__init__()
        self._color = QColor(color)
        self._phase = 0.0
        self.setFixedSize(size, size)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def set_phase(self, value):
        self._phase = value
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        beat = 0.5 + 0.5 * math.sin(self._phase * 2.4)
        p.translate(w / 2.0, h / 2.0)
        p.rotate(45)
        halo = QColor(self._color)
        halo.setAlphaF(0.14 + 0.34 * beat)
        p.setBrush(halo)
        p.drawRect(QRectF(-w / 2.0, -h / 2.0, w, h))
        core = QColor(self._color)
        core.setAlphaF(0.85 + 0.15 * beat)
        p.setBrush(core)
        p.drawRect(QRectF(-w / 4.0, -h / 4.0, w / 2.0, h / 2.0))
        p.end()


class IconBadge(QWidget):
    def __init__(self, path, size=60):
        super().__init__()
        self._pix = QPixmap(str(path))
        self._tinted = None
        self.setFixedSize(size, size)

    def _duotone(self):
        if self._tinted is not None:
            return self._tinted
        w, h = self.width(), self.height()
        scaled = self._pix.scaled(self.size(), Qt.KeepAspectRatioByExpanding,
                                  Qt.SmoothTransformation)
        gray = scaled.toImage().convertToFormat(QImage.Format_Grayscale8)
        ox, oy = (scaled.width() - w) // 2, (scaled.height() - h) // 2
        out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        for y in range(h):
            for x in range(w):
                src = gray.pixelColor(ox + x, oy + y)
                lum = src.value() / 255.0
                if lum < 0.5:
                    col = mix(QColor(38, 8, 16), QColor(255, 46, 77), lum * 2.0)
                else:
                    col = mix(QColor(255, 46, 77), QColor(74, 155, 255),
                              (lum - 0.5) * 2.0)
                col.setAlpha(src.alpha())
                out.setPixelColor(x, y, col)
        self._tinted = QPixmap.fromImage(out)
        return self._tinted

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = chamfer_path(r, 12)
        p.setClipPath(path)
        if self._pix.isNull():
            p.fillRect(r, QColor("#0D1014"))
        else:
            p.drawPixmap(0, 0, self._duotone())
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(255, 255, 255, 40))
        p.drawPath(path)
        p.setPen(QPen(QColor(255, 46, 77, 220), 2))
        p.drawLine(QPointF(r.left(), r.top() + 12), QPointF(r.left(), r.top() + 28))
        p.end()


class ServerCard(QWidget):
    def __init__(self, name, address, tag, width=452, height=92):
        super().__init__()
        self._name = name
        self._address = address
        self._tag = tag
        self._phase = 0.0
        self.setFixedSize(width, height)

    def set_phase(self, value):
        self._phase = value
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = chamfer_path(r, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 10))
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(255, 255, 255, 30))
        p.drawPath(path)

        beat = 0.5 + 0.5 * math.sin(self._phase * 2.1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 46, 77, int(130 + 110 * beat)))
        p.drawRect(QRectF(r.left(), r.top() + 16, 3, r.height() - 32))

        p.setPen(QPen(QColor(61, 139, 255, 170), 1))
        p.drawLine(QPointF(r.right() - 22, r.bottom()), QPointF(r.right() - 22, r.bottom() - 9))
        p.drawLine(QPointF(r.right() - 22, r.bottom()), QPointF(r.right() - 31, r.bottom()))

        p.translate(28, r.height() / 2.0)
        p.rotate(45)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(61, 139, 255, 70 + int(120 * beat)))
        p.drawRect(QRectF(-6, -6, 12, 12))
        p.setBrush(QColor(61, 139, 255, 235))
        p.drawRect(QRectF(-3, -3, 6, 6))
        p.resetTransform()

        p.setFont(display_font(26, 1.4))
        fm = p.fontMetrics()
        parts = self._name.split("\\")
        colors = (QColor(ACCENT), QColor(HOT))
        x = 48.0
        for i, part in enumerate(parts[:2]):
            p.setPen(colors[i])
            p.drawText(QRectF(x, 10, 260, 38), Qt.AlignVCenter | Qt.AlignLeft, part)
            x += fm.width(part)
            if i == 0 and len(parts) > 1:
                p.setPen(QColor(110, 120, 136))
                p.drawText(QRectF(x + 2, 10, 30, 38), Qt.AlignVCenter | Qt.AlignLeft, "\\")
                x += fm.width("\\") + 6
        line_w = max(46.0, min(160.0, x - 48 - 4))
        p.setPen(QPen(QColor(255, 46, 77, 190), 2))
        p.drawLine(QPointF(50, 49), QPointF(50 + line_w, 49))
        p.setPen(QColor(61, 139, 255, 190))
        p.setFont(mono_font(7.4, 1.0))
        p.drawText(QRectF(56 + line_w, 41, 140, 16), Qt.AlignVCenter | Qt.AlignLeft, "// LINK UP")
        p.setPen(QColor(MUTED))
        p.setFont(mono_font(9, 0.8))
        p.drawText(QRectF(50, 58, r.width() - 170, 22), Qt.AlignVCenter | Qt.AlignLeft, self._address)

        badge = QRectF(r.right() - 96, r.center().y() - 15, 74, 30)
        bpath = chamfer_path(badge, 7)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(61, 139, 255, 26))
        p.drawPath(bpath)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(61, 139, 255, 210))
        p.drawPath(bpath)
        p.setPen(QColor(HOT))
        p.setFont(label_font(8.0, 2.4))
        p.drawText(badge, Qt.AlignCenter, self._tag)
        p.end()


class PanelButton(QPushButton):
    def __init__(self, text, kind="ghost", cut=10, font=None, danger=False):
        super().__init__(text)
        self.kind = kind
        self.cut = cut
        self.danger = danger
        self._hover = 0.0
        self._phase = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(font or label_font(9, 2.2))
        self._anim = QPropertyAnimation(self, b"hoverLevel", self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.glow = None
        if kind == "primary":
            self.glow = QGraphicsDropShadowEffect(self)
            self.glow.setOffset(0, 0)
            self.glow.setBlurRadius(30)
            self.glow.setColor(QColor(255, 46, 77, 190))
            self.setGraphicsEffect(self.glow)
            self._pulse = QPropertyAnimation(self.glow, b"blurRadius", self)
            self._pulse.setStartValue(20)
            self._pulse.setEndValue(48)
            self._pulse.setDuration(2100)
            self._pulse.setEasingCurve(QEasingCurve.InOutSine)
            self._pulse.setLoopCount(-1)
            self._pulse.start()

    def get_hoverLevel(self):
        return self._hover

    def set_hoverLevel(self, value):
        self._hover = float(value)
        self.update()

    hoverLevel = pyqtProperty(float, fget=get_hoverLevel, fset=set_hoverLevel)

    def set_phase(self, value):
        self._phase = value
        if self.isVisible():
            self.update()

    def _aim(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event):
        if self.isEnabled():
            self._aim(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._aim(0.0)
        super().leaveEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange and self.glow is not None:
            if self.isEnabled():
                self.glow.setBlurRadius(28)
                self._pulse.start()
            else:
                self._pulse.stop()
                self.glow.setBlurRadius(0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        enabled = self.isEnabled()
        if self.kind == "primary":
            self._paint_primary(p, r, enabled)
        elif self.kind == "chroma":
            self._paint_chroma(p, r)
        elif self.kind == "youtube":
            self._paint_youtube(p, r, enabled)
        elif self.kind == "fill":
            self._paint_fill(p, r, enabled)
        else:
            self._paint_ghost(p, r, enabled)
        p.end()

    def _paint_primary(self, p, r, enabled):
        path = chamfer_path(r, 13)
        top = QColor(255, 96, 116) if enabled else QColor(86, 58, 66)
        bot = QColor(200, 26, 52) if enabled else QColor(62, 40, 48)
        if enabled:
            top = mix(top, QColor(255, 154, 170), self._hover)
            bot = mix(bot, QColor(224, 64, 86), self._hover)
        grad = QLinearGradient(r.left(), r.top(), r.left(), r.bottom())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(255, 140, 158, 160 if enabled else 60))
        p.drawPath(path)
        p.setPen(QPen(QColor(255, 228, 230, 100 if enabled else 30), 1))
        p.drawLine(QPointF(r.left() + 14, r.top() + 1.5), QPointF(r.right() - 2, r.top() + 1.5))

        red = QColor(HOT) if enabled else QColor(96, 52, 62)
        red.setAlpha(230 if enabled else 120)
        p.setPen(Qt.NoPen)
        p.setBrush(red)
        p.drawRect(QRectF(r.left() + 18, r.center().y() - 13, 4, 26))

        p.setPen(QColor("#F2F7FF") if enabled else QColor(108, 118, 136))
        p.setFont(self.font())
        p.drawText(QRectF(r.left() + 36, r.top(), r.width() - 110, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())

        p.setFont(display_font(12, 1.0))
        chev = QColor(HOT) if enabled else QColor(108, 118, 136)
        chev.setAlpha(235 if enabled else 120)
        p.setPen(chev)
        x = r.right() - 56 + self._hover * 7
        p.drawText(QRectF(x, r.top(), 48, r.height()),
                   Qt.AlignVCenter | Qt.AlignRight, ">>>")

        if enabled:
            p.setClipPath(path)
            cycle = (self._phase % 5.2) / 5.2
            sx = -0.35 * r.width() + cycle * 1.7 * r.width()
            band = QLinearGradient(r.left() + sx, 0, r.left() + sx + 160, 0)
            band.setColorAt(0.0, QColor(255, 255, 255, 0))
            band.setColorAt(0.5, QColor(255, 255, 255, 42))
            band.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(r, band)

    def _paint_ghost(self, p, r, enabled):
        path = chamfer_path(r, 9)
        tint = HOT if self.danger else ACCENT
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(8 + 14 * self._hover) if enabled else 6))
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(mix(QColor(255, 255, 255, 44), QColor(tint), 
                     self._hover if enabled else 0.0))
        p.drawPath(path)
        marker = QColor(tint)
        marker.setAlpha(min(255, int(90 + 150 * self._hover)) if enabled else 50)
        p.setPen(Qt.NoPen)
        p.setBrush(marker)
        p.drawRect(QRectF(r.left() + 15, r.center().y() - 7, 3, 14))
        p.setPen(mix(QColor(206, 202, 194), QColor(255, 255, 255),
                     self._hover if enabled else 0.0))
        p.setFont(self.font())
        p.drawText(r.adjusted(24, 0, 0, 0), Qt.AlignCenter, self.text())

    def _paint_fill(self, p, r, enabled):
        path = chamfer_path(r, 9)
        top = QColor(86, 160, 255) if enabled else QColor(52, 72, 100)
        bot = QColor(32, 104, 212) if enabled else QColor(34, 48, 68)
        if enabled:
            top = mix(top, QColor(142, 196, 255), self._hover)
            bot = mix(bot, QColor(58, 132, 238), self._hover)
        grad = QLinearGradient(r.left(), r.top(), r.left(), r.bottom())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(128, 188, 255, 175 if enabled else 70))
        p.drawPath(path)
        p.setPen(QPen(QColor(235, 246, 255, 95 if enabled else 30), 1))
        p.drawLine(QPointF(r.left() + 10, r.top() + 1.5), QPointF(r.right() - 10, r.top() + 1.5))
        p.setPen(QColor("#F4F9FF") if enabled else QColor(118, 138, 160))
        p.setFont(self.font())
        p.drawText(r, Qt.AlignCenter, self.text())

    def _paint_youtube(self, p, r, enabled):
        path = chamfer_path(r, 7)
        hover = self._hover if enabled else 0.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 46, 77, int(14 + 30 * hover)))
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(mix(QColor(255, 46, 77, 95), QColor(255, 46, 77, 235), hover))
        p.drawPath(path)

        iw, ih = 20, 14
        ix = r.left() + 11
        iy = r.center().y() - ih / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(mix(QColor(198, 34, 56), QColor(255, 46, 77), hover))
        p.drawRoundedRect(QRectF(ix, iy, iw, ih), 3.5, 3.5)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPolygon(QPolygonF([QPointF(ix + 8.0, iy + 3.5),
                                 QPointF(ix + 8.0, iy + ih - 3.5),
                                 QPointF(ix + 14.5, iy + ih / 2.0)]))

        core = mix(QColor(206, 202, 194), QColor(255, 255, 255), hover)
        p.setPen(core)
        p.setFont(self.font())
        p.drawText(r.adjusted(38, 0, 10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())

    def _paint_chroma(self, p, r):
        path = chamfer_path(r, 7)
        fill = QColor(220, 40, 62) if self.danger else QColor(255, 255, 255, 24)
        fill.setAlphaF(fill.alphaF() * (0.45 + 0.55 * self._hover))
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(255, 255, 255, 96))
        p.drawPath(path)
        p.setPen(QColor("#FFFFFF") if self.danger and self._hover > 0.4 else QColor("#CFD4DA"))
        p.setFont(self.font())
        p.drawText(r, Qt.AlignCenter, self.text())


class PulseProgress(QProgressBar):
    def __init__(self):
        super().__init__()
        self._phase = 0.0

    def set_phase(self, value):
        self._phase = value
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        span = self.maximum() - self.minimum()
        frac = (self.value() - self.minimum()) / span if span > 0 else 0.0
        fw = w * max(0.0, min(1.0, frac))
        if fw <= 0:
            p.end()
            return
        fill = QLinearGradient(0, 0, fw, 0)
        fill.setColorAt(0.0, QColor(255, 46, 77))
        fill.setColorAt(1.0, QColor(255, 120, 140))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(0, 0, fw, h), h / 2, h / 2)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, fw, h), h / 2, h / 2)
        p.setClipPath(clip)
        x = (self._phase * 1.3 % 1.0) * (fw + 160) - 160
        shine = QLinearGradient(x, 0, x + 110, 0)
        shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.5, QColor(255, 255, 255, 96))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, fw, h), shine)
        p.end()


class LauncherWindow(QWidget):
    progress_signal = pyqtSignal(int, int)
    done_signal = pyqtSignal(str, bool)
    launcher_check_signal = pyqtSignal(str, object)
    launcher_dl_signal = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(1120, 640)
        self.setWindowIcon(QIcon(str(ASSET_DIR / "icon_app.png")))
        self._drag = None
        self._busy = False
        self._game_proc = None
        self._t = 0.0
        self._last = time.perf_counter()
        self._sparks = []
        self._fire_pm = None
        self._upd_checking = False
        self._launcher_update = None
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

        self.cfg = load_config()
        stored = self.cfg.get("paths", "paks_dir", fallback="")
        self.paks = Path(stored) if stored and valid_paks(Path(stored)) else find_scum_paks()
        if self.paks:
            self.cfg["paths"]["paks_dir"] = str(self.paks)
            save_config(self.cfg)

        self.bg = QPixmap(str(ASSET_DIR / "keyart.png"))
        self.progress_signal.connect(self._apply_progress)
        self.done_signal.connect(self._apply_done)
        self.launcher_check_signal.connect(self._apply_launcher_state)
        self.launcher_dl_signal.connect(self._apply_launcher_download)
        self._build_ui()
        self._center()
        self._refresh_folder()
        self._build_scene()
        self._spawn_fire()
        self._timer.start()
        QTimer.singleShot(1600, lambda: self.check_launcher_update(auto=True))

    # ---- painting -------------------------------------------------------
    def _build_scene(self):
        w, h = self.width(), self.height()
        if self.bg.isNull():
            self._bg_pm = QPixmap(w, h)
            self._bg_pm.fill(QColor("#07090C"))
        else:
            scaled = self.bg.scaled(int(w * 1.09), int(h * 1.09),
                                    Qt.KeepAspectRatioByExpanding,
                                    Qt.SmoothTransformation)
            self._bg_pm = QPixmap(scaled.size())
            self._bg_pm.fill(Qt.transparent)
            bp = QPainter(self._bg_pm)
            bp.setRenderHint(QPainter.SmoothPixmapTransform)
            bp.drawPixmap(0, 0, scaled)
            grade = QLinearGradient(0, 0, scaled.width(), 0)
            grade.setColorAt(0.0, QColor(200, 40, 70, 150))
            grade.setColorAt(0.5, QColor(74, 26, 44, 120))
            grade.setColorAt(1.0, QColor(30, 70, 180, 140))
            bp.setCompositionMode(QPainter.CompositionMode_Overlay)
            bp.fillRect(self._bg_pm.rect(), grade)
            bp.end()

        self._overlay_pm = QPixmap(w, h)
        self._overlay_pm.fill(Qt.transparent)
        p = QPainter(self._overlay_pm)
        p.setRenderHint(QPainter.Antialiasing)
        left = QLinearGradient(0, 0, w * 0.78, 0)
        left.setColorAt(0.0, QColor(7, 9, 12, 246))
        left.setColorAt(0.45, QColor(7, 9, 12, 214))
        left.setColorAt(0.72, QColor(7, 9, 12, 90))
        left.setColorAt(1.0, QColor(7, 9, 12, 18))
        p.fillRect(QRectF(0, 0, w, h), left)
        bottom = QLinearGradient(0, h * 0.62, 0, h)
        bottom.setColorAt(0.0, QColor(5, 7, 10, 0))
        bottom.setColorAt(1.0, QColor(5, 7, 10, 205))
        p.fillRect(QRectF(0, 0, w, h), bottom)
        p.end()

        self._glow_pm = QPixmap(w, h)
        self._glow_pm.fill(Qt.transparent)
        p = QPainter(self._glow_pm)
        glow = QRadialGradient(w * 0.20, h * 0.42, 470)
        glow.setColorAt(0.0, QColor(255, 46, 77, 46))
        glow.setColorAt(1.0, QColor(255, 46, 77, 0))
        p.fillRect(QRectF(0, 0, w, h), glow)
        p.end()

    def _new_spark(self, w, h, start=False):
        return {
            "x": random.uniform(0, w),
            "y": h - random.uniform(0, 22) if start else h - random.uniform(0, 8),
            "v": random.uniform(28, 82),
            "ph": random.uniform(0, math.tau),
            "life": random.uniform(0.3, 1.0) if start else 1.0,
            "decay": random.uniform(0.28, 0.60),
            "r": random.uniform(0.6, 1.7),
        }

    def _spawn_fire(self):
        w, h = self.width(), self.height()
        src = QPixmap(str(ASSET_DIR / "fire_strip.png"))
        self._fire_pm = None
        self._sparks = [self._new_spark(w, h, start=True) for _ in range(34)]
        if src.isNull():
            return
        fade = 64.0
        specs = ((206, False), (170, True), (226, False), (184, True), (204, False))
        tiles = []
        span = 0.0
        for height, mirror in specs:
            tw = max(1, int(round(src.width() * height / src.height())))
            pm = src.scaled(tw, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            if mirror:
                pm = pm.transformed(QTransform().scale(-1.0, 1.0))
            layer = QPixmap(pm.size())
            layer.fill(Qt.transparent)
            q = QPainter(layer)
            q.setRenderHint(QPainter.SmoothPixmapTransform)
            q.drawPixmap(0, 0, pm)
            q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            edge = QLinearGradient(0, 0, tw, 0)
            edge.setColorAt(0.0, QColor(0, 0, 0, 0))
            edge.setColorAt(fade / tw, QColor(0, 0, 0, 255))
            edge.setColorAt(1.0 - fade / tw, QColor(0, 0, 0, 255))
            edge.setColorAt(1.0, QColor(0, 0, 0, 0))
            q.fillRect(layer.rect(), edge)
            q.end()
            tiles.append((layer, tw))
            span += tw - fade
        span += fade
        ch = max(layer.height() for layer, _ in tiles)
        canvas = QPixmap(int(span), ch)
        canvas.fill(Qt.black)
        q = QPainter(canvas)
        q.setRenderHint(QPainter.SmoothPixmapTransform)
        q.setCompositionMode(QPainter.CompositionMode_Plus)
        x = 0.0
        for layer, tw in tiles:
            q.drawPixmap(int(round(x)), ch - layer.height(), layer)
            x += tw - fade
        q.end()
        self._fire_pm = canvas
        self._fire_x = -(canvas.width() - w) / 2.0

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.12, now - self._last)
        self._last = now
        self._t += dt
        w, h = self.width(), self.height()
        for s in self._sparks:
            s["y"] -= s["v"] * dt
            s["life"] -= s["decay"] * dt
            if s["life"] <= 0 or s["y"] < h - 300:
                s.update(self._new_spark(w, h))
        self.launch_btn.set_phase(self._t)
        self.status_dot.set_phase(self._t)
        self.server_card.set_phase(self._t)
        self.progress.set_phase(self._t)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 14, 14)
        p.setClipPath(clip)

        mx = max(0.0, (self._bg_pm.width() - self.width()) / 2.0) * 0.9
        my = max(0.0, (self._bg_pm.height() - self.height()) / 2.0) * 0.8
        dx = math.sin(self._t * 0.11) * mx
        dy = math.cos(self._t * 0.07) * my
        p.drawPixmap(int(-mx - dx), int(-my - dy), self._bg_pm)

        p.setOpacity(0.86 + 0.14 * math.sin(self._t * 1.1))
        p.drawPixmap(0, 0, self._glow_pm)
        p.setOpacity(1.0)

        p.drawPixmap(0, 0, self._overlay_pm)
        self._paint_fire(p)
        self._paint_panel(p)
        self._paint_sweep(p)
        self._paint_top_line(p)

        p.setClipping(False)
        p.setPen(QColor(255, 255, 255, 26))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        p.end()

    def _paint_sweep(self, p):
        w, h = self.width(), self.height()
        cycle = (self._t % 9.0) / 9.0
        x = -0.4 * w + cycle * 2.2 * w
        band = QLinearGradient(x, 0, x + 280, h * 0.4)
        band.setColorAt(0.0, QColor(61, 139, 255, 0))
        band.setColorAt(0.5, QColor(61, 139, 255, 20))
        band.setColorAt(1.0, QColor(61, 139, 255, 0))
        p.fillRect(self.rect(), band)

    def _paint_fire(self, p):
        w, h = self.width(), self.height()
        t = self._t
        beat = 0.82 + 0.18 * math.sin(t * 1.9)
        p.setPen(Qt.NoPen)
        p.setCompositionMode(QPainter.CompositionMode_Plus)

        wash = QLinearGradient(0, h - 175, 0, h)
        wash.setColorAt(0.0, QColor(255, 108, 28, 0))
        wash.setColorAt(0.5, QColor(255, 96, 20, int(10 * beat)))
        wash.setColorAt(1.0, QColor(255, 124, 30, int(54 * beat)))
        p.fillRect(QRectF(0, h - 175, w, 175), wash)

        hot = QRadialGradient(w * 0.72, h + 5, 240)
        hot.setColorAt(0.0, QColor(255, 120, 34, int(30 * beat)))
        hot.setColorAt(1.0, QColor(255, 80, 12, 0))
        p.fillRect(QRectF(0, h - 175, w, 175), hot)

        bed = QLinearGradient(0, h - 150, 0, h)
        bed.setColorAt(0.0, QColor(255, 70, 0, 0))
        bed.setColorAt(0.62, QColor(255, 78, 6, int(16 * beat)))
        bed.setColorAt(1.0, QColor(255, 118, 26, int(58 * beat)))
        p.fillRect(QRectF(0, h - 150, w, 150), bed)

        if self._fire_pm is not None:
            flick = 0.5 + 0.5 * math.sin(t * 2.1)
            ph = self._fire_pm.height() * (1.0 + 0.02 * flick)
            p.setOpacity(0.9 + 0.1 * flick)
            p.drawPixmap(QRectF(self._fire_x, h - ph + 12.0,
                                float(self._fire_pm.width()), ph),
                         self._fire_pm, QRectF(self._fire_pm.rect()))
            p.setOpacity(1.0)

        for s in self._sparks:
            life = max(0.0, s["life"])
            p.setBrush(QColor(255, 96, 18, int(52 * life)))
            p.drawEllipse(QRectF(s["x"] - s["r"] * 1.4, s["y"] - s["r"] * 2.8,
                                 s["r"] * 2.8, s["r"] * 5.6))
            p.setBrush(QColor(255, 186, 92, int(180 * life)))
            p.drawEllipse(QRectF(s["x"] - s["r"] * 0.8, s["y"] - s["r"] * 0.8,
                                 s["r"] * 1.6, s["r"] * 1.6))

        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def _paint_top_line(self, p):
        span = self.width() * 0.55
        base = QLinearGradient(0, 0, span, 0)
        base.setColorAt(0.0, QColor(255, 46, 77, 235))
        base.setColorAt(1.0, QColor(255, 46, 77, 0))
        p.fillRect(QRectF(0, 0, span, 2), base)
        cycle = (self._t % 6.0) / 6.0
        x = -170 + cycle * (span + 340)
        bright = QLinearGradient(x, 0, x + 170, 0)
        bright.setColorAt(0.0, QColor(220, 236, 255, 0))
        bright.setColorAt(0.5, QColor(255, 238, 241, 225))
        bright.setColorAt(1.0, QColor(220, 236, 255, 0))
        p.fillRect(QRectF(0, 0, span, 2), bright)

    def _paint_panel(self, p):
        h = self.height()
        poly = QPolygonF([QPointF(0, 0), QPointF(600, 0),
                          QPointF(520, h), QPointF(0, h)])
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(6, 8, 11, 238))
        grad.setColorAt(0.55, QColor(6, 8, 11, 226))
        grad.setColorAt(1.0, QColor(6, 8, 11, 242))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPolygon(poly)

        p.setPen(QPen(QColor(255, 46, 77, 40), 9))
        p.drawLine(QPointF(600, 0), QPointF(520, h))
        p.setPen(QPen(QColor(255, 46, 77, 210), 2))
        p.drawLine(QPointF(600, 0), QPointF(520, h))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(QPointF(588, 0), QPointF(508, h))

        p.setPen(QPen(QColor(61, 139, 255, 90), 2))
        for off in (18, 32, 46):
            p.drawLine(QPointF(600 - off, 0), QPointF(520 - off, h))

        band = QRectF(44, 602, 452, 7)
        p.save()
        p.setClipRect(band)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 46, 77, 26))
        p.drawRect(band)
        x = band.left() - 14
        stripe = 0
        while x < band.right() + 14:
            p.setBrush(QColor(61, 139, 255, 120) if stripe % 2 else QColor(255, 46, 77, 150))
            p.drawPolygon(QPolygonF([QPointF(x, band.bottom()), QPointF(x + 7, band.bottom()),
                                     QPointF(x + 14, band.top()), QPointF(x + 7, band.top())]))
            x += 22
            stripe += 1
        p.restore()

        self._paint_divider(p, 112)
        self._paint_divider(p, 496)

    def _paint_divider(self, p, y):
        p.setPen(QColor(255, 255, 255, 28))
        p.drawLine(QPointF(44, y), QPointF(496, y))
        p.setPen(QColor(255, 255, 255, 40))
        x, i = 44, 0
        while x <= 496:
            p.drawLine(QPointF(x, y), QPointF(x, y + (7 if i % 3 == 0 else 4)))
            x += 22
            i += 1
        p.setPen(QPen(QColor(61, 139, 255, 200), 2))
        p.drawLine(QPointF(490, y + 2), QPointF(502, y - 8))

    # ---- ui -------------------------------------------------------------
    def _build_ui(self):
        self.icon_badge = IconBadge(ASSET_DIR / "icon.png", 60)
        self.icon_badge.setParent(self)
        self.icon_badge.move(44, 26)

        title = QLabel("ARAB SCUM <span style='color:#FF2E4D'>DARK</span>", self)
        title.setTextFormat(Qt.RichText)
        title.setFont(display_font(31, 1.2))
        title.setStyleSheet("color:#E9E5DD;background:transparent;")
        title.setGeometry(120, 18, 440, 48)
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        sub = QLabel("SURVIVAL  //  ABO ADAM SERVER", self)
        sub.setFont(label_font(7.6, 2.6))
        sub.setStyleSheet("color:#8B9199;background:transparent;")
        sub.setGeometry(122, 64, 420, 18)
        sub.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.min_btn = PanelButton("\u2212", "chroma", font=QFont("Segoe UI", 10))
        self.min_btn.setParent(self)
        self.min_btn.setGeometry(1008, 24, 32, 32)
        self.min_btn.clicked.connect(self.showMinimized)

        self.close_btn = PanelButton("\u2715", "chroma", font=QFont("Segoe UI", 10), danger=True)
        self.close_btn.setParent(self)
        self.close_btn.setGeometry(1046, 24, 32, 32)
        self.close_btn.clicked.connect(self.close)

        self._section("01", "TARGET SERVER", 126)

        self.server_card = ServerCard("PVP\\PVE", SERVER_CONNECT or "not configured", "MAIN")
        self.server_card.setParent(self)
        self.server_card.move(44, 148)

        self._section("02", "OPERATIONS", 262)

        self.launch_btn = PanelButton("LAUNCH GAME", "primary", font=display_font(18, 2.4))
        self.launch_btn.setParent(self)
        self.launch_btn.setGeometry(44, 282, 452, 62)
        self.launch_btn.clicked.connect(self.launch_game)

        self.upd_btn = PanelButton("UPDATE LAUNCHER", "ghost", font=label_font(7.8, 1.2))
        self.upd_btn.setParent(self)
        self.upd_btn.setGeometry(44, 356, 142, 44)
        self.upd_btn.setToolTip("Check GitHub for a newer launcher build and install it")
        self.upd_btn.clicked.connect(self.update_launcher)

        self.mods_btn = PanelButton("DOWNLOAD MODS", "ghost", font=label_font(7.8, 1.2))
        self.mods_btn.setParent(self)
        self.mods_btn.setGeometry(198, 356, 142, 44)
        self.mods_btn.clicked.connect(self.sync_mods)

        self.delete_btn = PanelButton("DELETE MODS", "ghost", font=label_font(7.8, 1.2), danger=True)
        self.delete_btn.setParent(self)
        self.delete_btn.setGeometry(352, 356, 142, 44)
        self.delete_btn.clicked.connect(self.delete_mods)

        self.status_dot = Dot("#6BE08A", 10)
        self.status_dot.setParent(self)
        self.status_dot.move(46, 415)

        self.status_lbl = QLabel("Ready to launch", self)
        self.status_lbl.setFont(label_font(9.2, 0.8))
        self.status_lbl.setStyleSheet("color:#C6CBD2;background:transparent;")
        self.status_lbl.setGeometry(66, 406, 430, 24)
        self.status_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self.progress = PulseProgress()
        self.progress.setParent(self)
        self.progress.setGeometry(44, 440, 452, 4)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.hide()

        self.keep_toggle = Toggle(self.cfg.getboolean("settings", "keep_mods", fallback=True))
        self.keep_toggle.setParent(self)
        self.keep_toggle.move(44, 458)
        self.keep_toggle.toggled.connect(self._keep_changed)

        keep_lbl = QLabel("KEEP MODS INSTALLED", self)
        keep_lbl.setFont(label_font(8.2, 2.0))
        keep_lbl.setStyleSheet("color:#8B9199;background:transparent;")
        keep_lbl.setGeometry(102, 456, 240, 24)
        keep_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        hint = QLabel("// AUTO CLEANUP", self)
        hint.setFont(mono_font(7.4, 1.0))
        hint.setStyleSheet("color:#5D636B;background:transparent;")
        hint.setGeometry(300, 456, 196, 24)
        hint.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

        self._section("03", "INSTALL PATH", 506)

        self.folder_edit = QLineEdit(self)
        self.folder_edit.setGeometry(44, 526, 336, 40)
        self.folder_edit.setFont(mono_font(8.2, 0.4))
        self.folder_edit.setPlaceholderText("not found - type a path or click BROWSE")
        self.folder_edit.setToolTip("Paste or type the SCUM folder path, then press Enter")
        self._folder_style(False)
        self.folder_edit.textEdited.connect(lambda _: self._folder_style(False))
        self.folder_edit.editingFinished.connect(self._apply_typed_folder)

        self.browse_btn = PanelButton("BROWSE", "fill", font=label_font(8.4, 2.2))
        self.browse_btn.setParent(self)
        self.browse_btn.setGeometry(388, 526, 108, 40)
        self.browse_btn.clicked.connect(self.choose_folder)

        version = QLabel(f"v{APP_VERSION}", self)
        version.setFont(mono_font(7.8, 0.8))
        version.setStyleSheet("color:#5D636B;background:transparent;")
        version.setGeometry(44, 576, 80, 18)

        self.youtube_btn = PanelButton("YOUTUBE", "youtube", font=label_font(7.8, 2.2))
        self.youtube_btn.setParent(self)
        self.youtube_btn.setGeometry(352, 568, 144, 30)
        self.youtube_btn.setToolTip("Open AboAdamH on YouTube")
        self.youtube_btn.clicked.connect(self.open_youtube)

        self.credit = CreditPlate()
        self.credit.setParent(self)
        self.credit.move(44, 613)

    def open_youtube(self):
        QDesktopServices.openUrl(QUrl(YOUTUBE_URL))

    def _section(self, number, text, y):
        num = QLabel(number, self)
        num.setFont(mono_font(9, 1.2, QFont.Bold))
        num.setStyleSheet("color:#3D8BFF;background:transparent;")
        num.setGeometry(44, y, 28, 18)
        num.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lbl = QLabel(text, self)
        lbl.setFont(label_font(8.0, 2.4))
        lbl.setStyleSheet("color:#8B9199;background:transparent;")
        lbl.setGeometry(76, y, 340, 18)
        lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def showEvent(self, event):
        self._last = time.perf_counter()
        if not self._timer.isActive():
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    # ---- window interactions -------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def _refresh_folder(self):
        self.folder_edit.setText(str(self.paks) if self.paks else "")
        self.folder_edit.setCursorPosition(0)
        self.folder_edit.setToolTip(str(self.paks) if self.paks else "No SCUM install detected")
        self._folder_style(False)

    def _folder_style(self, error):
        border = "rgba(255,46,77,0.90)" if error else "rgba(255,255,255,0.16)"
        self.folder_edit.setStyleSheet(
            "QLineEdit{background:rgba(255,255,255,0.045);color:#C6CBD2;"
            f"border:1px solid {border};border-left:2px solid #FF2E4D;padding:0 10px;}}"
            "QLineEdit:focus{border-color:rgba(255,46,77,0.85);color:#FFFFFF;}")

    def _set_folder(self, candidate):
        self.paks = candidate
        self.cfg["paths"]["paks_dir"] = str(candidate)
        save_config(self.cfg)
        self._refresh_folder()
        self._set_status("SCUM folder saved")

    def _apply_typed_folder(self):
        text = self.folder_edit.text().strip().strip('"')
        if not text or (self.paks and Path(text) == self.paks):
            return
        candidate = resolve_paks(text)
        if not candidate:
            self._folder_style(True)
            self._set_status("That path has no SCUM game (needs Binaries\\Win64\\SCUM.exe)", True)
            return
        self._set_folder(candidate)

    def choose_folder(self):
        from PyQt5.QtWidgets import QFileDialog
        start = str(self.paks.parent.parent) if self.paks else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select SCUM game folder", start)
        if not chosen:
            return
        candidate = resolve_paks(chosen)
        if not candidate:
            box = QMessageBox(self)
            box.setWindowTitle("SCUM not found")
            box.setText(f"No SCUM installation in:\n{chosen}")
            box.setInformativeText("Pick the folder that contains Binaries\\Win64\\SCUM.exe, "
                                   "or select SCUM.exe directly.")
            pick = box.addButton("Select SCUM.exe...", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec_()
            if box.clickedButton() is pick:
                exe, _ = QFileDialog.getOpenFileName(
                    self, "Select SCUM.exe", chosen, "SCUM executable (SCUM.exe)")
                candidate = resolve_paks(exe) if exe else None
        if not candidate:
            self._folder_style(True)
            self._set_status("Folder unchanged - no SCUM game there", True)
            return
        self._set_folder(candidate)

    # ---- actions --------------------------------------------------------
    def _set_status(self, text, error=False):
        self.status_lbl.setText(text)
        self.status_dot.set_color("#FF2E4D" if error else "#6BE08A")

    def _keep_changed(self, on):
        self.cfg["settings"]["keep_mods"] = "true" if on else "false"
        save_config(self.cfg)

    def _busy_state(self, busy, label=None):
        self._busy = busy
        self.launch_btn.setEnabled(not busy)
        self.upd_btn.setEnabled(not busy)
        self.mods_btn.setEnabled(not busy)
        self.delete_btn.setEnabled(not busy)
        if label:
            self.launch_btn.setText(label)

    def launch_game(self):
        if self._busy:
            return
        if not self.paks or not valid_paks(self.paks):
            self._set_status("SCUM folder not found. Click the folder row below.", True)
            return
        if not SERVER_CONNECT:
            self._set_status("Server address is not configured yet.", True)
            return
        scum = self.paks.parent.parent / "Binaries" / "Win64" / "SCUM.exe"
        args = [str(scum), "-fileopenlog", "-nobattleye", "-connect", SERVER_CONNECT]
        env = inst_env({"SteamAppId": SCUM_APP_ID, "SteamGameId": SCUM_APP_ID})
        try:
            proc = subprocess.Popen(
                args, cwd=str(scum.parent), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as exc:
            self._set_status(f"Launch failed: {exc}", True)
            return
        self._game_proc = proc
        self._busy_state(True, "GAME RUNNING")
        if self.keep_toggle.isChecked():
            self._set_status("Game started. Launcher will close when you quit SCUM.")
        else:
            self._set_status("Game started. Mods will be removed when you quit SCUM.")
        self.hide()
        self._timer.stop()
        QTimer.singleShot(1000, self._watch_game)

    def _watch_game(self):
        # Stay alive (hidden) while SCUM runs: exiting now would leave the game
        # holding DLLs from our onefile temp dir, so its cleanup would fail.
        if self._game_proc.poll() is None:
            QTimer.singleShot(1000, self._watch_game)
            return
        if not self.keep_toggle.isChecked():
            removed = self._delete_managed_files()
            log_line(f"removed {removed} mod files after game exit")
        self._timer.stop()
        QTimer.singleShot(2500, QApplication.instance().quit)

    def _manifest_path(self):
        for name in ("mod_manifest.json", "launcher_mod_manifest.json"):
            p = BASE_DIR / name
            if p.exists():
                return p
        return None

    def _load_manifest(self):
        path = self._manifest_path()
        if path:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                self._set_status(f"Bad manifest: {exc}", True)
                return None
        url = self.cfg.get("mods", "manifest_url", fallback="") or MANIFEST_URL
        if not url:
            self._set_status("No mod_manifest.json nearby and no manifest URL set.", True)
            return None
        try:
            sep = "&" if "?" in url else "?"
            req = urllib.request.Request(f"{url}{sep}t={int(time.time())}",
                                         headers={"User-Agent": "ArabScumDark"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            self._set_status(f"Manifest download failed: {exc}", True)
            return None

    def sync_mods(self):
        if self._busy:
            return
        if not self.paks:
            self._set_status("SCUM folder not found. Choose it first.", True)
            return
        manifest = self._load_manifest()
        if manifest is None:
            return
        try:
            items = manifest["items"]
        except Exception as exc:
            self._set_status(f"Bad manifest: {exc}", True)
            return
        self._busy_state(True, "PLEASE WAIT")
        self.progress.show()
        self.progress.setValue(0)
        self._set_status("Downloading mods...")
        threading.Thread(target=self._sync_worker, args=(manifest, items), daemon=True).start()

    def _sync_worker(self, manifest, items):
        mods_dir = self.paks / "~mods"
        base_url = manifest.get("base_url", "").rstrip("/")
        done, total = 0, len(items)
        installed = []
        try:
            mods_dir.mkdir(parents=True, exist_ok=True)
            for item in items:
                rel = Path(item["path"])
                dest = (mods_dir / rel).resolve()
                if mods_dir.resolve() not in dest.parents:
                    raise RuntimeError(f"Unsafe path in manifest: {rel}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                expected = str(item.get("sha", "")).lower()
                if dest.exists() and dest.stat().st_size == item.get("size", -1) \
                        and sha256_file(dest) == expected:
                    installed.append(str(dest))
                    done += 1
                    self._progress(done, total)
                    continue
                if not base_url:
                    raise RuntimeError("Manifest has no base_url")
                tmp = dest.with_name(dest.name + ".download")
                url = f"{base_url}/{rel.as_posix()}"
                req = urllib.request.Request(url, headers={"User-Agent": "ArabScumDark"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                if sha256_file(tmp) != expected:
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(f"Hash mismatch: {rel}")
                os.replace(tmp, dest)
                installed.append(str(dest))
                done += 1
                self._progress(done, total)
            self.cfg["mods"]["files"] = json.dumps(installed)
            save_config(self.cfg)
            self._done(f"Mods ready ({done}/{total})", False)
        except Exception as exc:
            self._done(f"Download failed: {exc}", True)

    def _progress(self, done, total):
        self.progress_signal.emit(done, total)

    def _apply_progress(self, done, total):
        if not self._busy:
            return
        self.progress.setValue(int(done * 100 / max(1, total)))
        self._set_status(f"Downloading mods... {done}/{total}")

    def _done(self, text, error):
        self.done_signal.emit(text, error)

    def _apply_done(self, text, error):
        self._busy_state(False, "LAUNCH GAME")
        self.progress.hide()
        self._set_status(text, error)

    # ---- launcher self-update -------------------------------------------
    def check_launcher_update(self, auto=False):
        if self._busy or self._upd_checking:
            return
        if not getattr(sys, "frozen", False):
            return
        self._upd_checking = True
        self.upd_btn.setText("CHECKING...")
        threading.Thread(target=self._launcher_check_worker, args=(auto,), daemon=True).start()

    def _launcher_check_worker(self, auto):
        try:
            sep = "&" if "?" in LAUNCHER_UPDATE_URL else "?"
            req = urllib.request.Request(
                f"{LAUNCHER_UPDATE_URL}{sep}t={int(time.time())}",
                headers={"User-Agent": f"ArabScumDark/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            self.launcher_check_signal.emit("error", (auto, f"check failed: {exc}"))
            return
        if version_tuple(data.get("version", "")) > version_tuple(APP_VERSION):
            self.launcher_check_signal.emit("available", (auto, data))
        else:
            self.launcher_check_signal.emit("current", (auto, data))

    def _apply_launcher_state(self, state, payload):
        if state == "restart":
            self._set_status("Launcher updated - restarting...")
            QTimer.singleShot(300, QApplication.instance().quit)
            return
        self._upd_checking = False
        auto, data = payload
        if state == "available":
            self._launcher_update = data
            self.upd_btn.setText(f"UPDATE TO v{data.get('version', '?')}")
            self.upd_btn.setToolTip(f"Install launcher v{data.get('version', '?')}")
            self._set_status(f"Launcher update available: v{data.get('version', '?')}")
        elif state == "current":
            self._launcher_update = None
            self.upd_btn.setText("UPDATE LAUNCHER")
            self.upd_btn.setToolTip("Launcher is up to date")
            if not auto:
                self._set_status("Launcher is up to date")
        else:
            self._launcher_update = None
            self.upd_btn.setText("UPDATE LAUNCHER")
            if self._busy:
                self._busy_state(False, "LAUNCH GAME")
                self.progress.hide()
            self._set_status(f"Launcher update {data}", True)
        if not self._busy:
            self.upd_btn.setEnabled(True)

    def update_launcher(self):
        if self._busy or self._upd_checking:
            return
        if not getattr(sys, "frozen", False):
            self._set_status("Self-update works only in the packaged launcher", True)
            return
        data = self._launcher_update
        if not data:
            self.check_launcher_update()
            return
        ver = data.get("version", "?")
        size = int(data.get("size", 0) or 0)
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(f"Update launcher to v{ver}?")
        box.setInformativeText(
            f"Download {size / 1048576:.1f} MB, replace this launcher and restart it.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        if box.exec_() != QMessageBox.Yes:
            return
        self._busy_state(True, "UPDATING...")
        self.progress.show()
        self.progress.setValue(0)
        self._set_status(f"Downloading launcher v{ver}...")
        threading.Thread(target=self._launcher_dl_worker, args=(data,), daemon=True).start()

    def _launcher_dl_worker(self, data):
        exe = Path(sys.executable)
        tmp = exe.with_name(exe.name + ".new")
        old = exe.with_name(exe.name + ".old")
        try:
            tmp.unlink(missing_ok=True)
            req = urllib.request.Request(
                data["url"], headers={"User-Agent": f"ArabScumDark/{APP_VERSION}"})
            digest = hashlib.sha256()
            got = 0
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length") or data.get("size") or 0)
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    digest.update(chunk)
                    got += len(chunk)
                    self.launcher_dl_signal.emit(got, total)
            expected = str(data.get("sha256", "")).lower()
            if expected and digest.hexdigest() != expected:
                raise RuntimeError("hash mismatch")
            if old.exists():
                old.unlink()
            os.replace(exe, old)
            try:
                os.replace(tmp, exe)
            except Exception:
                os.replace(old, exe)
                raise
            subprocess.Popen([str(exe)], env=inst_env())
            self.launcher_check_signal.emit("restart", None)
        except Exception as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            self.launcher_check_signal.emit("error", (False, f"failed: {exc}"))

    def _apply_launcher_download(self, got, total):
        if total > 0:
            self.progress.setValue(int(got * 100 / total))
            self._set_status(
                f"Downloading launcher... {got / 1048576:.1f}/{total / 1048576:.1f} MB")
        else:
            self._set_status(f"Downloading launcher... {got / 1048576:.1f} MB")

    def _managed_files(self):
        try:
            return [Path(p) for p in json.loads(self.cfg.get("mods", "files", fallback="[]"))]
        except Exception:
            return []

    def _delete_managed_files(self):
        removed = 0
        for p in self._managed_files():
            try:
                if p.exists() and p.is_file():
                    p.unlink()
                    removed += 1
            except OSError:
                pass
        self.cfg["mods"]["files"] = "[]"
        save_config(self.cfg)
        return removed

    def delete_mods(self):
        if self._busy:
            return
        files = self._managed_files()
        if not files:
            self._set_status("No launcher-managed mods installed.")
            return
        removed = self._delete_managed_files()
        self._set_status(f"Mods deleted ({removed} files)")


def main():
    sys.excepthook = log_hook
    threading.excepthook = _thread_hook
    cleanup_old_exe()
    try:
        import faulthandler
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        _fh = open(LOG_FILE, "ab", buffering=0)
        faulthandler.enable(_fh)
    except Exception:
        pass
    log_line(f"launcher start v{APP_VERSION} exe={sys.executable} frozen={getattr(sys, 'frozen', False)}")
    try:
        return _run()
    except Exception:
        show_error("Launcher crashed:\n" + traceback.format_exc())
        return 1


def _run():
    preview_out = None
    if "--preview" in sys.argv:
        idx = sys.argv.index("--preview")
        if len(sys.argv) > idx + 1:
            preview_out = sys.argv[idx + 1]
    preview_at = None
    if "--at" in sys.argv:
        idx = sys.argv.index("--at")
        if len(sys.argv) > idx + 1:
            try:
                preview_at = float(sys.argv[idx + 1])
            except ValueError:
                preview_at = None

    app = QApplication(sys.argv)
    log_line("QApplication created")
    try:
        from PyQt5.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_message_handler)
    except Exception:
        pass
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    win = LauncherWindow()
    log_line("window constructed")

    if preview_out:
        if preview_at is not None:
            win._t = preview_at
        win.move(-4000, -4000)
        win.show()
        app.processEvents()
        win.grab().save(preview_out, "PNG")
        print(f"preview saved: {preview_out}")
        win.close()
        return 0

    win.setWindowOpacity(0.0)
    win.show()
    fade = QPropertyAnimation(win, b"windowOpacity", win)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setDuration(420)
    fade.setEasingCurve(QEasingCurve.OutCubic)
    fade.start()
    if "--launch" in sys.argv:
        QTimer.singleShot(200, win.launch_game)
    log_line("entering exec loop")
    rc = app.exec_()
    log_line(f"exec loop finished rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())

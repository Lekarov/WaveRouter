"""
Extraction de l'icône associée à un exécutable Windows (.exe), pour
l'afficher dans la liste des jeux de l'interface.

Implémenté en ctypes pur (API Shell32/GDI32) pour ne pas ajouter de
dépendance supplémentaire (pas de pywin32).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache

from PIL import Image

_shell32 = ctypes.windll.shell32
_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

_BI_RGB = 0
_DIB_RGB_COLORS = 0

# Déclarations explicites des signatures : sans elles, ctypes déduit des
# types par défaut (souvent c_int) qui débordent sur les handles 64 bits
# et lèvent une OverflowError au moindre appel.
_shell32.ExtractIconExW.argtypes = [
    wintypes.LPCWSTR,
    ctypes.c_int,
    ctypes.POINTER(wintypes.HICON),
    ctypes.POINTER(wintypes.HICON),
    wintypes.UINT,
]
_shell32.ExtractIconExW.restype = wintypes.UINT

_user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.c_void_p]
_user32.GetIconInfo.restype = wintypes.BOOL

_user32.DestroyIcon.argtypes = [wintypes.HICON]
_user32.DestroyIcon.restype = wintypes.BOOL

_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC

_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.ReleaseDC.restype = ctypes.c_int

_gdi32.GetObjectW.argtypes = [wintypes.HBITMAP, ctypes.c_int, ctypes.c_void_p]
_gdi32.GetObjectW.restype = ctypes.c_int

_gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
]
_gdi32.GetDIBits.restype = ctypes.c_int

_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteObject.restype = wintypes.BOOL


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", wintypes.LPVOID),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _extract_icon_uncached(exe_path: str, size: int) -> Image.Image | None:
    large = (wintypes.HICON * 1)()
    small = (wintypes.HICON * 1)()
    extracted = _shell32.ExtractIconExW(exe_path, 0, large, small, 1)
    if extracted == 0:
        return None

    hicon = large[0] or small[0]
    if not hicon:
        return None

    other_hicon = small[0] if large[0] else 0
    try:
        icon_info = _ICONINFO()
        if not _user32.GetIconInfo(hicon, ctypes.byref(icon_info)):
            return None

        try:
            bitmap = _BITMAP()
            _gdi32.GetObjectW(icon_info.hbmColor, ctypes.sizeof(_BITMAP), ctypes.byref(bitmap))
            width, height = bitmap.bmWidth, bitmap.bmHeight
            if width <= 0 or height <= 0:
                return None

            hdc = _user32.GetDC(None)
            try:
                bmi = _BITMAPINFO()
                bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
                bmi.bmiHeader.biWidth = width
                bmi.bmiHeader.biHeight = -height  # top-down, plus simple à relire
                bmi.bmiHeader.biPlanes = 1
                bmi.bmiHeader.biBitCount = 32
                bmi.bmiHeader.biCompression = _BI_RGB

                buffer = ctypes.create_string_buffer(width * height * 4)
                scanlines = _gdi32.GetDIBits(
                    hdc,
                    icon_info.hbmColor,
                    0,
                    height,
                    buffer,
                    ctypes.byref(bmi),
                    _DIB_RGB_COLORS,
                )
                if scanlines == 0:
                    return None
            finally:
                _user32.ReleaseDC(None, hdc)

            image = Image.frombuffer("RGBA", (width, height), buffer.raw, "raw", "BGRA", 0, 1)
            return image.resize((size, size), Image.LANCZOS)
        finally:
            if icon_info.hbmColor:
                _gdi32.DeleteObject(icon_info.hbmColor)
            if icon_info.hbmMask:
                _gdi32.DeleteObject(icon_info.hbmMask)
    finally:
        _user32.DestroyIcon(hicon)
        if other_hicon:
            _user32.DestroyIcon(other_hicon)


@lru_cache(maxsize=128)
def extract_icon_image(exe_path: str, size: int = 32) -> Image.Image | None:
    """
    Retourne l'icône du fichier `exe_path` sous forme d'image PIL RGBA
    carrée de `size`x`size` pixels, ou None si l'extraction échoue (fichier
    introuvable, pas d'icône, erreur GDI...). Résultat mis en cache par
    chemin (l'icône d'un exécutable ne change pas en cours de session).
    """
    try:
        return _extract_icon_uncached(exe_path, size)
    except OSError:
        return None

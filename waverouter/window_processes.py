"""
Détection des applications actuellement ouvertes (fenêtres visibles), pour
permettre un ajout "rapide" d'un jeu sans avoir à parcourir manuellement
son chemin d'exécutable.

Utilise uniquement l'API Windows (via ctypes) et psutil, déjà nécessaires
au reste de l'application : aucune dépendance supplémentaire.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import psutil

user32 = ctypes.windll.user32

# Fenêtres système/shell à ignorer, car ce ne sont jamais des jeux à router.
_IGNORED_PROCESS_NAMES = {
    "explorer.exe",
    "searchhost.exe",
    "shellexperiencehost.exe",
    "applicationframehost.exe",
    "textinputhost.exe",
    "systemsettings.exe",
    "python.exe",
    "pythonw.exe",
    "waverouter.exe",
}


@dataclass
class DetectedWindow:
    title: str
    process_name: str
    exe_path: str


def list_visible_app_processes() -> list[DetectedWindow]:
    """
    Retourne la liste des applications ayant actuellement une fenêtre
    visible avec un titre, dédupliquée par processus.
    """
    results: list[DetectedWindow] = []
    seen_pids: set[int] = set()

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in seen_pids:
            return True
        seen_pids.add(pid.value)

        try:
            proc = psutil.Process(pid.value)
            process_name = proc.name()
            exe_path = proc.exe()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return True

        if process_name.lower() in _IGNORED_PROCESS_NAMES:
            return True

        results.append(
            DetectedWindow(title=title, process_name=process_name, exe_path=exe_path)
        )
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    results.sort(key=lambda w: w.title.lower())
    return results


def find_running_exe_path(process_name: str) -> str | None:
    """
    Cherche parmi les processus actuellement actifs celui dont le nom
    correspond à `process_name` et retourne son chemin complet. Sert de
    secours pour afficher l'icône d'un jeu dont le chemin n'a pas été
    enregistré, tant qu'il est en cours d'exécution.
    """
    target = process_name.strip().lower()
    if not target:
        return None
    for proc in psutil.process_iter(attrs=["name"]):
        name = (proc.info.get("name") or "").strip().lower()
        if name == target:
            try:
                return proc.exe()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                return None
    return None

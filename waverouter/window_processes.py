"""
Détection des applications actuellement ouvertes (fenêtres visibles), pour
permettre un ajout "rapide" d'un jeu sans avoir à parcourir manuellement
son chemin d'exécutable, et heuristiques servant à reconnaître un jeu.

Utilise uniquement l'API Windows (via ctypes) et psutil, déjà nécessaires
au reste de l'application : aucune dépendance supplémentaire.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import psutil

user32 = ctypes.windll.user32

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

_SM_CXSCREEN = 0
_SM_CYSCREEN = 1

# Une fenêtre couvrant au moins cette fraction de l'écran principal est
# considérée comme plein écran. Le seuil reste permissif : les jeux en
# "plein écran fenêtré" laissent parfois passer la barre des tâches.
_FULLSCREEN_RATIO = 0.85

# Fenêtres système/shell à ignorer, car ce ne sont jamais des jeux à router.
_IGNORED_PROCESS_NAMES = {
    "explorer.exe",
    "searchhost.exe",
    "shellexperiencehost.exe",
    "applicationframehost.exe",
    "textinputhost.exe",
    "systemsettings.exe",
    "startmenuexperiencehost.exe",
    "lockapp.exe",
    "python.exe",
    "pythonw.exe",
    "waverouter.exe",
}

# Applications courantes qui produisent du son et peuvent occuper tout
# l'écran sans être des jeux : elles ne doivent jamais déclencher la
# proposition d'ajout automatique.
_NON_GAME_PROCESS_NAMES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "vivaldi.exe",
    "discord.exe",
    "spotify.exe",
    "vlc.exe",
    "mpc-hc64.exe",
    "obs64.exe",
    "obs32.exe",
    "streamlabs obs.exe",
    "wavelink.exe",
    "elgato wave link.exe",
    "steam.exe",
    "steamwebhelper.exe",
    "epicgameslauncher.exe",
    "galaxyclient.exe",
    "battle.net.exe",
    "riotclientux.exe",
    "ubisoftconnect.exe",
    "upc.exe",
    "eadesktop.exe",
    "teams.exe",
    "slack.exe",
    "zoom.exe",
    "code.exe",
    "devenv.exe",
    "vlc.exe",
    "foobar2000.exe",
    "itunes.exe",
    "audacity.exe",
    "reaper.exe",
}


@dataclass
class DetectedWindow:
    title: str
    process_name: str
    exe_path: str


def is_system_process(process_name: str) -> bool:
    """
    Indique si ce process ne doit jamais être proposé comme jeu (composant
    Windows, launcher, navigateur, outil de streaming...).
    """
    normalized = process_name.strip().lower()
    return normalized in _IGNORED_PROCESS_NAMES or normalized in _NON_GAME_PROCESS_NAMES


def _screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(_SM_CXSCREEN), user32.GetSystemMetrics(_SM_CYSCREEN)


def _window_pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _window_title(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.strip()


def _enum_windows(callback) -> None:
    """Parcourt les fenêtres de premier niveau ; `callback(hwnd)` renvoie False pour arrêter."""
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def wrapped(hwnd, _lparam) -> bool:
        return callback(hwnd)

    user32.EnumWindows(WNDENUMPROC(wrapped), 0)


def list_visible_app_processes() -> list[DetectedWindow]:
    """
    Retourne la liste des applications ayant actuellement une fenêtre
    visible avec un titre, dédupliquée par processus.
    """
    results: list[DetectedWindow] = []
    seen_pids: set[int] = set()

    def callback(hwnd) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title:
            return True

        pid = _window_pid(hwnd)
        if pid in seen_pids:
            return True
        seen_pids.add(pid)

        try:
            proc = psutil.Process(pid)
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

    _enum_windows(callback)
    results.sort(key=lambda w: w.title.lower())
    return results


def find_fullscreen_window_title(pid: int) -> str | None:
    """
    Retourne le titre de la fenêtre plein écran appartenant à ce PID, ou
    None s'il n'en a aucune.

    Sert d'indice décisif pour la détection automatique : couplée à la
    présence d'une session audio, une fenêtre occupant tout l'écran
    distingue un jeu d'un navigateur ou d'un lecteur multimédia en fenêtre.
    """
    screen_w, screen_h = _screen_size()
    if screen_w <= 0 or screen_h <= 0:
        return None
    min_w = screen_w * _FULLSCREEN_RATIO
    min_h = screen_h * _FULLSCREEN_RATIO

    found: list[str] = []

    def callback(hwnd) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if _window_pid(hwnd) != pid:
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        if (rect.right - rect.left) < min_w or (rect.bottom - rect.top) < min_h:
            return True
        found.append(_window_title(hwnd) or "")
        return False  # inutile de continuer, une fenêtre suffit

    _enum_windows(callback)
    if not found:
        return None
    return found[0] or f"PID {pid}"


def map_running_exe_paths(process_names: set[str]) -> dict[str, str]:
    """
    Retourne, pour les noms de process demandés, le chemin de l'exécutable
    correspondant parmi les processus actuellement actifs.

    Un seul balayage couvre toute la liste : appelée une fois par
    rafraîchissement de l'interface, cette fonction remplace autant de
    balayages complets qu'il y avait de jeux sans chemin enregistré.
    """
    targets = {name.strip().lower() for name in process_names if name.strip()}
    if not targets:
        return {}

    found: dict[str, str] = {}
    for proc in psutil.process_iter(attrs=["name", "exe"]):
        name = (proc.info.get("name") or "").strip().lower()
        if name not in targets or name in found:
            continue
        exe = proc.info.get("exe") or ""
        if exe:
            found[name] = exe
            if len(found) == len(targets):
                break
    return found

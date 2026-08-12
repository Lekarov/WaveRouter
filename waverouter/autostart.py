"""
Gestion du démarrage automatique de WaveRouter avec Windows, via la clé de
registre HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
"""

from __future__ import annotations

import sys
import winreg

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "WaveRouter"


def _get_executable_command() -> str:
    """
    Retourne la commande à enregistrer dans le registre.

    En .exe packagé (PyInstaller), sys.executable pointe vers WaveRouter.exe
    lui-même. En exécution depuis les sources, on relance python avec le
    script principal.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{sys.argv[0]}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool) -> None:
    """Active ou désactive le lancement automatique au démarrage de Windows."""
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key, _VALUE_NAME, 0, winreg.REG_SZ, _get_executable_command()
            )
        else:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass  # Déjà désactivé, rien à faire

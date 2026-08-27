"""
Gestion du démarrage automatique de WaveRouter avec Windows, via la clé de
registre HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
"""

from __future__ import annotations

import os
import sys
import winreg

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "WaveRouter"


def _get_executable_command() -> str:
    """
    Retourne la commande à enregistrer dans le registre.

    En .exe packagé (PyInstaller), sys.executable pointe vers WaveRouter.exe
    lui-même. En exécution depuis les sources, on relance python avec le
    script principal. Le chemin du script est rendu absolu : le registre le
    lance depuis un répertoire courant arbitraire, un argv[0] relatif y
    serait introuvable.

    `--minimized` évite que la fenêtre s'ouvre à chaque ouverture de session
    Windows : l'application démarre directement dans la barre système.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    return f'"{sys.executable}" "{script}" --minimized'


def registered_command() -> str | None:
    """Commande actuellement enregistrée au démarrage, ou None s'il n'y en a pas."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError:
        # Clé inaccessible (stratégie de groupe, profil corrompu) : on
        # considère la fonctionnalité inactive plutôt que de planter l'UI.
        return None


def is_enabled() -> bool:
    """Indique si une entrée de démarrage automatique existe."""
    return registered_command() is not None


def is_stale() -> bool:
    """
    Indique si l'entrée enregistrée ne correspond plus à cette installation.

    Cas vécu : le dossier du projet a été renommé, et l'entrée continuait de
    désigner l'ancien emplacement. Le démarrage automatique ne fonctionnait
    donc plus, alors que l'application l'affichait comme actif puisque la clé
    existait toujours.
    """
    current = registered_command()
    return current is not None and current != _get_executable_command()


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

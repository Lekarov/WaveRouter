"""
Verrou d'instance unique.

WaveRouter est conçu pour démarrer avec Windows tout en restant lançable à
la main : sans garde-fou, deux instances tournent en parallèle, chacune avec
son moteur de surveillance et sa propre icône de barre système. Les deux
envoient alors des commandes SoundVolumeView concurrentes sur les mêmes
processus, ce qui produit des routages incohérents.

Le verrou repose sur un mutex nommé Windows : le premier processus le crée,
les suivants constatent qu'il existe déjà et s'arrêtent. Le mutex est
automatiquement libéré par Windows à la mort du processus, y compris en cas
de crash, donc aucun fichier de verrou fantôme à nettoyer.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

# Le préfixe "Local\" limite la portée à la session utilisateur courante :
# deux comptes Windows connectés simultanément gardent chacun leur instance.
MUTEX_NAME = r"Local\WaveRouter.SingleInstance"

_ERROR_ALREADY_EXISTS = 183

# use_last_error=True : ctypes capture le code d'erreur au retour de chaque
# appel et le range à part. Sans cela, GetLastError() lu depuis Python peut
# déjà avoir été écrasé par les appels internes de l'interpréteur.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstance:
    """Détient le mutex d'instance unique pendant toute la vie du processus."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._name = name
        self._handle: int | None = None
        self.already_running = False

    def acquire(self) -> bool:
        """
        Tente de prendre le verrou. Retourne True si cette instance est la
        seule, False si une autre est déjà en cours d'exécution.
        """
        handle = _kernel32.CreateMutexW(None, False, self._name)
        last_error = ctypes.get_last_error()
        if not handle:
            # Impossible de créer le mutex : on préfère laisser l'application
            # démarrer plutôt que de la bloquer sur un détail système.
            return True
        self._handle = handle
        self.already_running = last_error == _ERROR_ALREADY_EXISTS
        return not self.already_running

    def release(self) -> None:
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None


def show_already_running_message() -> None:
    """Signale à l'utilisateur que WaveRouter tourne déjà (boîte native)."""
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "WaveRouter est déjà en cours d'exécution.\n\n"
            "Retrouvez-le dans la barre système, près de l'horloge.",
            "WaveRouter",
            0x40,  # MB_ICONINFORMATION
        )
    except Exception:
        pass  # Message d'information seulement, jamais bloquant

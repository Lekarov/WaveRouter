"""
Détection des canaux de sortie audio disponibles pour le routage, à partir
de la liste de périphériques exposée par SoundVolumeView.

Constat important : les canaux virtuels créés par Elgato Wave Link ne
portent PAS de nom distinctif ("Wave Link", "Elgato", ...) au niveau
Windows. Ce sont simplement les noms donnés aux canaux dans l'application
Wave Link (ex: "Games!", "Music", "SFX", "System", "Voice chat", "Divers"),
et l'utilisateur peut les renommer librement. Il n'existe donc aucun
mot-clé fiable permettant de les distinguer automatiquement des autres
périphériques de sortie (haut-parleurs, casque, carte de capture...).

La stratégie retenue est donc d'afficher TOUS les périphériques de rendu
(playback) détectés, à l'exception du matériel physique identifiable avec
certitude (le retour micro "Wave:3 FX" d'Elgato, jamais un canal de
routage utile), et de laisser l'utilisateur choisir manuellement le bon
canal dans le menu déroulant.
"""

from __future__ import annotations

import re

from waverouter.audio_backend import AudioBackend, SoundVolumeViewError

# Matériel physique Elgato identifiable avec certitude, à exclure car ce
# n'est jamais un canal de routage Wave Link (retour micro Wave:1/Wave:3,
# sortie Wave XLR).
_HARDWARE_EXCLUDE_PATTERN = re.compile(r"wave\s*:\s*\d\s*fx|wave\s*xlr", re.IGNORECASE)


def detect_wavelink_channels(backend: AudioBackend) -> list[str]:
    """
    Retourne la liste des noms de périphériques de rendu (playback)
    disponibles pour le routage, matériel Elgato de monitoring exclu.

    Comme les canaux Wave Link ne sont pas identifiables par leur nom,
    cette liste correspond à tous les périphériques de sortie du système
    (haut-parleurs, casque, canaux Wave Link, etc.) : c'est à l'utilisateur
    de choisir le bon dans le menu déroulant.

    Lève SoundVolumeViewError si l'outil est introuvable ou en échec.
    """
    devices = backend.list_devices()
    channels: list[str] = []
    seen: set[str] = set()

    for device in devices:
        device_type = (device.get("Type") or "").strip().lower()
        direction = (device.get("Direction") or "").strip().lower()
        name = (device.get("Name") or "").strip()

        if device_type != "device" or direction != "render":
            continue
        if not name:
            continue
        if _HARDWARE_EXCLUDE_PATTERN.search(name.lower()):
            continue
        if name not in seen:
            seen.add(name)
            channels.append(name)

    channels.sort(key=str.lower)
    return channels


def try_detect_wavelink_channels(backend: AudioBackend) -> tuple[list[str], str | None]:
    """
    Variante tolérante aux erreurs : retourne (liste, message_erreur).
    Si la détection échoue, la liste est vide et le message décrit la cause.
    """
    try:
        return detect_wavelink_channels(backend), None
    except SoundVolumeViewError as exc:
        return [], str(exc)


def list_all_render_device_names(backend: AudioBackend) -> list[str]:
    """
    Retourne le nom de tous les périphériques de rendu (playback) connus
    du système, sans aucun filtrage. Utile pour le diagnostic.
    """
    devices = backend.list_devices()
    names: list[str] = []
    for device in devices:
        device_type = (device.get("Type") or "").strip().lower()
        direction = (device.get("Direction") or "").strip().lower()
        name = (device.get("Name") or "").strip()
        if device_type == "device" and direction == "render" and name:
            names.append(name)
    return names

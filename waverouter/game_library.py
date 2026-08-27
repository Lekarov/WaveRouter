"""
Découverte des jeux installés sur la machine (Steam, Epic Games, GOG).

Objectif : éviter à l'utilisateur d'aller chercher lui-même l'exécutable de
chaque jeu. On lit les manifestes que les launchers écrivent déjà sur le
disque, puis on désigne l'exécutable le plus plausible.

Le choix de l'exécutable mérite une attention particulière. Beaucoup de jeux
Unreal Engine s'installent avec un lanceur (`MonJeu.exe`) qui démarre le
véritable processus (`MonJeu-Win64-Shipping.exe`). C'est ce dernier qui ouvre
la session audio, donc le seul que le routage doive viser : on le privilégie
explicitement lors de la sélection.
"""

from __future__ import annotations

import json
import re
import winreg
from dataclasses import dataclass
from pathlib import Path

# Emplacement des manifestes du launcher Epic (chemin fixe imposé par Epic).
EPIC_MANIFESTS_DIR = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"

# Profondeur maximale de fouille dans un dossier de jeu. Au delà, on ne
# trouve plus que des outils annexes, et le balayage devient coûteux.
_MAX_DEPTH = 4

# Dossiers qui ne contiennent jamais l'exécutable principal d'un jeu.
_SKIPPED_DIRS = {
    "_commonredist",
    "commonredist",
    "redist",
    "directx",
    "dotnet",
    "vcredist",
    "engine",
    "support",
    "installers",
    "prerequisites",
    "__installer",
    "tools",
    "editor",
    "docs",
    "manual",
}

# Fragments présents dans le nom des exécutables annexes livrés avec les
# jeux. Ils sont cherchés n'importe où dans le nom, donc ils doivent être
# assez spécifiques pour ne jamais apparaître dans un titre de jeu.
_EXCLUDED_EXE_PATTERNS = (
    "unins",
    "vcredist",
    "dxsetup",
    "directx",
    "dotnet",
    "crashreport",
    "crashhandler",
    "crashpad",
    "setup",
    "installer",
    "redist",
    "eossdk",
    "easyanticheat",
    "anticheat",
    "battleye",
    "be_service",
    "touchup",
    "notification_helper",
    "epicwebhelper",
    "cefprocess",
    "subprocess",
    "launcher",
    "updater",
    "uninstall",
    # Amorceurs des services en ligne, systématiquement plus gros que le jeu
    # lui-même : sans cette exclusion, ils remportent le choix par la taille.
    "bootstrapper",
    "prereq",
    "activationui",
)

# Noms d'exécutables annexes trop courts ou trop courants pour être cherchés
# comme fragments : "start" apparaîtrait dans "Starcraft.exe", "play" dans
# "Playdead.exe". Ils ne sont donc écartés que sur correspondance exacte.
_EXCLUDED_EXE_STEMS = {
    "start",
    "play",
    "launch",
    "config",
    "configtool",
    "settings",
    "options",
    "patcher",
    "update",
    "server",
    "dedicatedserver",
    "editor",
    "benchmark",
    "cleanup",
    "activation",
    "register",
    "support",
    "helper",
}

# Deux exécutables dont les tailles sont dans ce rapport sont considérés
# comme des variantes du même binaire, et non comme un jeu face à un
# utilitaire : un vrai lanceur est plus petit d'un ordre de grandeur.
_VARIANT_RATIO = 0.8

# Processus réel des jeux Unreal Engine, à préférer au lanceur.
_SHIPPING_PATTERN = re.compile(r"-Win(?:32|64)-Shipping\.exe$", re.IGNORECASE)

# Extrait les paires "clé" "valeur" du format VDF de Valve.
_VDF_PAIR = re.compile(r'"([^"]+)"\s+"([^"]*)"')


@dataclass(frozen=True)
class InstalledGame:
    """Jeu détecté dans une bibliothèque, prêt à être ajouté à WaveRouter."""

    name: str
    source: str  # "Steam", "Epic Games" ou "GOG"
    exe_path: str
    install_dir: str = ""

    @property
    def process_name(self) -> str:
        return Path(self.exe_path).name


# ----------------------------------------------------------------------
# Sélection de l'exécutable principal
# ----------------------------------------------------------------------
def _is_excluded_exe(name: str) -> bool:
    """Vrai si cet exécutable est un utilitaire ou un lanceur, jamais le jeu."""
    lowered = name.lower()
    if any(pattern in lowered for pattern in _EXCLUDED_EXE_PATTERNS):
        return True
    return Path(name).stem.lower() in _EXCLUDED_EXE_STEMS


def _iter_executables(root: Path, depth: int = 0):
    """Parcourt les .exe du dossier, en signalant ceux qui sont écartés."""
    if depth > _MAX_DEPTH:
        return
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir():
                if entry.name.lower() not in _SKIPPED_DIRS:
                    yield from _iter_executables(entry, depth + 1)
            elif entry.suffix.lower() == ".exe":
                yield entry, _is_excluded_exe(entry.name)
        except OSError:
            continue


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def pick_main_executable(install_dir: str, game_name: str = "") -> str:
    """
    Retourne le chemin de l'exécutable le plus plausible pour ce jeu, ou une
    chaîne vide si le dossier n'en contient aucun d'exploitable.
    """
    root = Path(install_dir)
    if not root.is_dir():
        return ""

    tous = list(_iter_executables(root))
    if not tous:
        return ""
    candidates = [exe for exe, exclu in tous if not exclu]
    if not candidates:
        # Le dossier ne contient que des utilitaires et des lanceurs : mieux
        # vaut proposer le moins mauvais que de faire disparaître le jeu de
        # la liste, l'utilisateur pouvant corriger le nom du processus.
        candidates = [exe for exe, _ in tous]

    # 1. Le binaire Unreal réel, s'il existe : c'est lui qui produit le son.
    shipping = [exe for exe in candidates if _SHIPPING_PATTERN.search(exe.name)]
    if shipping:
        return str(max(shipping, key=_file_size))

    # 2. Un exécutable dont le nom correspond au jeu ou au dossier d'install.
    wanted = {_normalize(game_name), _normalize(root.name)} - {""}
    if wanted:
        matches = [exe for exe in candidates if _normalize(exe.stem) in wanted]
        if matches:
            return str(max(matches, key=_file_size))

    # 3. À défaut, le plus gros exécutable : le moteur du jeu pèse toujours
    #    bien plus lourd que les utilitaires et lanceurs qui l'accompagnent.
    #    Un jeu livre cependant parfois plusieurs variantes du même binaire
    #    ("Anno117.exe" et "Anno117_plus.exe", à 4 % l'un de l'autre). Entre
    #    tailles comparables, la taille ne veut plus rien dire : on retient
    #    alors le nom le plus court, c'est-à-dire celui sans suffixe.
    largest = _file_size(max(candidates, key=_file_size))
    variants = [exe for exe in candidates if _file_size(exe) >= largest * _VARIANT_RATIO]
    return str(min(variants, key=lambda exe: (len(exe.stem), -_file_size(exe))))


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


# ----------------------------------------------------------------------
# Steam
# ----------------------------------------------------------------------
def _read_registry_value(hive: int, key_path: str, value_name: str) -> str:
    try:
        with winreg.OpenKey(hive, key_path) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return str(value)
    except OSError:
        return ""


def find_steam_path() -> str:
    for hive, path, name in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ):
        value = _read_registry_value(hive, path, name)
        if value and Path(value).is_dir():
            return value
    return ""


def _steam_library_dirs(steam_path: str) -> list[Path]:
    """Retourne tous les dossiers `steamapps`, y compris sur disques secondaires."""
    libraries: list[Path] = []
    root_apps = Path(steam_path) / "steamapps"
    if root_apps.is_dir():
        libraries.append(root_apps)

    vdf = root_apps / "libraryfolders.vdf"
    try:
        content = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries

    for key, value in _VDF_PAIR.findall(content):
        if key.lower() != "path":
            continue
        apps = Path(value.replace("\\\\", "\\")) / "steamapps"
        if apps.is_dir() and apps not in libraries:
            libraries.append(apps)
    return libraries


def scan_steam_games() -> list[InstalledGame]:
    steam_path = find_steam_path()
    if not steam_path:
        return []

    games: list[InstalledGame] = []
    for library in _steam_library_dirs(steam_path):
        try:
            manifests = sorted(library.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for manifest in manifests:
            try:
                content = manifest.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fields = dict(_VDF_PAIR.findall(content))
            name = fields.get("name", "").strip()
            install_dir = fields.get("installdir", "").strip()
            if not name or not install_dir:
                continue
            full_dir = library / "common" / install_dir
            exe = pick_main_executable(str(full_dir), name)
            if exe:
                games.append(
                    InstalledGame(
                        name=name, source="Steam", exe_path=exe, install_dir=str(full_dir)
                    )
                )
    return games


# ----------------------------------------------------------------------
# Epic Games
# ----------------------------------------------------------------------
def scan_epic_games() -> list[InstalledGame]:
    manifest_dir = Path(EPIC_MANIFESTS_DIR)
    if not manifest_dir.is_dir():
        return []

    games: list[InstalledGame] = []
    try:
        items = sorted(manifest_dir.glob("*.item"))
    except OSError:
        return []

    for item in items:
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("DisplayName", "")).strip()
        install_location = str(data.get("InstallLocation", "")).strip()
        launch_exe = str(data.get("LaunchExecutable", "")).strip()
        if not name or not install_location:
            continue

        # Epic indique directement l'exécutable de lancement, mais il peut
        # s'agir d'un lanceur Unreal : on laisse la sélection trancher.
        exe = pick_main_executable(install_location, name)
        if not exe and launch_exe:
            candidate = Path(install_location) / launch_exe
            exe = str(candidate) if candidate.is_file() else ""
        if exe:
            games.append(
                InstalledGame(
                    name=name,
                    source="Epic Games",
                    exe_path=exe,
                    install_dir=install_location,
                )
            )
    return games


# ----------------------------------------------------------------------
# GOG
# ----------------------------------------------------------------------
def scan_gog_games() -> list[InstalledGame]:
    games: list[InstalledGame] = []
    seen: set[str] = set()

    for hive, base in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games"),
    ):
        try:
            root = winreg.OpenKey(hive, base)
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, sub_name) as sub:
                        name = _query(sub, "gameName")
                        path = _query(sub, "path")
                        exe = _query(sub, "exe") or _query(sub, "exeFile")
                except OSError:
                    continue
                if not name or not path:
                    continue

                full_exe = ""
                if exe:
                    candidate = Path(exe)
                    if not candidate.is_absolute():
                        candidate = Path(path) / exe
                    if candidate.is_file():
                        full_exe = str(candidate)
                if not full_exe:
                    full_exe = pick_main_executable(path, name)
                if full_exe and full_exe.lower() not in seen:
                    seen.add(full_exe.lower())
                    games.append(
                        InstalledGame(
                            name=name, source="GOG", exe_path=full_exe, install_dir=path
                        )
                    )
    return games


def _query(key, value_name: str) -> str:
    try:
        value, _ = winreg.QueryValueEx(key, value_name)
        return str(value).strip()
    except OSError:
        return ""


# ----------------------------------------------------------------------
# Dossier personnalisé
# ----------------------------------------------------------------------
def scan_folder(folder: str) -> list[InstalledGame]:
    """
    Détecte les jeux contenus dans un dossier quelconque.

    Couvre les bibliothèques qu'aucun launcher ne référence : jeux portables,
    copies manuelles, disque de jeux rangé à la main. Chaque sous-dossier
    direct est considéré comme un jeu et prend son nom ; si le dossier
    désigné contient lui-même des exécutables sans sous-dossier de jeu, il
    est traité comme un jeu unique.
    """
    root = Path(folder)
    if not root.is_dir():
        return []

    games: list[InstalledGame] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []

    for entry in entries:
        try:
            if not entry.is_dir() or entry.name.lower() in _SKIPPED_DIRS:
                continue
        except OSError:
            continue
        exe = pick_main_executable(str(entry), entry.name)
        if exe:
            games.append(
                InstalledGame(
                    name=entry.name, source="Dossier", exe_path=exe, install_dir=str(entry)
                )
            )

    if not games:
        exe = pick_main_executable(str(root), root.name)
        if exe:
            games.append(
                InstalledGame(
                    name=root.name, source="Dossier", exe_path=exe, install_dir=str(root)
                )
            )
    return games


# ----------------------------------------------------------------------
# Point d'entrée
# ----------------------------------------------------------------------
def scan_installed_games(extra_folders: list[str] | None = None) -> list[InstalledGame]:
    """
    Retourne tous les jeux détectés, dédupliqués par exécutable et triés par
    nom. Le balayage touche le disque : à lancer depuis un thread de fond,
    jamais depuis le thread de l'interface.

    `extra_folders` ajoute des dossiers de jeux choisis par l'utilisateur,
    parcourus en plus des bibliothèques Steam, Epic Games et GOG.
    """
    all_games: list[InstalledGame] = []
    for scanner in (scan_steam_games, scan_epic_games, scan_gog_games):
        try:
            all_games.extend(scanner())
        except Exception:
            continue  # Un launcher absent ou une clé illisible ne doit rien casser

    for folder in extra_folders or []:
        try:
            all_games.extend(scan_folder(folder))
        except Exception:
            continue  # Dossier déplacé, disque débranché, droits insuffisants

    unique: dict[str, InstalledGame] = {}
    for game in all_games:
        key = game.exe_path.lower()
        if key not in unique:
            unique[key] = game
    return sorted(unique.values(), key=lambda g: g.name.lower())

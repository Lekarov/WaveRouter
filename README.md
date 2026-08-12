<div align="center">

# 🌊 WaveRouter

**Routage audio automatique des jeux vers Elgato Wave Link, sur Windows.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![UI](https://img.shields.io/badge/UI-CustomTkinter-7C5CFF)](https://github.com/TomSchimansky/CustomTkinter)
[![Status](https://img.shields.io/badge/status-active-brightgreen)](#)

</div>

---

## 🎯 À quoi ça sert

[Elgato Wave Link](https://www.elgato.com/wavelink) ne détecte pas automatiquement
tous les jeux : certains partent par défaut dans le canal **System** au lieu du
canal **Games!**, obligeant à corriger le routage manuellement à chaque lancement.

**WaveRouter** tourne en arrière-plan, surveille les processus actifs sur ta
machine et force automatiquement le bon routage audio dès qu'un jeu de ta liste
est détecté — sans aucune intervention manuelle.

## ✨ Fonctionnalités

- 🖥️ **Interface moderne** (CustomTkinter, thème sombre) avec navigation
  latérale : tableau de bord, jeux, réglages, logs
- 🎮 **Liste de jeux gérable visuellement** — ajout via sélecteur de fichier,
  ou **détection automatique** parmi les fenêtres actuellement ouvertes
- 🖼️ **Icônes réelles des jeux** extraites directement de leurs `.exe`
- 🔍 **Surveillance en arrière-plan** (thread dédié, scan configurable, 3s par défaut)
- 🔔 **Icône dans la barre système** avec notifications discrètes de routage
- 📜 **Panneau de logs horodaté** pour diagnostiquer un souci de détection
- 🚀 **Démarrage automatique avec Windows** (optionnel)
- 💾 **Configuration persistante** (JSON, rechargée automatiquement)

## 🧠 Comment ça fonctionne

```
┌─────────────────┐     toutes les 3s      ┌──────────────────────┐
│ ProcessMonitor   │ ─────────────────────▶ │ Liste des processus  │
│ (thread de fond) │                        │ actifs (psutil)      │
└────────┬─────────┘                        └──────────────────────┘
         │ jeu détecté
         ▼
┌─────────────────┐   commande CLI    ┌──────────────────────┐
│ AudioBackend      │ ─────────────────▶ │ SoundVolumeView.exe  │
│ (wrapper)         │                    │ (Nirsoft)             │
└────────┬───────────┘                  └──────────┬───────────┘
         │                                          │ force le périphérique
         ▼                                          ▼
┌─────────────────┐                        ┌──────────────────────┐
│ Logs + tableau   │                        │ Canal Wave Link cible │
│ de bord + toast   │                        │ (ex: Games!)          │
└─────────────────┘                        └──────────────────────┘
```

WaveRouter ne remplace pas Wave Link : il pilote en coulisse la fonctionnalité
Windows *"préférences de périphérique par application"* via l'outil en ligne de
commande [SoundVolumeView](#-soundvolumeview--pourquoi-il-nest-pas-inclus) de
Nirsoft, pour forcer chaque jeu de ta liste vers le canal Wave Link choisi.

## 📥 Installation

### Option rapide (recommandée)

1. Télécharge ou clone ce dépôt
2. Double-clique sur `lancer_waverouter.bat` — il crée automatiquement un
   environnement virtuel Python et installe les dépendances au premier
   lancement, puis démarre l'application

### Option manuelle

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Ajoute `--debug` pour un mode verbeux (diagnostic de la détection), aussi
activable à chaud dans l'onglet **Réglages**.

## 🔊 SoundVolumeView — pourquoi il n'est pas inclus

WaveRouter s'appuie sur **SoundVolumeView**, un outil gratuit de
[NirSoft](https://www.nirsoft.net/utils/sound_volume_view.html). **Son
exécutable n'est pas fourni dans ce dépôt** : la licence NirSoft autorise la
redistribution de ses utilitaires sous certaines conditions, mais interdit
explicitement de les héberger soi-même (miroir) sans autorisation — il doit
être téléchargé depuis le site officiel.

**Comment l'obtenir :**

1. Va sur la [page officielle SoundVolumeView](https://www.nirsoft.net/utils/sound_volume_view.html)
2. Télécharge la version 64 bits (ou 32 bits selon ton système)
3. Dézippe `SoundVolumeView.exe` où tu veux (aucune installation requise)
4. Dans WaveRouter → **Réglages**, renseigne son chemin (bouton "Parcourir...",
   ou "Télécharger" pour ouvrir directement la page officielle)

## ⚙️ Configuration

| Donnée | Emplacement |
|---|---|
| Jeux + réglages | `%APPDATA%\DoktorP3st\WaveRouter\config.json` |
| Logs | `%APPDATA%\DoktorP3st\WaveRouter\logs\app.log` |

## 📦 Packaging en `.exe` autonome

```powershell
pip install pyinstaller
pyinstaller --noconsole --onefile --name WaveRouter `
    --collect-all customtkinter `
    --collect-all pystray `
    --collect-all plyer `
    main.py
```

L'exécutable final se trouve dans `dist\WaveRouter.exe`. L'option "Lancer au
démarrage de Windows" détecte automatiquement si l'app tourne en `.exe`
packagé ou en script Python, et enregistre la bonne commande dans le registre
(`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). Aucun droit
administrateur n'est requis.

## 🗂️ Structure du projet

```
WaveRouter/
├── main.py                       # Point d'entrée
├── lancer_waverouter.bat         # Lancement + installation auto des dépendances
├── requirements.txt
└── waverouter/
    ├── config.py                 # Modèle + persistance JSON
    ├── logger.py                 # Journalisation (fichier + callbacks UI)
    ├── audio_backend.py          # Wrapper CLI SoundVolumeView
    ├── wavelink_devices.py       # Détection des périphériques de sortie audio
    ├── process_monitor.py        # Thread de surveillance des processus
    ├── window_processes.py       # Détection des fenêtres ouvertes (ajout rapide)
    ├── icon_extractor.py         # Extraction d'icône depuis un .exe (ctypes/GDI)
    ├── autostart.py              # Démarrage automatique Windows (registre)
    └── ui/
        ├── theme.py               # Palette de couleurs et constantes de style
        ├── main_window.py         # Fenêtre principale (CustomTkinter)
        ├── dialogs.py              # Boîtes de dialogue d'ajout/édition de jeu
        └── tray.py                 # Icône barre système (pystray)
```

## 🩺 Diagnostic

- Active le **mode debug** pour voir, dans l'onglet **Logs**, le détail de
  chaque scan (processus actifs, jeux surveillés, marquages retirés...)
- Aucun canal détecté ? Vérifie que Wave Link est lancé et que le chemin vers
  `SoundVolumeView.exe` est correct, puis clique sur "Actualiser les canaux"
- Un routage échoue ? Le message d'erreur exact renvoyé par SoundVolumeView
  apparaît dans les logs

## 📄 Licence

Distribué sous licence [MIT](LICENSE). SoundVolumeView reste la propriété de
NirSoft et n'est pas couvert par cette licence — voir la section dédiée
ci-dessus.

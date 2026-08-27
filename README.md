<div align="center">

# 🌊 WaveRouter

**Routage audio automatique des jeux vers Elgato Wave Link, sur Windows.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![UI](https://img.shields.io/badge/UI-PySide6%20%2F%20Qt-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![Tests](https://img.shields.io/badge/tests-102%20passing-brightgreen)](#-tests)
[![Status](https://img.shields.io/badge/status-active-brightgreen)](#)

</div>

---

## 🎯 À quoi ça sert

[Elgato Wave Link](https://www.elgato.com/wavelink) ne détecte pas automatiquement
tous les jeux : certains partent par défaut dans le canal **System** au lieu du
canal **Games!**, obligeant à corriger le routage manuellement à chaque lancement.

**WaveRouter** tourne en arrière-plan, détecte un jeu à l'instant où il démarre,
force le bon routage audio, puis **vérifie que Windows l'a réellement appliqué**.

## ✨ Fonctionnalités

- 🎮 **Import de ta bibliothèque** — détecte les jeux installés dans Steam,
  Epic Games et GOG, et sait aussi analyser n'importe quel dossier pour les
  jeux installés à la main
- ⚡ **Détection au lancement** — comparaison différentielle des processus,
  assez légère pour tourner à la seconde
- ✅ **Routage confirmé** — la préférence est posée immédiatement, puis
  vérifiée sur les sessions audio réelles et réappliquée jusqu'à confirmation
- 🔎 **Détection automatique de nouveaux jeux** — une application inconnue qui
  joue du son en plein écran est proposée à l'ajout
- 🖼️ **Icônes réelles des jeux** extraites directement de leurs `.exe`
- 🖥️ **Interface Qt** (thème sombre) : tableau de bord, jeux, réglages, logs
- 🔔 **Barre système et notifications natives** Windows
- 🔒 **Instance unique**, démarrage automatique optionnel, logs avec rotation

## 🧠 Comment ça fonctionne

```
┌──────────────────┐   psutil.pids()    ┌────────────────────────┐
│ ProcessMonitor   │ ──── ~0,01 ms ───▶ │ Nouveaux PID depuis     │
│ (thread de fond) │                    │ le tick précédent       │
└────────┬─────────┘                    └────────────────────────┘
         │ jeu de la liste détecté
         ▼
┌──────────────────┐   /SetAppDefault   ┌────────────────────────┐
│ AudioBackend     │ ─────────────────▶ │ SoundVolumeView.exe     │
└────────┬─────────┘                    └───────────┬────────────┘
         │                                          │
         │ ◀──── /scomma : sessions audio ──────────┘
         │
         ▼
   Le jeu sort-il sur le bon canal ?
         │                    │
      oui│                    │non → on réapplique, jusqu'à 60 s
         ▼
┌──────────────────┐
│ Routage confirmé  │  → tableau de bord, log, notification
└──────────────────┘
```

WaveRouter ne remplace pas Wave Link : il pilote en coulisse la fonctionnalité
Windows *« préférences de périphérique par application »* via l'outil en ligne
de commande [SoundVolumeView](#-soundvolumeview--pourquoi-il-nest-pas-inclus)
de Nirsoft.

**Pourquoi vérifier ?** `/SetAppDefault` enregistre une préférence, il ne
redirige pas un flux audio déjà ouvert. Selon que le moteur audio du jeu
s'initialise avant ou après la commande, le routage prend ou se perd
silencieusement. WaveRouter relit donc les sessions audio réelles jusqu'à
confirmer que le jeu sort bien sur le canal voulu.

## 📥 Installation

### Option rapide (recommandée)

1. Télécharge ou clone ce dépôt
2. Double-clique sur `lancer_waverouter.bat` — il crée l'environnement virtuel,
   installe les dépendances au premier lancement, puis démarre l'application

### Option manuelle

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Options : `--debug` pour le mode verbeux (aussi activable dans **Réglages**),
`--minimized` pour démarrer directement dans la barre système.

## 🔊 SoundVolumeView — pourquoi il n'est pas inclus

WaveRouter s'appuie sur **SoundVolumeView**, un outil gratuit de
[NirSoft](https://www.nirsoft.net/utils/sound_volume_view.html). **Son
exécutable n'est pas fourni dans ce dépôt** : la licence NirSoft autorise la
redistribution de ses utilitaires sous certaines conditions, mais interdit
explicitement de les héberger soi-même (miroir) sans autorisation.

**Comment l'obtenir :**

1. Va sur la [page officielle SoundVolumeView](https://www.nirsoft.net/utils/sound_volume_view.html)
2. Télécharge la version 64 bits (ou 32 bits selon ton système)
3. Dézippe `SoundVolumeView.exe` où tu veux (aucune installation requise)
4. Dans WaveRouter → **Réglages**, renseigne son chemin (bouton « Parcourir... »,
   ou « Télécharger » pour ouvrir directement la page officielle)

## 🎮 Ajouter tes jeux

| Méthode | Quand l'utiliser |
|---|---|
| **Importer mes jeux** | Le plus rapide : liste tes jeux Steam, Epic Games et GOG. Le bouton « Ajouter un dossier... » couvre les jeux installés à la main. |
| **Détecter un jeu en cours** | Le jeu tourne déjà : on le choisit parmi les fenêtres ouvertes. |
| **+ Ajouter un jeu** | Saisie manuelle de l'exécutable. |
| *Automatique* | Une application inconnue qui joue du son en plein écran est proposée d'elle-même. |

L'import vise le **processus qui produit réellement le son**, pas le lanceur :
un jeu Unreal est surveillé sur son binaire `-Win64-Shipping.exe`, et les
amorceurs (`EOSBootstrapper`, `*Launcher`…) sont écartés.

## ⚙️ Configuration

| Donnée | Emplacement |
|---|---|
| Jeux + réglages | `%APPDATA%\DoktorP3st\WaveRouter\config.json` |
| Logs | `%APPDATA%\DoktorP3st\WaveRouter\logs\app.log` |

## 🧪 Tests

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

102 tests couvrent la logique non graphique : configuration, backend audio,
moteur de surveillance, découverte des jeux, journalisation, démarrage
automatique.

## 📦 Packaging en `.exe` autonome

```powershell
pip install pyinstaller
pyinstaller --noconsole --onefile --name WaveRouter main.py
```

L'exécutable final se trouve dans `dist\WaveRouter.exe`. L'option « Lancer au
démarrage de Windows » détecte automatiquement si l'app tourne en `.exe`
packagé ou en script Python, et enregistre la bonne commande dans le registre
(`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). Aucun droit
administrateur n'est requis.

## 🗂️ Structure du projet

```
WaveRouter/
├── main.py                       # Point d'entrée
├── lancer_waverouter.bat         # Lancement + installation auto des dépendances
├── requirements.txt
├── tests/                        # 102 tests (logique non graphique)
└── waverouter/
    ├── config.py                 # Modèle + persistance JSON atomique
    ├── logger.py                 # Journalisation (fichier avec rotation + UI)
    ├── audio_backend.py          # Wrapper CLI SoundVolumeView
    ├── wavelink_devices.py       # Détection des périphériques de sortie
    ├── process_monitor.py        # Détection différentielle + routage confirmé
    ├── game_library.py           # Jeux installés (Steam, Epic, GOG, dossiers)
    ├── window_processes.py       # Fenêtres ouvertes, détection plein écran
    ├── icon_extractor.py         # Extraction d'icône depuis un .exe (ctypes/GDI)
    ├── autostart.py              # Démarrage automatique Windows (registre)
    ├── single_instance.py        # Mutex nommé : une seule instance
    └── ui/                       # PySide6 ; le moteur n'importe jamais Qt
        ├── theme.py              # Palette + feuille de style globale
        ├── widgets.py            # Composants réutilisables
        ├── main_window.py        # Fenêtre principale
        ├── dialogs.py            # Ajout, détection, import de bibliothèque
        └── tray.py               # Barre système + notifications
```

## 🩺 Diagnostic

- Active le **mode debug** pour voir, dans l'onglet **Logs**, sur quel canal
  chaque jeu sort réellement à chaque tentative de routage
- Aucun canal détecté ? Vérifie que Wave Link est lancé et que le chemin vers
  `SoundVolumeView.exe` est correct, puis clique sur « Actualiser la liste des
  canaux »
- Un routage n'est jamais confirmé ? Le canal a peut-être été renommé dans
  Wave Link : compare avec le nom affiché sur la fiche du jeu
- Le mauvais exécutable a été importé ? Modifie le jeu (icône crayon) et
  corrige le nom du processus, il n'a pas besoin de correspondre au lanceur

## 📄 Licence

Distribué sous licence [MIT](LICENSE). SoundVolumeView reste la propriété de
NirSoft et n'est pas couvert par cette licence — voir la section dédiée
ci-dessus.

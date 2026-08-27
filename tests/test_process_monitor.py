"""
Tests du moteur de surveillance.

`_tick()` est appelé directement plutôt que via le thread : le comportement
reste identique et les scénarios deviennent déterministes, y compris ceux qui
dépendent du temps (expiration du délai de confirmation).
"""

from __future__ import annotations

import psutil
import pytest

from waverouter import window_processes
from waverouter.audio_backend import AppSession
from waverouter.config import AppConfig, GameEntry, Settings
from waverouter.logger import EventLogger
from waverouter.process_monitor import ProcessMonitor


class FakeBackend:
    """Backend audio simulé : enregistre les commandes et sert des sessions."""

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.calls: list[tuple[str, str]] = []  # (device, process)
        self.sessions: list[AppSession] = []
        self.fail_next = False

    def is_available(self) -> bool:
        return self.available

    def set_app_default_device(self, device_name: str, process_name: str) -> None:
        if self.fail_next:
            from waverouter.audio_backend import SoundVolumeViewError

            self.fail_next = False
            raise SoundVolumeViewError("échec simulé")
        self.calls.append((device_name, process_name))

    def list_app_sessions(self) -> list[AppSession]:
        return list(self.sessions)


class FakeProcess:
    def __init__(self, pid: int, name: str, exe: str = "") -> None:
        self.pid = pid
        self._name = name
        self._exe = exe or f"C:\\Jeux\\{name}"

    def name(self) -> str:
        return self._name

    def exe(self) -> str:
        return self._exe


@pytest.fixture
def env(monkeypatch):
    """Environnement de test : table de processus et backend pilotables."""

    table: dict[int, FakeProcess] = {}

    monkeypatch.setattr(psutil, "pids", lambda: list(table))

    def fake_process(pid):
        if pid not in table:
            raise psutil.NoSuchProcess(pid)
        return table[pid]

    monkeypatch.setattr(psutil, "Process", fake_process)
    # Par défaut aucune fenêtre plein écran : la détection automatique ne se
    # déclenche que dans les tests qui la simulent explicitement.
    monkeypatch.setattr(window_processes, "find_fullscreen_window_title", lambda pid: None)
    return table


def build_monitor(config: AppConfig, backend: FakeBackend, **callbacks) -> ProcessMonitor:
    return ProcessMonitor(
        config=config,
        backend_factory=lambda: backend,
        logger=EventLogger(debug=False),
        **callbacks,
    )


def config_avec_jeu(**settings_kwargs) -> AppConfig:
    settings = Settings(soundvolumeview_path="C:/svv.exe", auto_detect_games=False)
    for key, value in settings_kwargs.items():
        setattr(settings, key, value)
    return AppConfig(
        games=[GameEntry(label="Hunt", process_name="HuntGame.exe", channel="Games!")],
        settings=settings,
    )


# ----------------------------------------------------------------------
# Détection et application du routage
# ----------------------------------------------------------------------
def test_jeu_lance_declenche_le_routage(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()

    assert backend.calls == [("Games!", "HuntGame.exe")]


def test_process_inconnu_nest_pas_route(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "chrome.exe")
    monitor._tick()

    assert backend.calls == []


def test_jeu_suspendu_nest_pas_route(env):
    backend = FakeBackend()
    config = config_avec_jeu()
    config.games[0].enabled = False
    monitor = build_monitor(config, backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()

    assert backend.calls == []


def test_jeu_sans_canal_nest_pas_route(env):
    backend = FakeBackend()
    config = config_avec_jeu()
    config.games[0].channel = ""
    monitor = build_monitor(config, backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()

    assert backend.calls == []


def test_correspondance_insensible_a_la_casse(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "HUNTGAME.EXE")
    monitor._tick()

    assert len(backend.calls) == 1


# ----------------------------------------------------------------------
# Confirmation du routage
# ----------------------------------------------------------------------
def test_routage_confirme_quand_la_session_sort_sur_le_bon_canal(env):
    routed: list[tuple[str, str]] = []
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend, on_routed=lambda l, c: routed.append((l, c)))

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()  # détection + application immédiate
    assert routed == []  # pas encore de session audio

    backend.sessions = [AppSession("HuntGame.exe", 100, "Games!")]
    monitor._tick()

    assert routed == [("Hunt", "Games!")]
    assert len(monitor.active_routes()) == 1


def test_routage_reapplique_si_le_jeu_sort_ailleurs(env):
    """
    Cas central du correctif : le jeu avait déjà ouvert son flux audio quand
    la préférence a été posée, il sort donc encore sur l'ancien périphérique.
    """
    routed: list[tuple[str, str]] = []
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend, on_routed=lambda l, c: routed.append((l, c)))

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()
    assert len(backend.calls) == 1

    backend.sessions = [AppSession("HuntGame.exe", 100, "Haut-parleurs")]
    monitor._tick()
    assert len(backend.calls) == 2  # nouvelle tentative
    assert routed == []

    backend.sessions = [AppSession("HuntGame.exe", 100, "Games!")]
    monitor._tick()
    assert routed == [("Hunt", "Games!")]


def test_comparaison_de_canal_tolerante_a_la_casse(env):
    routed: list[tuple[str, str]] = []
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend, on_routed=lambda l, c: routed.append((l, c)))

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()
    backend.sessions = [AppSession("HuntGame.exe", 100, "  games!  ")]
    monitor._tick()

    assert routed == [("Hunt", "Games!")]


def test_confirme_si_le_bon_canal_figure_parmi_plusieurs_sessions(env):
    """
    Cas observé en conditions réelles : une application conserve des sessions
    résiduelles sur les canaux qu'elle a utilisés auparavant. La présence du
    canal visé suffit, sinon un jeu correctement routé serait déclaré en
    échec à cause de sessions périmées.
    """
    routed: list[tuple[str, str]] = []
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend, on_routed=lambda l, c: routed.append((l, c)))

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()
    backend.sessions = [
        AppSession("HuntGame.exe", 100, "Haut-parleurs"),
        AppSession("HuntGame.exe", 100, "Games!"),
        AppSession("HuntGame.exe", 100, "System"),
    ]
    monitor._tick()

    assert routed == [("Hunt", "Games!")]


def test_plusieurs_processus_du_meme_nom_ne_routent_quune_fois(env):
    """
    Régression relevée en conditions réelles : un navigateur ouvrait dix-huit
    processus du même nom, donc dix-huit commandes, logs et notifications pour
    un seul routage. `/SetAppDefault` visant l'exécutable et non l'instance,
    une seule application suffit.
    """
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    for pid in range(100, 118):
        env[pid] = FakeProcess(pid, "HuntGame.exe")
    monitor._tick()

    assert len(backend.calls) == 1


def test_confirmation_via_un_processus_enfant(env):
    """Le son peut venir d'un autre processus de même nom que celui détecté."""
    routed: list[tuple[str, str]] = []
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend, on_routed=lambda l, c: routed.append((l, c)))

    env[100] = FakeProcess(100, "HuntGame.exe")
    env[101] = FakeProcess(101, "HuntGame.exe")
    monitor._tick()

    backend.sessions = [AppSession("HuntGame.exe", 101, "Games!")]
    monitor._tick()

    assert routed == [("Hunt", "Games!")]


def test_routage_maintenu_tant_quune_instance_tourne(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    env[101] = FakeProcess(101, "HuntGame.exe")
    monitor._tick()
    backend.sessions = [AppSession("HuntGame.exe", 100, "Games!")]
    monitor._tick()
    assert len(monitor.active_routes()) == 1

    del env[100]  # une instance se ferme, l'autre continue
    monitor._tick()
    assert len(monitor.active_routes()) == 1

    del env[101]
    monitor._tick()
    assert monitor.active_routes() == []


def test_jeu_silencieux_reste_enregistre_apres_le_delai(env):
    """Un jeu qui n'ouvre jamais de session garde sa préférence, sans erreur."""
    backend = FakeBackend()
    # Délai nul : la première vérification déclenche déjà l'expiration.
    monitor = build_monitor(config_avec_jeu(routing_confirm_seconds=0.0), backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()
    backend.sessions = [AppSession("autre.exe", 1, "Haut-parleurs")]
    monitor._tick()

    assert len(monitor.active_routes()) == 1
    assert monitor.active_routes()[0].channel == "Games!"


def test_plus_aucun_appel_backend_sans_routage_en_attente(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "chrome.exe")
    monitor._tick()
    appels_avant = len(backend.calls)
    monitor._tick()  # rien de neuf : le tick doit rester gratuit

    assert len(backend.calls) == appels_avant


def test_backend_indisponible_ne_plante_pas(env):
    backend = FakeBackend(available=False)
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()  # ne doit lever aucune exception

    assert backend.calls == []


def test_echec_de_commande_ne_plante_pas(env):
    backend = FakeBackend()
    backend.fail_next = True
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()

    assert backend.calls == []  # l'appel a échoué, rien n'a été enregistré


# ----------------------------------------------------------------------
# Cycle de vie des processus
# ----------------------------------------------------------------------
def test_fermeture_du_jeu_libere_le_routage(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()
    backend.sessions = [AppSession("HuntGame.exe", 100, "Games!")]
    monitor._tick()
    assert len(monitor.active_routes()) == 1

    del env[100]
    backend.sessions = []
    monitor._tick()

    assert monitor.active_routes() == []


def test_relance_du_jeu_reroute(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()
    del env[100]
    monitor._tick()

    env[200] = FakeProcess(200, "HuntGame.exe")  # nouveau PID après relance
    monitor._tick()

    assert len(backend.calls) == 2


def test_processus_disparu_pendant_le_scan_est_ignore(env, monkeypatch):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    # Le PID est listé mais le processus meurt avant qu'on lise son nom.
    monkeypatch.setattr(psutil, "pids", lambda: [999])
    monitor._tick()  # ne doit lever aucune exception

    assert backend.calls == []


# ----------------------------------------------------------------------
# Détection automatique d'un nouveau jeu
# ----------------------------------------------------------------------
def config_detection_auto() -> AppConfig:
    return AppConfig(
        settings=Settings(soundvolumeview_path="C:/svv.exe", auto_detect_games=True)
    )


def test_application_avec_son_et_plein_ecran_est_proposee(env, monkeypatch):
    candidats: list[tuple[str, str, str]] = []
    backend = FakeBackend()
    monitor = build_monitor(
        config_detection_auto(), backend, on_game_candidate=lambda p, e, t: candidats.append((p, e, t))
    )

    env[100] = FakeProcess(100, "NouveauJeu.exe")
    monitor._tick()

    backend.sessions = [AppSession("NouveauJeu.exe", 100, "Haut-parleurs")]
    monkeypatch.setattr(window_processes, "find_fullscreen_window_title", lambda pid: "Nouveau Jeu")
    monitor._tick()

    assert candidats == [("NouveauJeu.exe", "C:\\Jeux\\NouveauJeu.exe", "Nouveau Jeu")]


def test_application_avec_son_mais_en_fenetre_nest_pas_proposee(env):
    candidats: list = []
    backend = FakeBackend()
    monitor = build_monitor(
        config_detection_auto(), backend, on_game_candidate=lambda *a: candidats.append(a)
    )

    env[100] = FakeProcess(100, "Lecteur.exe")
    monitor._tick()
    backend.sessions = [AppSession("Lecteur.exe", 100, "Haut-parleurs")]
    monitor._tick()  # pas de fenêtre plein écran (défaut du fixture)

    assert candidats == []


def test_application_sans_son_nest_pas_proposee(env, monkeypatch):
    candidats: list = []
    backend = FakeBackend()
    monitor = build_monitor(
        config_detection_auto(), backend, on_game_candidate=lambda *a: candidats.append(a)
    )
    monkeypatch.setattr(window_processes, "find_fullscreen_window_title", lambda pid: "Plein écran")

    env[100] = FakeProcess(100, "Outil.exe")
    monitor._tick()
    monitor._tick()  # aucune session audio

    assert candidats == []


def test_processus_systeme_nest_jamais_propose(env, monkeypatch):
    candidats: list = []
    backend = FakeBackend()
    monitor = build_monitor(
        config_detection_auto(), backend, on_game_candidate=lambda *a: candidats.append(a)
    )
    monkeypatch.setattr(window_processes, "find_fullscreen_window_title", lambda pid: "Chrome")

    env[100] = FakeProcess(100, "chrome.exe")
    monitor._tick()
    backend.sessions = [AppSession("chrome.exe", 100, "Haut-parleurs")]
    monitor._tick()

    assert candidats == []


def test_processus_ignore_nest_plus_propose(env, monkeypatch):
    candidats: list = []
    backend = FakeBackend()
    config = config_detection_auto()
    config.ignore_process("NouveauJeu.exe")
    monitor = build_monitor(config, backend, on_game_candidate=lambda *a: candidats.append(a))
    monkeypatch.setattr(window_processes, "find_fullscreen_window_title", lambda pid: "Jeu")

    env[100] = FakeProcess(100, "NouveauJeu.exe")
    monitor._tick()
    backend.sessions = [AppSession("NouveauJeu.exe", 100, "Haut-parleurs")]
    monitor._tick()

    assert candidats == []


def test_meme_jeu_propose_une_seule_fois(env, monkeypatch):
    candidats: list = []
    backend = FakeBackend()
    monitor = build_monitor(
        config_detection_auto(), backend, on_game_candidate=lambda *a: candidats.append(a)
    )
    monkeypatch.setattr(window_processes, "find_fullscreen_window_title", lambda pid: "Jeu")

    env[100] = FakeProcess(100, "NouveauJeu.exe")
    monitor._tick()
    backend.sessions = [AppSession("NouveauJeu.exe", 100, "Haut-parleurs")]
    monitor._tick()
    assert len(candidats) == 1

    del env[100]
    monitor._tick()
    env[200] = FakeProcess(200, "NouveauJeu.exe")  # relance du même jeu
    monitor._tick()
    backend.sessions = [AppSession("NouveauJeu.exe", 200, "Haut-parleurs")]
    monitor._tick()

    assert len(candidats) == 1


def test_detection_auto_desactivee(env, monkeypatch):
    candidats: list = []
    backend = FakeBackend()
    config = config_detection_auto()
    config.settings.auto_detect_games = False
    monitor = build_monitor(config, backend, on_game_candidate=lambda *a: candidats.append(a))
    monkeypatch.setattr(window_processes, "find_fullscreen_window_title", lambda pid: "Jeu")

    env[100] = FakeProcess(100, "NouveauJeu.exe")
    monitor._tick()
    backend.sessions = [AppSession("NouveauJeu.exe", 100, "Haut-parleurs")]
    monitor._tick()

    assert candidats == []


# ----------------------------------------------------------------------
# Pause
# ----------------------------------------------------------------------
def test_bascule_de_pause_notifie_letat(env):
    etats: list[bool] = []
    backend = FakeBackend()
    monitor = build_monitor(
        config_avec_jeu(), backend, on_state_changed=lambda: etats.append(True)
    )

    assert monitor.toggle_pause() is True
    assert monitor.is_paused is True
    assert monitor.toggle_pause() is False
    assert len(etats) == 2


# ----------------------------------------------------------------------
# Routage immédiat d'un jeu déjà lancé (ajout/édition depuis l'interface)
# ----------------------------------------------------------------------
def test_jeu_ajoute_alors_quil_tourne_est_route_immediatement(env):
    backend = FakeBackend()
    config = AppConfig(settings=Settings(soundvolumeview_path="C:/svv.exe", auto_detect_games=False))
    monitor = build_monitor(config, backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()
    assert backend.calls == []  # jeu inconnu de la config : rien ne se passe

    # L'utilisateur ajoute le jeu pendant qu'il tourne.
    config.games.append(GameEntry(label="Hunt", process_name="HuntGame.exe", channel="Games!"))
    assert monitor.request_route("HuntGame.exe", "Hunt", "Games!") is True
    assert backend.calls == [("Games!", "HuntGame.exe")]

    # La confirmation suit le circuit normal.
    backend.sessions = [AppSession("HuntGame.exe", 100, "Games!")]
    monitor._tick()
    assert len(monitor.active_routes()) == 1


def test_request_route_sans_processus_en_cours(env, monkeypatch):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [])

    monitor._tick()  # aucun processus
    assert monitor.request_route("HuntGame.exe", "Hunt", "Games!") is False
    assert backend.calls == []


def test_request_route_sans_canal(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "autre.exe")
    monitor._tick()
    assert monitor.request_route("autre.exe", "Autre", "") is False
    assert backend.calls == []


def test_request_route_remplace_un_routage_confirme(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()
    backend.sessions = [AppSession("HuntGame.exe", 100, "Games!")]
    monitor._tick()
    assert len(monitor.active_routes()) == 1

    # L'utilisateur change le canal du jeu pendant qu'il tourne.
    assert monitor.request_route("HuntGame.exe", "Hunt", "Music") is True
    assert backend.calls[-1] == ("Music", "HuntGame.exe")

    backend.sessions = [AppSession("HuntGame.exe", 100, "Music")]
    monitor._tick()
    routes = monitor.active_routes()
    assert len(routes) == 1
    assert routes[0].channel == "Music"


def test_request_route_retrouve_un_processus_inconnu_du_moteur(env, monkeypatch):
    """Surveillance jamais démarrée : le processus est cherché via psutil."""
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    class FakeIterProcess:
        pid = 200
        info = {"name": "HuntGame.exe"}

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [FakeIterProcess()])

    assert monitor.request_route("HuntGame.exe", "Hunt", "Games!") is True
    assert backend.calls == [("Games!", "HuntGame.exe")]


def test_forget_process_abandonne_pending_et_actif(env):
    backend = FakeBackend()
    monitor = build_monitor(config_avec_jeu(), backend)

    env[100] = FakeProcess(100, "HuntGame.exe")
    monitor._tick()
    backend.sessions = [AppSession("HuntGame.exe", 100, "Games!")]
    monitor._tick()
    assert len(monitor.active_routes()) == 1

    monitor.forget_process("HuntGame.exe")
    assert monitor.active_routes() == []

    # Plus aucune session pending : le tick suivant n'appelle plus le backend.
    calls_avant = len(backend.calls)
    monitor._tick()
    assert len(backend.calls) == calls_avant

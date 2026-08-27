"""
Moteur de surveillance en arrière-plan : détecte les processus de jeux au
moment exact de leur lancement et applique le routage audio configuré, en
vérifiant qu'il a réellement été pris en compte.

Deux principes gouvernent ce module :

1. **Détection différentielle.** `psutil.pids()` est un unique appel système
   très bon marché. En comparant l'ensemble des PID d'un tick à l'autre, on
   ne résout le nom que des processus réellement nouveaux (zéro à deux en
   régime normal), au lieu d'interroger les trois cents processus de la
   machine à chaque scan. Le balayage devient assez léger pour tourner à la
   seconde, donc pour détecter un jeu quasiment à l'instant où il démarre.

2. **Routage confirmé.** `/SetAppDefault` enregistre une préférence Windows,
   il ne redirige pas un flux audio déjà ouvert. Appliquer une seule fois au
   lancement ne suffit donc pas : selon que le moteur audio du jeu s'ouvre
   avant ou après la commande, le routage prend ou se perd silencieusement.
   Chaque jeu détecté entre dans une file d'attente : on applique tout de
   suite (pour que la préférence précède l'ouverture du flux), puis on relit
   les sessions audio jusqu'à confirmer que le jeu sort bien sur le bon
   canal, en réappliquant si besoin, pendant `routing_confirm_seconds`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import psutil

from waverouter.audio_backend import AudioBackend, AppSession, SoundVolumeViewError
from waverouter.config import AppConfig
from waverouter.logger import EventLogger

# Callback appelé après un routage confirmé : (libellé_jeu, canal)
RoutedCallback = Callable[[str, str], None]
# Callback appelé quand une application inconnue ressemble à un jeu :
# (nom_du_process, chemin_exe, titre_de_fenêtre)
CandidateCallback = Callable[[str, str, str], None]
# Callback appelé quand l'état pause/reprise change
StateCallback = Callable[[], None]

# Délai maximal accordé à une application inconnue pour se révéler être un
# jeu (ouvrir sa fenêtre et sa session audio) avant qu'on cesse de l'observer.
_CANDIDATE_OBSERVE_SECONDS = 45.0


@dataclass
class PendingRoute:
    """Routage appliqué, en attente de confirmation par la session audio."""

    process_name: str
    label: str
    channel: str
    deadline: float
    pid: int = 0  # première instance repérée, à titre informatif
    attempts: int = 0
    session_seen: bool = False


@dataclass
class Candidate:
    """Application inconnue observée pour déterminer si c'est un jeu."""

    process_name: str
    exe_path: str
    deadline: float
    pid: int = 0


@dataclass
class ActiveRoute:
    """Routage confirmé et toujours en cours."""

    process_name: str
    label: str
    channel: str
    pid: int = 0
    since: float = field(default_factory=time.time)


class ProcessMonitor:
    """Thread de fond qui détecte les lancements de jeux et route l'audio."""

    def __init__(
        self,
        config: AppConfig,
        backend_factory: Callable[[], AudioBackend],
        logger: EventLogger,
        on_routed: RoutedCallback | None = None,
        on_game_candidate: CandidateCallback | None = None,
        on_state_changed: StateCallback | None = None,
    ) -> None:
        self._config = config
        self._backend_factory = backend_factory
        self._logger = logger
        self._on_routed = on_routed
        self._on_game_candidate = on_game_candidate
        self._on_state_changed = on_state_changed

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()  # set = en pause

        self._lock = threading.Lock()
        self._known_pids: set[int] = set()
        # PID -> nom de processus normalisé, pour savoir quels noms tournent
        # encore sans avoir à réinterroger le système à chaque tick.
        self._pid_names: dict[int, str] = {}
        # Les trois tables suivantes sont indexées par NOM de processus, et
        # non par PID : `/SetAppDefault` s'applique à un exécutable, pas à une
        # instance. Un navigateur ou un jeu qui lance dix-huit processus du
        # même nom ne doit déclencher qu'un seul routage, sinon chaque
        # lancement provoque autant de commandes, de logs et de notifications.
        self._pending: dict[str, PendingRoute] = {}
        self._candidates: dict[str, Candidate] = {}
        self._active: dict[str, ActiveRoute] = {}
        # Process déjà proposés à l'utilisateur pendant cette session : évite
        # de renotifier à chaque relance tant qu'il n'a pas tranché.
        self._proposed: set[str] = set()

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="WaveRouterMonitor")
        self._thread.start()
        self._logger.info("Surveillance démarrée.")

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop_event.set()
        self._thread.join(timeout=5)
        self._thread = None
        self._logger.info("Surveillance arrêtée.")

    def pause(self) -> None:
        self._pause_event.set()
        self._logger.info("Surveillance mise en pause.")
        self._notify_state()

    def resume(self) -> None:
        self._pause_event.clear()
        self._logger.info("Surveillance reprise.")
        self._notify_state()

    def toggle_pause(self) -> bool:
        """Bascule pause/reprise et retourne le nouvel état (True = en pause)."""
        if self.is_paused:
            self.resume()
        else:
            self.pause()
        return self.is_paused

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def _notify_state(self) -> None:
        if self._on_state_changed:
            try:
                self._on_state_changed()
            except Exception:
                pass  # Un abonné défaillant ne doit pas casser la surveillance

    def active_routes(self) -> list[ActiveRoute]:
        """Routages confirmés actuellement en vigueur (jeux encore ouverts)."""
        with self._lock:
            return list(self._active.values())

    def forget_candidate(self, process_name: str) -> None:
        """Cesse de reproposer ce process pendant la session en cours."""
        with self._lock:
            self._proposed.add(process_name.strip().lower())

    def request_route(self, process_name: str, label: str, channel: str) -> bool:
        """
        Route immédiatement un jeu ajouté ou modifié depuis l'interface alors
        qu'il tourne déjà.

        Le moteur ne réagit qu'aux processus nouvellement lancés : sans ce
        point d'entrée, un jeu ajouté en pleine partie (cas typique de la
        détection automatique) ne serait routé qu'à son prochain lancement.

        Retourne True si le processus tourne et qu'un routage a été engagé.
        Appel bloquant (SoundVolumeView est invoqué) : à lancer hors du
        thread de l'interface.
        """
        normalized = process_name.strip().lower()
        if not channel:
            return False
        with self._lock:
            pid = next(
                (p for p, n in self._pid_names.items() if n == normalized), None
            )
            # Un suivi antérieur (candidat, routage confirmé vers un ancien
            # canal) ne doit pas bloquer la nouvelle demande.
            self._candidates.pop(normalized, None)
            self._active.pop(normalized, None)
        if pid is None:
            # Le moteur peut ne pas encore connaître ce process (surveillance
            # en pause, premier scan non effectué) : vérification directe.
            pid = self._find_running_pid(normalized)
        if pid is None:
            return False
        self._enqueue_route(
            pid, process_name, normalized, label, channel, time.monotonic()
        )
        return True

    @staticmethod
    def _find_running_pid(normalized: str) -> int | None:
        for proc in psutil.process_iter(["name"]):
            try:
                if (proc.info.get("name") or "").strip().lower() == normalized:
                    return proc.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def forget_process(self, process_name: str) -> None:
        """Abandonne le suivi d'un process (jeu supprimé ou désactivé)."""
        normalized = process_name.strip().lower()
        with self._lock:
            self._pending.pop(normalized, None)
            self._active.pop(normalized, None)

    # ------------------------------------------------------------------
    # Boucle principale
    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.is_set():
            interval = max(0.5, float(self._config.settings.poll_interval))
            if not self._pause_event.is_set():
                try:
                    self._tick()
                except Exception as exc:  # ne jamais laisser le thread mourir silencieusement
                    self._logger.error(f"Erreur pendant le scan des processus : {exc}")
            self._stop_event.wait(interval)

    def _tick(self) -> None:
        current_pids = set(psutil.pids())

        with self._lock:
            new_pids = current_pids - self._known_pids
            gone_pids = self._known_pids - current_pids
            first_scan = not self._known_pids
            self._known_pids = current_pids
            for pid in gone_pids:
                self._pid_names.pop(pid, None)

        if new_pids:
            self._handle_new_processes(new_pids, first_scan)
        if gone_pids:
            self._forget_stopped_processes()

        self._process_pending()

    def _forget_stopped_processes(self) -> None:
        """
        Retire les entrées dont plus aucune instance ne tourne.

        Le suivi porte sur le nom de l'exécutable : tant qu'une seule instance
        subsiste, le routage reste valable et ne doit pas être réappliqué.
        """
        closed: list[ActiveRoute] = []
        with self._lock:
            running = set(self._pid_names.values())
            for table in (self._pending, self._candidates):
                for name in [n for n in table if n not in running]:
                    table.pop(name, None)
            for name in [n for n in self._active if n not in running]:
                closed.append(self._active.pop(name))
        for route in closed:
            self._logger.debug_log(
                f"{route.process_name} fermé, routage vers {route.channel} libéré."
            )

    def _handle_new_processes(self, new_pids: set[int], first_scan: bool) -> None:
        settings = self._config.settings
        # Copie défensive : la liste des jeux est modifiée depuis le thread de
        # l'interface pendant que ce thread la parcourt.
        games = list(self._config.games)
        games_by_process = {
            game.normalized_process_name(): game for game in games if game.enabled
        }

        now = time.monotonic()
        for pid in new_pids:
            try:
                proc = psutil.Process(pid)
                name = (proc.name() or "").strip()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue  # processus déjà mort ou système protégé
            if not name:
                continue

            normalized = name.lower()
            with self._lock:
                self._pid_names[pid] = normalized
                deja_traite = (
                    normalized in self._pending
                    or normalized in self._active
                    or normalized in self._candidates
                )
            if deja_traite:
                continue  # une autre instance du même exécutable est déjà suivie

            game = games_by_process.get(normalized)
            if game:
                self._enqueue_route(pid, name, normalized, game.label, game.channel, now)
                continue

            if settings.auto_detect_games and not self._config.is_ignored(normalized):
                self._observe_candidate(pid, proc, name, normalized, now)

        if first_scan:
            self._logger.debug_log(
                f"Scan initial : {len(new_pids)} processus déjà actifs analysés."
            )

    def _enqueue_route(
        self, pid: int, process_name: str, normalized: str, label: str, channel: str, now: float
    ) -> None:
        if not channel:
            self._logger.error(
                f"Impossible de router '{label}' : aucun canal configuré."
            )
            return
        deadline = now + max(0.0, float(self._config.settings.routing_confirm_seconds))
        with self._lock:
            self._pending[normalized] = PendingRoute(
                process_name=process_name,
                label=label,
                channel=channel,
                deadline=deadline,
                pid=pid,
            )
        self._logger.info(f"{process_name} détecté (PID {pid}), routage vers {channel}...")
        # Application immédiate : plus la préférence est posée tôt, plus elle a
        # de chances de précéder l'ouverture du flux audio par le jeu.
        self._apply_routing(process_name, channel, label)

    def _observe_candidate(
        self, pid: int, proc: psutil.Process, name: str, normalized: str, now: float
    ) -> None:
        from waverouter.window_processes import is_system_process

        if is_system_process(normalized):
            return
        with self._lock:
            if normalized in self._proposed:
                return
        try:
            exe_path = proc.exe()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            exe_path = ""
        with self._lock:
            self._candidates[normalized] = Candidate(
                process_name=name,
                exe_path=exe_path,
                deadline=now + _CANDIDATE_OBSERVE_SECONDS,
                pid=pid,
            )

    def _apply_routing(self, process_name: str, channel: str, label: str) -> bool:
        """Applique la préférence de sortie. Retourne False en cas d'échec."""
        backend = self._backend_factory()
        if not backend.is_available():
            self._logger.error(
                f"Impossible de router '{label}' : SoundVolumeView.exe introuvable."
            )
            return False
        try:
            backend.set_app_default_device(channel, process_name)
            return True
        except SoundVolumeViewError as exc:
            self._logger.error(f"Échec du routage de '{label}' : {exc}")
        except Exception as exc:
            self._logger.error(f"Échec inattendu du routage de '{label}' : {exc}")
        return False

    # ------------------------------------------------------------------
    # Confirmation des routages et observation des candidats
    # ------------------------------------------------------------------
    def _process_pending(self) -> None:
        with self._lock:
            pending = list(self._pending.values())
            candidates = list(self._candidates.values())
        if not pending and not candidates:
            return  # aucun appel à SoundVolumeView : le tick reste gratuit

        sessions = self._read_sessions()
        if sessions is None:
            return  # backend indisponible : on retentera au prochain tick

        now = time.monotonic()
        for route in pending:
            self._confirm_route(route, sessions, now)
        for candidate in candidates:
            self._evaluate_candidate(candidate, sessions, now)

    def _read_sessions(self) -> list[AppSession] | None:
        backend = self._backend_factory()
        if not backend.is_available():
            return None
        try:
            return backend.list_app_sessions()
        except SoundVolumeViewError as exc:
            self._logger.debug_log(f"Lecture des sessions audio impossible : {exc}")
            return None

    @staticmethod
    def _find_sessions(sessions: list[AppSession], process_name: str) -> list[AppSession]:
        """
        Sessions audio de sortie ouvertes par cet exécutable, toutes
        instances confondues.

        Le PID n'entre volontairement pas en compte : la préférence posée par
        `/SetAppDefault` vaut pour l'exécutable entier, et un jeu peut très
        bien produire son son depuis un processus enfant du même nom que
        celui qui a été détecté.
        """
        target = process_name.strip().lower()
        return [s for s in sessions if s.process_name.strip().lower() == target]

    @staticmethod
    def _same_device(left: str, right: str) -> bool:
        return left.strip().casefold() == right.strip().casefold()

    def _confirm_route(
        self, route: PendingRoute, sessions: list[AppSession], now: float
    ) -> None:
        own = self._find_sessions(sessions, route.process_name)

        if own:
            route.session_seen = True
            if any(self._same_device(s.device_name, route.channel) for s in own):
                self._finalize_route(route)
                return
            # Le jeu sort ailleurs : on repose la préférence.
            route.attempts += 1
            actuels = ", ".join(sorted({s.device_name for s in own}))
            self._logger.debug_log(
                f"{route.process_name} sort sur '{actuels}' au lieu de "
                f"'{route.channel}', nouvelle tentative ({route.attempts})."
            )
            self._apply_routing(route.process_name, route.channel, route.label)

        if now < route.deadline:
            return

        # Fin du délai de confirmation.
        with self._lock:
            self._pending.pop(route.process_name.strip().lower(), None)
        if route.session_seen:
            self._logger.error(
                f"Routage de '{route.label}' non confirmé après "
                f"{self._config.settings.routing_confirm_seconds:.0f} s : le jeu "
                f"ne sort pas sur '{route.channel}'. Vérifiez que le canal existe "
                f"toujours dans Wave Link."
            )
        else:
            # Cas normal d'un jeu silencieux ou qui n'ouvre jamais de session :
            # la préférence est posée, elle s'appliquera dès qu'il jouera un son.
            self._logger.info(
                f"'{route.label}' n'a pas ouvert de session audio, la préférence "
                f"vers {route.channel} reste enregistrée."
            )
            self._register_active(route)

    def _finalize_route(self, route: PendingRoute) -> None:
        with self._lock:
            self._pending.pop(route.process_name.strip().lower(), None)
        self._register_active(route)
        self._logger.info(f"{route.process_name} → routé vers {route.channel} (confirmé).")
        if self._on_routed:
            try:
                self._on_routed(route.label, route.channel)
            except Exception as exc:
                self._logger.debug_log(f"Callback de routage en erreur : {exc}")

    def _register_active(self, route: PendingRoute) -> None:
        with self._lock:
            self._active[route.process_name.strip().lower()] = ActiveRoute(
                process_name=route.process_name,
                label=route.label,
                channel=route.channel,
                pid=route.pid,
            )

    def _evaluate_candidate(
        self, candidate: Candidate, sessions: list[AppSession], now: float
    ) -> None:
        from waverouter.window_processes import find_fullscreen_window_title

        normalized = candidate.process_name.strip().lower()
        expired = now >= candidate.deadline
        own = self._find_sessions(sessions, candidate.process_name)

        if not own:
            if expired:
                with self._lock:
                    self._candidates.pop(normalized, None)
            return  # pas (encore) de son : rien ne dit que c'est un jeu

        # Une application qui joue du son ET occupe tout l'écran est, en
        # pratique, un jeu : c'est ce couple qui distingue un jeu d'un
        # navigateur ou d'un lecteur de musique en fenêtre. La fenêtre est
        # cherchée sur les PID qui produisent effectivement du son, le
        # processus détecté au lancement n'étant pas toujours celui qui
        # l'affiche.
        title = None
        for pid in {s.pid for s in own if s.pid} | {candidate.pid}:
            title = find_fullscreen_window_title(pid)
            if title is not None:
                break
        if title is None:
            if expired:
                with self._lock:
                    self._candidates.pop(normalized, None)
            return

        with self._lock:
            self._candidates.pop(normalized, None)
            if normalized in self._proposed:
                return
            self._proposed.add(normalized)

        self._logger.info(f"Nouveau jeu potentiel détecté : {title} ({candidate.process_name})")
        if self._on_game_candidate:
            try:
                self._on_game_candidate(candidate.process_name, candidate.exe_path, title)
            except Exception as exc:
                self._logger.debug_log(f"Callback de détection en erreur : {exc}")

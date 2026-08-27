"""
Tests du backend SoundVolumeView.

Le point critique couvert ici : avant correction, un échec de
SoundVolumeView passait totalement inaperçu et l'application annonçait un
routage qui n'avait jamais eu lieu.
"""

from __future__ import annotations

import subprocess

import pytest

from waverouter.audio_backend import AudioBackend, SoundVolumeViewError


@pytest.fixture
def backend(tmp_path):
    exe = tmp_path / "SoundVolumeView.exe"
    exe.write_bytes(b"MZ")  # fichier factice : seule son existence compte
    return AudioBackend(str(exe))


def _fake_run(returncode: int = 0, stderr: bytes = b""):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, b"", stderr)

    return run


def test_backend_indisponible_sans_chemin():
    assert AudioBackend("").is_available() is False
    with pytest.raises(SoundVolumeViewError, match="introuvable"):
        AudioBackend("").set_app_default_device("Games!", "jeu.exe")


def test_code_retour_non_nul_leve_une_erreur(backend, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr=b"device not found"))
    with pytest.raises(SoundVolumeViewError, match="code 1"):
        backend.set_app_default_device("Canal inexistant", "jeu.exe")


def test_succes_silencieux(backend, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=0))
    backend.set_app_default_device("Games!", "jeu.exe")  # ne doit rien lever


def test_timeout_converti_en_erreur_metier(backend, monkeypatch):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SoundVolumeViewError, match="n'a pas répondu"):
        backend.set_app_default_device("Games!", "jeu.exe")


def test_erreur_systeme_convertie_en_erreur_metier(backend, monkeypatch):
    def run(cmd, **kwargs):
        raise OSError("accès refusé")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SoundVolumeViewError, match="Impossible de lancer"):
        backend.set_app_default_device("Games!", "jeu.exe")


def test_arguments_passes_a_soundvolumeview(backend, monkeypatch):
    captured = {}

    def run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    backend.set_app_default_device("Games!", "jeu.exe")
    assert captured["cmd"][1:] == ["/SetAppDefault", "Games!", "all", "jeu.exe"]


# ----------------------------------------------------------------------
# Lecture des sessions applicatives
# ----------------------------------------------------------------------
# Structure relevée sur une installation Wave Link réelle. Deux pièges y
# sont reproduits fidèlement, car ce sont eux qui rendaient la confirmation
# de routage inopérante :
#   - `Name` d'une application est son nom commercial, pas son exécutable ;
#   - `Device Name` est la carte son, identique pour tous les canaux Wave
#     Link, donc incapable de distinguer "Games!" de "Music".
_GAMES_ID = "{0.0.0.00000000}.{92b344bd-e19f-487f-8240-843fe9880f0e}"
_MUSIC_ID = "{0.0.0.00000000}.{e5542c6f-b384-47b2-be52-e4573ace1436}"

_CSV = (
    "Name,Type,Direction,Device Name,Item ID,Process Path,Process ID\n"
    f"Games!,Device,Render,Elgato Virtual Audio,{_GAMES_ID},,\n"
    f"Music,Device,Render,Elgato Virtual Audio,{_MUSIC_ID},,\n"
    "Micro,Device,Capture,Realtek,{0.0.1.0}.{aaa},,\n"
    f"Mon Super Jeu,Application,Render,Elgato Virtual Audio,{_GAMES_ID}|x%b4242,"
    "C:\\Jeux\\jeu.exe,4242\n"
    f"Brave Browser,Application,Render,Elgato Virtual Audio,{_MUSIC_ID}|x%b99,"
    "C:\\Program Files\\Brave\\brave.exe,99\n"
    f"Sons système,Application,Render,Elgato Virtual Audio,{_GAMES_ID}|sys,,\n"
    f"Mon Super Jeu,Application,Capture,Realtek,{{0.0.1.0}}.{{aaa}}|x,"
    "C:\\Jeux\\jeu.exe,4242\n"
)


@pytest.fixture
def backend_avec_sessions(backend, monkeypatch):
    def fake_list_devices(self):
        import csv
        import io

        return list(csv.DictReader(io.StringIO(_CSV)))

    monkeypatch.setattr(AudioBackend, "list_devices", fake_list_devices)
    return backend


def test_nom_de_process_extrait_du_chemin(backend_avec_sessions):
    """La colonne Name vaut « Mon Super Jeu » : seul le chemin donne jeu.exe."""
    sessions = backend_avec_sessions.list_app_sessions()
    assert {s.process_name for s in sessions} == {"jeu.exe", "brave.exe"}


def test_canal_resolu_via_item_id(backend_avec_sessions):
    """
    Les deux applications partagent le même « Device Name » : sans passer par
    l'Item ID, impossible de savoir laquelle sort sur Games! et laquelle sur
    Music.
    """
    par_process = {s.process_name: s.device_name for s in backend_avec_sessions.list_app_sessions()}
    assert par_process == {"jeu.exe": "Games!", "brave.exe": "Music"}


def test_sessions_de_capture_ignorees(backend_avec_sessions):
    assert all(s.device_name in ("Games!", "Music") for s in backend_avec_sessions.list_app_sessions())


def test_sons_systeme_sans_process_ignores(backend_avec_sessions):
    assert len(backend_avec_sessions.list_app_sessions()) == 2


def test_find_app_sessions_par_pid(backend_avec_sessions):
    sessions = backend_avec_sessions.find_app_sessions("jeu.exe", pid=4242)
    assert [s.device_name for s in sessions] == ["Games!"]


def test_find_app_sessions_retombe_sur_le_nom_si_pid_inconnu(backend_avec_sessions):
    # SoundVolumeView ne renseigne pas toujours le PID : on ne doit pas
    # perdre la session pour autant.
    sessions = backend_avec_sessions.find_app_sessions("jeu.exe", pid=1)
    assert [s.device_name for s in sessions] == ["Games!"]


def test_find_app_sessions_absente(backend_avec_sessions):
    assert backend_avec_sessions.find_app_sessions("inexistant.exe") == []


def test_export_manquant_leve_une_erreur(backend, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=0))
    with pytest.raises(SoundVolumeViewError, match="pas produit de fichier"):
        backend.list_devices()

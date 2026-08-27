"""
Tests du démarrage automatique Windows.

Le registre n'est jamais touché : `registered_command` est simulée. Le cas
couvert ici s'est réellement produit, le dossier du projet ayant été renommé
alors qu'une entrée de démarrage existait déjà.
"""

from __future__ import annotations

import sys

from waverouter import autostart


def test_aucune_entree(monkeypatch):
    monkeypatch.setattr(autostart, "registered_command", lambda: None)
    assert autostart.is_enabled() is False
    assert autostart.is_stale() is False


def test_entree_a_jour(monkeypatch):
    monkeypatch.setattr(
        autostart, "registered_command", autostart._get_executable_command
    )
    assert autostart.is_enabled() is True
    assert autostart.is_stale() is False


def test_entree_obsolete_apres_renommage(monkeypatch):
    """Le dossier a été renommé : la clé existe mais ne lance plus rien."""
    monkeypatch.setattr(
        autostart,
        "registered_command",
        lambda: '"C:\\Ancien\\ReparAudio\\.venv\\Scripts\\python.exe" "main.py"',
    )
    assert autostart.is_enabled() is True  # la clé est bien là...
    assert autostart.is_stale() is True  # ...mais elle est périmée


def test_commande_utilise_un_chemin_absolu(monkeypatch):
    """
    Le registre lance la commande depuis un répertoire courant arbitraire :
    un argv[0] relatif y serait introuvable.
    """
    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    commande = autostart._get_executable_command()
    assert "main.py" in commande
    assert commande.count('"') == 4  # exécutable et script, chacun entre guillemets
    script = commande.split('" "')[1].rstrip('"')
    assert script != "main.py"  # rendu absolu
    assert "--minimized" in autostart._get_executable_command()


def test_commande_en_executable_packagé(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\WaveRouter.exe")
    commande = autostart._get_executable_command()
    assert commande == '"C:\\Apps\\WaveRouter.exe" --minimized'

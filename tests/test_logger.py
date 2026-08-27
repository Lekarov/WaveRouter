"""
Tests du logger.

La rotation compte : l'application tourne en continu au démarrage de
Windows, et le fichier de log grossissait auparavant sans aucune limite.
"""

from __future__ import annotations

from waverouter import logger as logger_module
from waverouter.logger import EventLogger


def test_ecriture_et_relecture(config_dir):
    log = EventLogger()
    log.info("Premier événement")
    log.error("Deuxième événement")

    lignes = log.read_recent_lines()
    assert any("Premier événement" in l for l in lignes)
    assert any("Deuxième événement" in l for l in lignes)


def test_debug_muet_quand_desactive(config_dir):
    log = EventLogger(debug=False)
    log.debug_log("invisible")
    assert log.read_recent_lines() == []

    log.debug = True
    log.debug_log("visible")
    assert any("visible" in l for l in log.read_recent_lines())


def test_callbacks_recoivent_les_lignes(config_dir):
    recu: list[str] = []
    log = EventLogger()
    log.add_callback(recu.append)
    log.info("bonjour")

    assert len(recu) == 1
    assert "bonjour" in recu[0]


def test_callback_defaillant_nempeche_pas_les_autres(config_dir):
    recu: list[str] = []
    log = EventLogger()
    log.add_callback(lambda _line: 1 / 0)
    log.add_callback(recu.append)
    log.info("toujours livré")

    assert len(recu) == 1


def test_rotation_du_fichier(config_dir, monkeypatch):
    monkeypatch.setattr(logger_module, "MAX_LOG_BYTES", 200)
    log = EventLogger()
    for i in range(60):
        log.info(f"ligne de remplissage numéro {i}")

    backup = log.log_file.with_suffix(log.log_file.suffix + ".1")
    assert backup.exists()
    assert log.log_file.stat().st_size < 5000  # le fichier courant est reparti à zéro


def test_relecture_sans_fichier(config_dir):
    log = EventLogger()
    assert log.read_recent_lines() == []


def test_relecture_limitee_au_nombre_demande(config_dir):
    log = EventLogger()
    for i in range(50):
        log.info(f"événement {i}")

    assert len(log.read_recent_lines(count=10)) == 10

"""Tests de la configuration : chargement tolérant, migration, sauvegarde."""

from __future__ import annotations

import json

from waverouter.config import AppConfig, ConfigManager, GameEntry, Settings, get_config_path


def test_config_vide_par_defaut(config_dir):
    config = ConfigManager().config
    assert config.games == []
    assert config.settings.poll_interval == 1.0
    assert config.settings.auto_detect_games is True


def test_migration_ancienne_config(config_dir):
    """Une config écrite par une version antérieure doit rester exploitable."""
    ancienne = {
        "games": [
            {"label": "Hunt", "process_name": "HuntGame.exe", "channel": "Games!"}
        ],
        "settings": {"soundvolumeview_path": "C:/svv.exe", "poll_interval": 3.0},
    }
    path = get_config_path()
    path.write_text(json.dumps(ancienne), encoding="utf-8")

    config = ConfigManager().config
    assert len(config.games) == 1
    assert config.games[0].enabled is True  # champ absent, valeur par défaut
    assert config.settings.default_channel == ""
    assert config.ignored_processes == []
    # L'intervalle hérité de l'ancien moteur est ramené à la nouvelle valeur.
    assert config.settings.poll_interval == 1.0
    assert config.version == 2


def test_intervalle_personnalise_preserve_a_la_migration(config_dir):
    """Seule l'ancienne valeur par défaut est migrée, pas un choix explicite."""
    get_config_path().write_text(
        json.dumps({"settings": {"poll_interval": 10.0}}), encoding="utf-8"
    )
    assert ConfigManager().config.settings.poll_interval == 10.0


def test_pas_de_seconde_migration(config_dir):
    """Une config déjà migrée qui repasse à 3 s doit garder ce choix."""
    get_config_path().write_text(
        json.dumps({"version": 2, "settings": {"poll_interval": 3.0}}), encoding="utf-8"
    )
    assert ConfigManager().config.settings.poll_interval == 3.0


def test_config_corrompue_ne_plante_pas(config_dir):
    get_config_path().write_text("{ ceci n'est pas du json", encoding="utf-8")
    assert ConfigManager().config.games == []


def test_config_liste_au_lieu_dun_objet(config_dir):
    get_config_path().write_text("[1, 2, 3]", encoding="utf-8")
    assert ConfigManager().config.games == []


def test_valeurs_invalides_retombent_sur_les_defauts():
    config = AppConfig.from_dict(
        {"settings": {"poll_interval": "beaucoup", "routing_confirm_seconds": None}}
    )
    assert config.settings.poll_interval == Settings().poll_interval
    assert config.settings.routing_confirm_seconds == Settings().routing_confirm_seconds


def test_poll_interval_borne_au_minimum():
    config = AppConfig.from_dict({"settings": {"poll_interval": 0.01}})
    assert config.settings.poll_interval == 0.5


def test_jeu_sans_process_name_est_ignore():
    config = AppConfig.from_dict(
        {"games": [{"label": "Vide", "channel": "Games!"}, "pas un dict"]}
    )
    assert config.games == []


def test_sauvegarde_puis_rechargement(config_dir):
    manager = ConfigManager()
    manager.config.games.append(
        GameEntry(label="Hunt", process_name="HuntGame.exe", channel="Games!")
    )
    manager.config.settings.default_channel = "Games!"
    manager.config.ignore_process("Chrome.exe")
    manager.save()

    recharge = ConfigManager().config
    assert recharge.games[0].process_name == "HuntGame.exe"
    assert recharge.settings.default_channel == "Games!"
    assert recharge.ignored_processes == ["chrome.exe"]  # normalisé en minuscules


def test_find_game_insensible_a_la_casse():
    config = AppConfig(
        games=[GameEntry(label="Hunt", process_name="HuntGame.exe", channel="Games!")]
    )
    assert config.find_game("huntgame.exe") is not None
    assert config.find_game("  HUNTGAME.EXE  ") is not None
    assert config.find_game("autre.exe") is None


def test_dossiers_de_jeux_persistes(config_dir):
    manager = ConfigManager()
    assert manager.config.add_game_folder("D:\\Mes Jeux") is True
    assert manager.config.add_game_folder("D:\\Mes Jeux\\") is False  # doublon
    assert manager.config.add_game_folder("   ") is False
    manager.save()

    assert ConfigManager().config.game_folders == ["D:\\Mes Jeux"]


def test_ignore_process_sans_doublon():
    config = AppConfig()
    config.ignore_process("Chrome.exe")
    config.ignore_process("chrome.exe")
    assert config.ignored_processes == ["chrome.exe"]
    assert config.is_ignored("CHROME.EXE") is True

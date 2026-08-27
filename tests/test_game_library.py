"""
Tests de la découverte des jeux installés.

Le choix de l'exécutable est le point sensible : viser le lanceur au lieu du
binaire réel produit un routage qui ne s'applique jamais, puisque ce n'est
pas le lanceur qui ouvre la session audio.
"""

from __future__ import annotations

import json

from waverouter import game_library
from waverouter.game_library import (
    InstalledGame,
    pick_main_executable,
    scan_epic_games,
    scan_folder,
    scan_installed_games,
    scan_steam_games,
)


def ecrire_exe(path, taille: int = 1024) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * taille)


# ----------------------------------------------------------------------
# Choix de l'exécutable principal
# ----------------------------------------------------------------------
def test_binaire_unreal_prefere_au_lanceur(tmp_path):
    """Un jeu Unreal doit être surveillé sur son binaire -Shipping."""
    ecrire_exe(tmp_path / "MonJeu.exe", 5_000_000)  # lanceur, plus gros
    ecrire_exe(tmp_path / "Binaries" / "Win64" / "MonJeu-Win64-Shipping.exe", 1000)

    choisi = pick_main_executable(str(tmp_path), "Mon Jeu")

    assert choisi.endswith("MonJeu-Win64-Shipping.exe")


def test_correspondance_par_nom_de_jeu(tmp_path):
    ecrire_exe(tmp_path / "outil.exe", 9_000_000)
    ecrire_exe(tmp_path / "MonJeu.exe", 1000)

    assert pick_main_executable(str(tmp_path), "Mon Jeu").endswith("MonJeu.exe")


def test_correspondance_par_nom_de_dossier(tmp_path):
    dossier = tmp_path / "HuntGame"
    ecrire_exe(dossier / "petit.exe", 100)
    ecrire_exe(dossier / "HuntGame.exe", 200)

    assert pick_main_executable(str(dossier)).endswith("HuntGame.exe")


def test_plus_gros_executable_en_dernier_recours(tmp_path):
    ecrire_exe(tmp_path / "petit.exe", 100)
    ecrire_exe(tmp_path / "gros.exe", 900_000)

    assert pick_main_executable(str(tmp_path), "Sans rapport").endswith("gros.exe")


def test_variante_suffixee_ecartee(tmp_path):
    """
    Cas réel « Anno 117 » : deux binaires de taille quasi identique, dont une
    variante suffixée. La taille ne départage pas, le nom le plus court si.
    """
    ecrire_exe(tmp_path / "Anno117_plus.exe", 381_000)
    ecrire_exe(tmp_path / "Anno117.exe", 366_000)

    choisi = pick_main_executable(str(tmp_path), "Anno 117 - Pax Romana")

    assert choisi.endswith("Anno117.exe")


def test_lanceur_bien_plus_petit_reste_ecarte(tmp_path):
    """
    Cas réel « Hunt: Showdown 1896 » : hunt.exe n'est qu'un lanceur de 3,8 Mo
    devant HuntGame.exe de 53,5 Mo. Un nom plus court ne doit pas l'emporter
    quand l'écart de taille est d'un ordre de grandeur.
    """
    ecrire_exe(tmp_path / "hunt.exe", 3_800_000)
    ecrire_exe(tmp_path / "bin" / "HuntGame.exe", 53_500_000)

    choisi = pick_main_executable(str(tmp_path), "Hunt: Showdown 1896")

    assert choisi.endswith("HuntGame.exe")


def test_bootstrapper_ecarte_malgre_sa_taille(tmp_path):
    """
    Cas réel « Tears of Metal » : l'amorceur Epic Online Services pèse 2,5 Mo
    contre 0,6 Mo pour le jeu, et gagnerait donc par la taille.
    """
    ecrire_exe(tmp_path / "EOSBootstrapper.exe", 2_500_000)
    ecrire_exe(tmp_path / "UnityCrashHandler64.exe", 1_500_000)
    ecrire_exe(tmp_path / "ToM.exe", 600_000)

    assert pick_main_executable(str(tmp_path), "Tears of Metal").endswith("ToM.exe")


def test_utilitaires_exclus(tmp_path):
    ecrire_exe(tmp_path / "unins000.exe", 9_000_000)
    ecrire_exe(tmp_path / "vcredist_x64.exe", 8_000_000)
    ecrire_exe(tmp_path / "EasyAntiCheat_Setup.exe", 7_000_000)
    ecrire_exe(tmp_path / "jeu.exe", 1000)

    assert pick_main_executable(str(tmp_path)).endswith("jeu.exe")


def test_dossiers_de_redistribuables_ignores(tmp_path):
    ecrire_exe(tmp_path / "_CommonRedist" / "enorme.exe", 9_000_000)
    ecrire_exe(tmp_path / "jeu.exe", 1000)

    assert pick_main_executable(str(tmp_path)).endswith("jeu.exe")


def test_lanceur_ecarte_au_profit_du_jeu(tmp_path):
    ecrire_exe(tmp_path / "MonJeuLauncher.exe", 9_000_000)
    ecrire_exe(tmp_path / "MonJeu.exe", 1000)

    assert pick_main_executable(str(tmp_path), "Mon Jeu").endswith("MonJeu.exe")


def test_noms_generiques_ecartes(tmp_path):
    ecrire_exe(tmp_path / "start.exe", 9_000_000)
    ecrire_exe(tmp_path / "config.exe", 8_000_000)
    ecrire_exe(tmp_path / "MonJeu.exe", 1000)

    assert pick_main_executable(str(tmp_path)).endswith("MonJeu.exe")


def test_nom_de_jeu_contenant_un_mot_generique_conserve(tmp_path):
    """« start » ne doit pas faire disparaître Starcraft."""
    ecrire_exe(tmp_path / "Starcraft.exe", 5000)

    assert pick_main_executable(str(tmp_path), "Starcraft").endswith("Starcraft.exe")


def test_repli_si_tout_est_exclu(tmp_path):
    """Mieux vaut proposer le lanceur que de perdre le jeu."""
    ecrire_exe(tmp_path / "GameLauncher.exe", 5000)

    assert pick_main_executable(str(tmp_path)).endswith("GameLauncher.exe")


def test_dossier_sans_executable(tmp_path):
    (tmp_path / "data").mkdir()
    assert pick_main_executable(str(tmp_path)) == ""


def test_dossier_inexistant():
    assert pick_main_executable("Z:/nexiste/pas") == ""


# ----------------------------------------------------------------------
# Steam
# ----------------------------------------------------------------------
def test_scan_steam(tmp_path, monkeypatch):
    steam = tmp_path / "Steam"
    steamapps = steam / "steamapps"
    steamapps.mkdir(parents=True)

    (steamapps / "appmanifest_594650.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"594650"\n'
        '\t"name"\t\t"Hunt Showdown"\n'
        '\t"installdir"\t\t"Hunt Showdown"\n}\n',
        encoding="utf-8",
    )
    ecrire_exe(steamapps / "common" / "Hunt Showdown" / "HuntGame.exe", 5000)

    monkeypatch.setattr(game_library, "find_steam_path", lambda: str(steam))
    jeux = scan_steam_games()

    assert len(jeux) == 1
    assert jeux[0].name == "Hunt Showdown"
    assert jeux[0].source == "Steam"
    assert jeux[0].process_name == "HuntGame.exe"


def test_scan_steam_ignore_les_jeux_non_installes(tmp_path, monkeypatch):
    """Un manifeste sans dossier sur le disque ne doit rien produire."""
    steam = tmp_path / "Steam"
    steamapps = steam / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "appmanifest_1.acf").write_text(
        '"AppState"\n{\n\t"name"\t\t"Fantome"\n\t"installdir"\t\t"Fantome"\n}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(game_library, "find_steam_path", lambda: str(steam))
    assert scan_steam_games() == []


def test_scan_steam_bibliotheques_secondaires(tmp_path, monkeypatch):
    """Les jeux installés sur un second disque doivent être trouvés aussi."""
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    autre = tmp_path / "D_Jeux"
    (autre / "steamapps").mkdir(parents=True)

    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
        + str(autre).replace("\\", "\\\\")
        + '"\n\t}\n}\n',
        encoding="utf-8",
    )
    (autre / "steamapps" / "appmanifest_2.acf").write_text(
        '"AppState"\n{\n\t"name"\t\t"Jeu Distant"\n\t"installdir"\t\t"JeuDistant"\n}\n',
        encoding="utf-8",
    )
    ecrire_exe(autre / "steamapps" / "common" / "JeuDistant" / "JeuDistant.exe", 5000)

    monkeypatch.setattr(game_library, "find_steam_path", lambda: str(steam))
    jeux = scan_steam_games()

    assert [j.name for j in jeux] == ["Jeu Distant"]


def test_scan_steam_sans_installation(monkeypatch):
    monkeypatch.setattr(game_library, "find_steam_path", lambda: "")
    assert scan_steam_games() == []


# ----------------------------------------------------------------------
# Epic Games
# ----------------------------------------------------------------------
def test_scan_epic(tmp_path, monkeypatch):
    manifests = tmp_path / "Manifests"
    manifests.mkdir()
    install = tmp_path / "Games" / "MonJeuEpic"
    ecrire_exe(install / "MonJeuEpic.exe", 4000)

    (manifests / "abc.item").write_text(
        json.dumps(
            {
                "DisplayName": "Mon Jeu Epic",
                "InstallLocation": str(install),
                "LaunchExecutable": "MonJeuEpic.exe",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(game_library, "EPIC_MANIFESTS_DIR", str(manifests))
    jeux = scan_epic_games()

    assert len(jeux) == 1
    assert jeux[0].name == "Mon Jeu Epic"
    assert jeux[0].process_name == "MonJeuEpic.exe"


def test_scan_epic_manifeste_illisible(tmp_path, monkeypatch):
    """Un manifeste corrompu ne doit pas faire échouer tout le balayage."""
    manifests = tmp_path / "Manifests"
    manifests.mkdir()
    (manifests / "casse.item").write_text("{ pas du json", encoding="utf-8")

    install = tmp_path / "Games" / "Bon"
    ecrire_exe(install / "Bon.exe", 4000)
    (manifests / "bon.item").write_text(
        json.dumps({"DisplayName": "Bon", "InstallLocation": str(install)}),
        encoding="utf-8",
    )

    monkeypatch.setattr(game_library, "EPIC_MANIFESTS_DIR", str(manifests))
    assert [j.name for j in scan_epic_games()] == ["Bon"]


def test_scan_epic_sans_dossier(tmp_path, monkeypatch):
    monkeypatch.setattr(game_library, "EPIC_MANIFESTS_DIR", str(tmp_path / "absent"))
    assert scan_epic_games() == []


# ----------------------------------------------------------------------
# Dossier personnalisé
# ----------------------------------------------------------------------
def test_scan_dossier_un_sous_dossier_par_jeu(tmp_path):
    ecrire_exe(tmp_path / "Jeu Alpha" / "Alpha.exe", 5000)
    ecrire_exe(tmp_path / "Jeu Beta" / "Binaries" / "Beta-Win64-Shipping.exe", 5000)
    ecrire_exe(tmp_path / "Jeu Beta" / "BetaLauncher.exe", 9_000_000)

    jeux = scan_folder(str(tmp_path))

    assert [j.name for j in jeux] == ["Jeu Alpha", "Jeu Beta"]
    assert jeux[1].process_name == "Beta-Win64-Shipping.exe"  # pas le lanceur
    assert all(j.source == "Dossier" for j in jeux)


def test_scan_dossier_de_jeu_unique(tmp_path):
    """Un dossier pointant directement sur un jeu est traité comme tel."""
    jeu = tmp_path / "MonJeu"
    ecrire_exe(jeu / "MonJeu.exe", 5000)

    jeux = scan_folder(str(jeu))

    assert [j.name for j in jeux] == ["MonJeu"]


def test_scan_dossier_ignore_les_sous_dossiers_sans_exe(tmp_path):
    (tmp_path / "Sauvegardes").mkdir()
    ecrire_exe(tmp_path / "Jeu" / "Jeu.exe", 5000)

    assert [j.name for j in scan_folder(str(tmp_path))] == ["Jeu"]


def test_scan_dossier_inexistant():
    assert scan_folder("Z:/nexiste/pas") == []


def test_dossiers_personnalises_integres_au_scan_global(tmp_path, monkeypatch):
    monkeypatch.setattr(game_library, "scan_steam_games", lambda: [])
    monkeypatch.setattr(game_library, "scan_epic_games", lambda: [])
    monkeypatch.setattr(game_library, "scan_gog_games", lambda: [])
    ecrire_exe(tmp_path / "Jeu Portable" / "Portable.exe", 5000)

    jeux = scan_installed_games(extra_folders=[str(tmp_path)])

    assert [j.name for j in jeux] == ["Jeu Portable"]


def test_dossier_illisible_nempeche_pas_le_scan(monkeypatch):
    monkeypatch.setattr(game_library, "scan_steam_games", lambda: [])
    monkeypatch.setattr(game_library, "scan_epic_games", lambda: [])
    monkeypatch.setattr(game_library, "scan_gog_games", lambda: [])

    def explose(_folder):
        raise OSError("disque débranché")

    monkeypatch.setattr(game_library, "scan_folder", explose)
    assert scan_installed_games(extra_folders=["D:/absent"]) == []


# ----------------------------------------------------------------------
# Agrégation
# ----------------------------------------------------------------------
def test_scan_global_deduplique_et_trie(monkeypatch):
    monkeypatch.setattr(
        game_library,
        "scan_steam_games",
        lambda: [
            InstalledGame("Zelda", "Steam", "C:/jeux/zelda.exe"),
            InstalledGame("Alpha", "Steam", "C:/jeux/alpha.exe"),
        ],
    )
    monkeypatch.setattr(
        game_library,
        "scan_epic_games",
        lambda: [InstalledGame("Zelda (Epic)", "Epic Games", "C:/JEUX/ZELDA.EXE")],
    )
    monkeypatch.setattr(game_library, "scan_gog_games", lambda: [])

    jeux = scan_installed_games()

    assert [j.name for j in jeux] == ["Alpha", "Zelda"]  # doublon écarté, tri alphabétique


def test_scan_global_survit_a_un_scanner_defaillant(monkeypatch):
    def explose():
        raise RuntimeError("registre illisible")

    monkeypatch.setattr(game_library, "scan_steam_games", explose)
    monkeypatch.setattr(
        game_library, "scan_epic_games", lambda: [InstalledGame("Jeu", "Epic Games", "C:/j.exe")]
    )
    monkeypatch.setattr(game_library, "scan_gog_games", lambda: [])

    assert [j.name for j in scan_installed_games()] == ["Jeu"]

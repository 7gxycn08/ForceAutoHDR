import unittest

from library_scan import (
    epic_executable,
    gaming_root_folder,
    gog_entry,
    is_skipped_executable,
    manifest_install,
    parse_microsoft_game_config,
    rank_executables,
    steam_library_paths,
)


class LibraryScanTests(unittest.TestCase):
    def test_steam_library_and_manifest(self):
        libraries = steam_library_paths(
            '"libraryfolders" { "0" { "path" "D:\\\\SteamLibrary" } }'
        )
        self.assertEqual(libraries, [r"D:\SteamLibrary"])
        parsed = manifest_install(
            '"AppState" { "name" "My Game" "installdir" "MyGame" }'
        )
        self.assertEqual(parsed, ("My Game", "MyGame"))
        self.assertIsNone(
            manifest_install(
                '"AppState" { "name" "Redistributables" "installdir" "Steamworks Common Redistributables" }'
            )
        )

    def test_rank_prefers_the_named_executable(self):
        helper = r"D:\Game\crashhelper.exe"
        game = r"D:\Game\bin\MyGame.exe"
        ranked = rank_executables([helper, game], "My Game", {helper: 100, game: 5_000_000})
        self.assertEqual(ranked, [game])

    def test_store_manifests(self):
        name, path = epic_executable(
            {
                "DisplayName": "Fortnite",
                "InstallLocation": r"D:\Fortnite",
                "LaunchExecutable": r"FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe",
            }
        )
        self.assertEqual(name, "Fortnite")
        self.assertTrue(path.endswith("FortniteClient-Win64-Shipping.exe"))
        self.assertIsNone(epic_executable({"DisplayName": "Partial", "bIsIncompleteInstall": True}))

        gog_name, gog_path = gog_entry({"gameName": "Witcher", "path": r"D:\GOG\Witcher", "exe": "witcher3.exe"})
        self.assertEqual(gog_name, "Witcher")
        self.assertEqual(gog_path, r"D:\GOG\Witcher\witcher3.exe")

        xml = (
            "<Game><ExecutableList><Executable Name=\"game.exe\"/></ExecutableList>"
            '<ShellVisuals DefaultDisplayName="Halo"/></Game>'
        )
        xbox_name, xbox_path = parse_microsoft_game_config(xml, r"D:\XboxGames\Halo\Content")
        self.assertEqual(xbox_name, "Halo")
        self.assertEqual(xbox_path, r"D:\XboxGames\Halo\Content\game.exe")

    def test_gaming_root_and_launchers(self):
        folder = gaming_root_folder(r"E:\\", "XboxGames".encode("utf-16-le"))
        self.assertEqual(folder, r"E:\XboxGames")
        self.assertTrue(is_skipped_executable(r"C:\Steam\steam.exe"))
        self.assertFalse(is_skipped_executable(r"D:\Games\MyGame.exe"))


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from pathlib import Path

from registry_prefs import (
    APP_VERSION,
    APP_VERSION_TUPLE,
    GameEntry,
    apply_d3d_behaviors,
    apply_global_swap,
    auto_hdr_updates,
    exe_stem,
    is_managed_gpu_value,
    is_owned_d3d_behaviors,
    merge_preference_fields,
    normalize_exe_path,
    parse_profile,
    parse_strength,
    profile_document,
    strip_preference_fields,
    update_game_preference,
)


class PreferenceTests(unittest.TestCase):
    def test_merge_keeps_unrelated_gpu_settings(self):
        existing = "GpuPreference=2;SwapEffectUpgradeEnable=1;"
        merged = merge_preference_fields(existing, auto_hdr_updates(40))
        self.assertIn("GpuPreference=2", merged)
        self.assertIn("SwapEffectUpgradeEnable=1", merged)
        self.assertIn("AutoHDRStrength=40", merged)
        self.assertIn("AppStatus=1", merged)
        self.assertIn("AutoHDREnable=2097", merged)
        self.assertTrue(merged.endswith(";"))

    def test_merge_replaces_existing_auto_hdr_fields_once(self):
        existing = "AutoHDRStrength=10;GpuPreference=2;AutoHDRStrength=80;AutoHDREnable=1;"
        merged = merge_preference_fields(existing, auto_hdr_updates(55))
        self.assertEqual(merged.count("AutoHDRStrength="), 1)
        self.assertIn("AutoHDRStrength=55", merged)
        self.assertIn("AutoHDREnable=2097", merged)
        self.assertIn("GpuPreference=2", merged)
        self.assertNotIn("AutoHDREnable=1", merged)

    def test_strip_leaves_other_fields_and_drops_empty_values(self):
        existing = "GpuPreference=2;AutoHDRStrength=50;AppStatus=1;AutoHDREnable=2097;"
        stripped = strip_preference_fields(
            existing, ("AutoHDRStrength", "AppStatus", "AutoHDREnable")
        )
        self.assertEqual(stripped, "GpuPreference=2;")
        self.assertEqual(
            strip_preference_fields(
                "AutoHDRStrength=50;AppStatus=1;AutoHDREnable=2097;",
                ("AutoHDRStrength", "AppStatus", "AutoHDREnable"),
            ),
            "",
        )

    def test_strength_bounds(self):
        self.assertEqual(parse_strength("0"), 0)
        self.assertEqual(parse_strength("100"), 100)
        self.assertIsNone(parse_strength("101"))
        self.assertIsNone(parse_strength("nope"))
        with self.assertRaises(ValueError):
            auto_hdr_updates(101)
        with self.assertRaises(ValueError):
            auto_hdr_updates(True)

    def test_exe_stem_ignores_extension_case(self):
        self.assertEqual(exe_stem(r"D:\Games\Game.EXE"), "Game")
        self.assertEqual(exe_stem("My.Game.exe"), "My.Game")
        self.assertEqual(normalize_exe_path("D:/Games/Game.EXE"), r"D:\Games\Game.EXE")

    def test_managed_signatures(self):
        self.assertTrue(is_managed_gpu_value("AutoHDREnable=2097;GpuPreference=2;"))
        self.assertFalse(is_managed_gpu_value("GpuPreference=2;AutoHDREnable=1;"))
        self.assertTrue(is_owned_d3d_behaviors("BufferUpgradeOverride=1;BufferUpgradeEnable10Bit=1"))
        self.assertFalse(is_owned_d3d_behaviors("SomethingElse=1"))

    def test_update_can_keep_or_replace_gpu_fields(self):
        existing = "GpuPreference=2;SwapEffectUpgradeEnable=1;"
        kept = update_game_preference(existing, 40)
        self.assertIn("GpuPreference=2", kept)
        self.assertIn("SwapEffectUpgradeEnable=1", kept)
        self.assertIn("AutoHDRStrength=40", kept)
        cleared = update_game_preference(existing, 40, gpu_preference=None, swap_effect=None)
        self.assertNotIn("GpuPreference", cleared)
        self.assertNotIn("SwapEffectUpgradeEnable", cleared)
        forced = update_game_preference(existing, 10, gpu_preference=1, swap_effect=0)
        self.assertIn("GpuPreference=1", forced)
        self.assertIn("SwapEffectUpgradeEnable=0", forced)

    def test_ten_bit_toggle_preserves_other_behaviors(self):
        existing = "BufferUpgradeOverride=1;BufferUpgradeEnable10Bit=1;Custom=5"
        turned_off = apply_d3d_behaviors(existing, False)
        self.assertIn("BufferUpgradeOverride=1", turned_off)
        self.assertIn("Custom=5", turned_off)
        self.assertNotIn("BufferUpgradeEnable10Bit", turned_off)
        turned_on = apply_d3d_behaviors(turned_off, True)
        self.assertIn("BufferUpgradeEnable10Bit=1", turned_on)
        self.assertIn("Custom=5", turned_on)

    def test_global_swap_keeps_other_tokens(self):
        enabled = apply_global_swap("Other=1;", True)
        self.assertIn("Other=1", enabled)
        self.assertIn("SwapEffectUpgradeEnable=1", enabled)
        disabled = apply_global_swap(enabled, False)
        self.assertIn("Other=1", disabled)
        self.assertNotIn("SwapEffectUpgradeEnable", disabled)

    def test_profile_roundtrip(self):
        entry = GameEntry(r"Game", r"D:\Games\Game.exe", "Game.exe", 80, True, 2, 1, False)
        document = profile_document([entry, GameEntry("OnlyKey", None, "Only.exe", 10)], False)
        games, global_swap = parse_profile(document)
        self.assertFalse(global_swap)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["strength"], 80)
        self.assertEqual(games[0]["gpu_preference"], 2)
        self.assertEqual(games[0]["swap_effect"], 1)
        with self.assertRaises(ValueError):
            parse_profile({"version": 1, "games": [{"path": r"D:\Game.exe", "strength": 140}]})

    def test_version_files_match(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "file_version_info.txt").read_text(encoding="utf-8")
        self.assertIn(f"u'{APP_VERSION}'", text)
        needle = f"filevers={APP_VERSION_TUPLE}".replace(" ", "")
        self.assertIn(needle, text.replace(" ", ""))
        self.assertIn(f"prodvers={APP_VERSION_TUPLE}".replace(" ", ""), text.replace(" ", ""))
        title = (root / "ForceAutoHDR.py").read_text(encoding="utf-8")
        self.assertIn("APP_VERSION", title)
        self.assertIsNotNone(re.search(r"ForceAutoHDR v\{APP_VERSION\}", title))


if __name__ == "__main__":
    unittest.main()

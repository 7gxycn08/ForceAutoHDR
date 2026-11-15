![downloads](https://img.shields.io/github/downloads/7gxycn08/ForceAutoHDR/total?label=Github+Downloads)

# ForceAutoHDR

ForceAutoHDR simplifies the process of adding games to the AutoHDR list in the Windows Registry, enabling HDR for games not officially supported. This tool offers a user-friendly GUI for enabling AutoHDR in unsupported games.

## Features

- **Find the real executable**: Add a file, a shortcut, a running process, or a game found locally in Steam, Epic, GOG, or Xbox folders. Launchers and helpers are called out before they are saved.
- **See if this PC can use it**: The window shows whether you are on Windows 11, whether a display supports HDR, and whether HDR is currently on.
- **Per game**: HDR strength with mild, standard, and strong presets, optional 10-bit buffer upgrade, GPU preference, and flip-model override. Strength can be applied to every saved game.
- **Keeps your other GPU settings**: New fields are merged into the existing per-game value. Removing Auto HDR leaves GPU preference and the per-game flip setting in place.
- **Profiles and undo**: Export or import a JSON profile. The first change saves an initial backup, and Undo restores the registry areas to the state before the last change.
- **Safe**: Does not make any connections to the Internet. Unrelated Direct3D keys stay out of the list.
- **DXVK/VKD3D**: Works for games using Vulkan api wrappers.

![forcegui](https://github.com/7gxycn08/ForceAutoHDR/assets/121936658/8f62b984-d146-4b3e-a8ea-8ce99d834f91)

The window is a searchable table. Each row shows strength, 10-bit upgrade, GPU preference, flip model, and the full path. A missing file is marked so you can relink it. Drop an `.exe` or `.lnk` onto the window to add it.

The initial backup is written to `%LOCALAPPDATA%\ForceAutoHDR\initial-backup.json` before the first registry change.

## Usage

1. Ensure AutoHDR is enabled in Windows 11 settings.
2. In ForceAutoHDR, add the game executable itself, not a launcher. HDR strength is the Xbox Game Bar intensity slider, from 0 to 100.
3. Manually enable HDR by pressing `Win+Alt+B` in Windows 11.
4. Run your game. The path you saved should be the path the game actually launches with.
5. To verify AutoHDR is working, open the Xbox Game Bar, navigate to the HDR Intensity Slider, and adjust it. If the brightness shifts while adjusting the slider, AutoHDR is functioning.
6. For automatic HDR toggling for any process/game, consider using [PyAutoActions](https://github.com/7gxycn08/PyAutoActions/).
7. For permanently setting CPU Priority/IO Priority/Memory Priority via registry consider using [PrioritySetter](https://github.com/7gxycn08/PrioritySetter/).

## Windows 11 24H2 Overblown Colors Workaround

![24h2 (Github)](https://github.com/user-attachments/assets/bc7124fd-d27c-49a9-a988-e567629e83ee)

This workaround is for Unreal Engine games. Edit `Engine.ini`, usually in `%LOCALAPPDATA%\<GameFolder>\`.

The setting below selects the default back-buffer pixel format and uses 16-bit RGBA output.


```
[/Script/Engine.RendererSettings]
r.DefaultBackBufferPixelFormat=1
```

## Notice

AutoHDR is forced for unsupported games without notification popups.

## Getting Started

To start using ForceAutoHDR, download the latest release from our [Releases page](https://github.com/7gxycn08/ForceAutoHDR/releases). Install it using the setup file and run the application.

![winget](https://github.com/7gxycn08/ForceAutoHDR/assets/121936658/4dd2df30-da47-4dcd-9219-396709fa6f3b)


Alternatively you can install and update via [Windows Package Manager (Winget)](https://docs.microsoft.com/en-us/windows/package-manager/winget/):


`winget install ForceAutoHDR.7gxycn08`

To run this version from source:

```
pip install -r requirements.txt
python ForceAutoHDR.py
```

To build the windowed executable (UPX is disabled in the spec to reduce antivirus false positives):

```
pip install pyinstaller
pyinstaller ForceAutoHDR.spec
```

## Contributing

Contributions are welcome! If you have suggestions or want to improve ForceAutoHDR, please feel free to fork the repository, make changes, and submit a pull request. For major changes or discussions, please open an issue first.

Leave a Star if you like this project.

## License

ForceAutoHDR is released under the Apache License 2.0. See the [LICENSE](LICENSE) file for more details.

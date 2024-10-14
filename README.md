![downloads](https://img.shields.io/github/downloads/7gxycn08/ForceAutoHDR/total?label=Github+Downloads)

# ForceAutoHDR

ForceAutoHDR simplifies the process of adding games to the AutoHDR list in the Windows Registry, enabling HDR for games not officially supported. This tool offers a user-friendly GUI for enabling AutoHDR in unsupported games.

## Features

- **Easy to Use**: Add games to the AutoHDR list with a simple GUI.
- **Automatic Registry Management**: Automatically adds or removes game entries in the Registry.
- **Safe**: Does not make any connections to the Internet.
- **DXVK/VKD3D**: Works for games using Vulkan api wrappers.

![forcegui](https://github.com/7gxycn08/ForceAutoHDR/assets/121936658/8f62b984-d146-4b3e-a8ea-8ce99d834f91)

## Usage

1. Ensure AutoHDR is enabled in Windows 11 settings.
2. Manually enable HDR by pressing `Win+Alt+B` in Windows 11.
3. Run your game.
4. To verify AutoHDR is working, open the Xbox Game Bar, navigate to the HDR Intensity Slider, and adjust it. If the brightness shifts while adjusting the slider, AutoHDR is functioning.
5. For automatic HDR toggling for any process/game, consider using [PyAutoActions](https://github.com/7gxycn08/PyAutoActions/).

## Windows 11 24H2 Overblown Colors workaround

![24h2 (Github)](https://github.com/user-attachments/assets/bc7124fd-d27c-49a9-a988-e567629e83ee)

To fix games that exhibit such behavior edit 'Engine.ini' which usually are located in 'Appdata/local/(GameFolder)'.


Adding the variable bellow Defines the default back buffer pixel format and sets it to 16bit RGBA output.


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

## Contributing

Contributions are welcome! If you have suggestions or want to improve ForceAutoHDR, please feel free to fork the repository, make changes, and submit a pull request. For major changes or discussions, please open an issue first.

## License

ForceAutoHDR is released under the MIT License. See the [LICENSE](https://github.com/7gxycn08/ForceAutoHDR/blob/main/LICENSE) file for more details.

<div align="center">
  <h1>Pixel Fix</h1>
  <a href="https://github.com/nyaridev/pixel-fix/releases">
    <img src="https://img.shields.io/badge/version-1.0.0-black" alt="Version 1.0.0">
  </a>
</div>

Tool to batch-fix transparent pixel edges in sprites and images.

Pixel Fix fills fully transparent pixels with the nearest visible edge color while preserving transparency. This helps prevent dark or bright fringes around sprites, icons, and other cutout images when they are filtered, scaled, or rendered in-game.

## Features

- Batch process image folders
- Drag and drop images or folders
- Optional recursive folder scanning
- Multithreaded processing
- Minimal GUI
- Supports `.png`, `.webp`, `.bmp`, `.gif`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, and `.apng`

## Usage

Run the app:

```bat
run.bat
```

Choose a folder or drop images into the window, then click `Start`.

Pixel Fix writes changes directly to the selected image files, so keep a backup if you need the originals.

## Build

Create a Windows executable:

```bat
build.bat
```

The built app will be created at:

```text
dist/pixel-fix.exe
```

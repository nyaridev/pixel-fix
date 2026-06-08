from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw


ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def read_svg_path(svg_path: Path) -> str:
    svg = svg_path.read_text(encoding="utf-8")
    match = re.search(r"<path\b[^>]*\bd=\"([^\"]+)\"", svg)
    if match is None:
        raise ValueError(f"No SVG path found in {svg_path}")
    return match.group(1)


def parse_color(color: str) -> tuple[int, int, int, int]:
    normalized = color.strip().removeprefix("#")
    if len(normalized) != 6:
        raise ValueError("Icon color must be a 6-digit hex value, for example #ffffff")

    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
        255,
    )


def parse_path(path_data: str) -> list[list[tuple[float, float]]]:
    tokens = re.findall(r"[MmLlCcZz]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", path_data)
    subpaths: list[list[tuple[float, float]]] = []
    current: tuple[float, float] = (0.0, 0.0)
    start: tuple[float, float] = (0.0, 0.0)
    active: list[tuple[float, float]] = []
    command = ""
    index = 0

    def read_float() -> float:
        nonlocal index
        value = float(tokens[index])
        index += 1
        return value

    def cubic(
        p0: tuple[float, float],
        p1: tuple[float, float],
        p2: tuple[float, float],
        p3: tuple[float, float],
    ) -> list[tuple[float, float]]:
        points = []
        for step in range(1, 25):
            t = step / 24
            mt = 1 - t
            x = (
                mt**3 * p0[0]
                + 3 * mt**2 * t * p1[0]
                + 3 * mt * t**2 * p2[0]
                + t**3 * p3[0]
            )
            y = (
                mt**3 * p0[1]
                + 3 * mt**2 * t * p1[1]
                + 3 * mt * t**2 * p2[1]
                + t**3 * p3[1]
            )
            points.append((x, y))
        return points

    while index < len(tokens):
        if re.fullmatch(r"[MmLlCcZz]", tokens[index]):
            command = tokens[index]
            index += 1

        if command in {"M", "m"}:
            x, y = read_float(), read_float()
            if command == "m":
                x += current[0]
                y += current[1]
            if active:
                subpaths.append(active)
            current = start = (x, y)
            active = [current]
            command = "l" if command == "m" else "L"
        elif command in {"L", "l"}:
            x, y = read_float(), read_float()
            if command == "l":
                x += current[0]
                y += current[1]
            current = (x, y)
            active.append(current)
        elif command in {"C", "c"}:
            x1, y1 = read_float(), read_float()
            x2, y2 = read_float(), read_float()
            x, y = read_float(), read_float()
            if command == "c":
                p1 = (current[0] + x1, current[1] + y1)
                p2 = (current[0] + x2, current[1] + y2)
                p3 = (current[0] + x, current[1] + y)
            else:
                p1 = (x1, y1)
                p2 = (x2, y2)
                p3 = (x, y)
            active.extend(cubic(current, p1, p2, p3))
            current = p3
        elif command in {"Z", "z"}:
            active.append(start)
            subpaths.append(active)
            active = []
            current = start
            command = ""
        else:
            raise ValueError(f"Unsupported SVG path command: {command}")

    if active:
        subpaths.append(active)

    return subpaths


def render_svg_icon(
    path_data: str,
    size: int,
    color: tuple[int, int, int, int],
) -> Image.Image:
    scale_factor = 4
    canvas_size = size * scale_factor
    scale = canvas_size / 64
    image = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)

    for subpath in parse_path(path_data):
        points = [(x * scale, y * scale) for x, y in subpath]
        draw.polygon(points, fill=color)

    return image.resize((size, size), Image.Resampling.LANCZOS)


def build_ico(svg_path: Path | str, ico_path: Path | str, color: str = "#000000") -> None:
    svg_path = Path(svg_path)
    ico_path = Path(ico_path)

    if not svg_path.exists():
        raise FileNotFoundError(svg_path)

    path_data = read_svg_path(svg_path)
    rgba = parse_color(color)
    images = [render_svg_icon(path_data, size, rgba) for size in ICON_SIZES]
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    images[-1].save(
        ico_path,
        format="ICO",
        append_images=images[:-1],
        sizes=[(size, size) for size in ICON_SIZES],
    )


def main() -> None:
    if len(sys.argv) not in {3, 4}:
        raise SystemExit(
            "Usage: python app/build_icon.py <source.svg> <output.ico> [#rrggbb]"
        )

    color = sys.argv[3] if len(sys.argv) == 4 else "#000000"
    build_ico(Path(sys.argv[1]), Path(sys.argv[2]), color)


if __name__ == "__main__":
    main()

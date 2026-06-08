from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np
from PIL import Image

try:
    from scipy import ndimage
except ImportError:
    ndimage = None


IMAGE_EXTENSIONS = {
    ".apng",
    ".bmp",
    ".gif",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}

NEIGHBOR_LOCATIONS = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
)


class CancelEvent(Protocol):
    def is_set(self) -> bool: ...


class PixelFixCancelled(Exception):
    pass


@dataclass(frozen=True)
class FixResult:
    path: Path
    changed: bool
    message: str


def discover_images(directory: Path, recursive: bool = False) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []

    entries: Iterable[Path]
    entries = directory.rglob("*") if recursive else directory.iterdir()

    return sorted(
        (
            path
            for path in entries
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda path: str(path).lower(),
    )


def fix_image(
    path: Path, debug: bool = False, cancel_event: CancelEvent | None = None
) -> FixResult:
    _raise_if_cancelled(cancel_event)

    with Image.open(path) as source:
        image = source.convert("RGBA")

    pixels = np.array(image, dtype=np.uint8, copy=True)
    height, width = pixels.shape[:2]
    if width == 0 or height == 0:
        return FixResult(path, False, "Skipped empty image")

    alpha = pixels[:, :, 3]
    transparent_mask = alpha == 0
    if not transparent_mask.any():
        return FixResult(path, False, "No transparent pixels to fix")

    _raise_if_cancelled(cancel_event)
    edge_mask = _find_opaque_edge_pixels(alpha, transparent_mask)
    if not edge_mask.any():
        return FixResult(path, False, "No transparent pixels to fix")

    _raise_if_cancelled(cancel_event)
    nearest_y, nearest_x = _nearest_edge_coordinates(edge_mask, cancel_event)

    _raise_if_cancelled(cancel_event)
    target_y, target_x = np.nonzero(transparent_mask)
    source_y = nearest_y[target_y, target_x]
    source_x = nearest_x[target_y, target_x]
    valid_sources = (source_y >= 0) & (source_x >= 0)

    if not valid_sources.any():
        return FixResult(path, False, "No transparent pixels to fix")

    target_y = target_y[valid_sources]
    target_x = target_x[valid_sources]
    source_y = source_y[valid_sources]
    source_x = source_x[valid_sources]

    pixels[target_y, target_x, :3] = pixels[source_y, source_x, :3]
    if debug:
        pixels[target_y, target_x, 3] = 255

    _raise_if_cancelled(cancel_event)
    Image.fromarray(pixels, mode="RGBA").save(path)
    return FixResult(path, True, "Written")


def _find_opaque_edge_pixels(
    alpha: np.ndarray, transparent_mask: np.ndarray
) -> np.ndarray:
    height, width = alpha.shape
    has_transparent_neighbor = np.zeros((height, width), dtype=bool)

    for offset_x, offset_y in NEIGHBOR_LOCATIONS:
        center_y_start = max(0, -offset_y)
        center_y_end = min(height, height - offset_y)
        center_x_start = max(0, -offset_x)
        center_x_end = min(width, width - offset_x)

        if center_y_start >= center_y_end or center_x_start >= center_x_end:
            continue

        neighbor_y_start = center_y_start + offset_y
        neighbor_y_end = center_y_end + offset_y
        neighbor_x_start = center_x_start + offset_x
        neighbor_x_end = center_x_end + offset_x

        has_transparent_neighbor[
            center_y_start:center_y_end,
            center_x_start:center_x_end,
        ] |= transparent_mask[
            neighbor_y_start:neighbor_y_end,
            neighbor_x_start:neighbor_x_end,
        ]

    return (alpha != 0) & has_transparent_neighbor


def _nearest_edge_coordinates(
    edge_mask: np.ndarray, cancel_event: CancelEvent | None = None
) -> tuple[np.ndarray, np.ndarray]:
    if ndimage is not None:
        _raise_if_cancelled(cancel_event)
        nearest = ndimage.distance_transform_edt(
            ~edge_mask,
            return_distances=False,
            return_indices=True,
        )
        _raise_if_cancelled(cancel_event)
        return (
            nearest[0].astype(np.int32, copy=False),
            nearest[1].astype(np.int32, copy=False),
        )

    height, width = edge_mask.shape
    row_distances = np.empty((height, width), dtype=np.float64)
    row_nearest_x = np.empty((height, width), dtype=np.int32)

    for y in range(height):
        if y % 16 == 0:
            _raise_if_cancelled(cancel_event)

        sites = np.flatnonzero(edge_mask[y])
        distances, nearest_x = _edt_1d(width, sites)
        row_distances[y] = distances
        row_nearest_x[y] = nearest_x

    nearest_y = np.empty((height, width), dtype=np.int32)
    nearest_x = np.empty((height, width), dtype=np.int32)

    for x in range(width):
        if x % 16 == 0:
            _raise_if_cancelled(cancel_event)

        valid_rows = np.flatnonzero(np.isfinite(row_distances[:, x]))
        _, column_nearest_y = _edt_1d(
            height,
            valid_rows,
            row_distances[valid_rows, x] if valid_rows.size else None,
        )

        nearest_y[:, x] = column_nearest_y
        valid = column_nearest_y >= 0
        nearest_x[valid, x] = row_nearest_x[column_nearest_y[valid], x]
        nearest_x[~valid, x] = -1

    return nearest_y, nearest_x


def _edt_1d(
    length: int, sites: np.ndarray, costs: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    if sites.size == 0:
        return (
            np.full(length, np.inf, dtype=np.float64),
            np.full(length, -1, dtype=np.int32),
        )

    sites = sites.astype(np.int32, copy=False)
    site_costs = (
        np.zeros(sites.size, dtype=np.float64)
        if costs is None
        else costs.astype(np.float64, copy=False)
    )

    envelope = np.empty(sites.size, dtype=np.int32)
    boundaries = np.empty(sites.size + 1, dtype=np.float64)
    envelope_size = 0
    envelope[0] = 0
    boundaries[0] = -np.inf
    boundaries[1] = np.inf

    for site_index in range(1, sites.size):
        while True:
            previous_index = envelope[envelope_size]
            intersection = _parabola_intersection(
                sites[site_index],
                site_costs[site_index],
                sites[previous_index],
                site_costs[previous_index],
            )
            if intersection > boundaries[envelope_size]:
                break
            envelope_size -= 1

        envelope_size += 1
        envelope[envelope_size] = site_index
        boundaries[envelope_size] = intersection
        boundaries[envelope_size + 1] = np.inf

    distances = np.empty(length, dtype=np.float64)
    nearest = np.empty(length, dtype=np.int32)
    envelope_position = 0

    for position in range(length):
        while boundaries[envelope_position + 1] < position:
            envelope_position += 1

        site_index = envelope[envelope_position]
        site = int(sites[site_index])
        delta = float(position - site)
        distances[position] = delta * delta + site_costs[site_index]
        nearest[position] = site

    return distances, nearest


def _parabola_intersection(
    site: np.integer, site_cost: float, previous_site: np.integer, previous_cost: float
) -> float:
    site_float = float(site)
    previous_float = float(previous_site)
    denominator = 2.0 * (site_float - previous_float)

    if denominator == 0.0:
        return np.inf if site_cost >= previous_cost else -np.inf

    return (
        (site_cost + site_float * site_float)
        - (previous_cost + previous_float * previous_float)
    ) / denominator


def _raise_if_cancelled(cancel_event: CancelEvent | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise PixelFixCancelled()

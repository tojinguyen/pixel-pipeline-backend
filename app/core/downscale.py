from enum import StrEnum


class ScaleAxis(StrEnum):
    WIDTH = "width"
    HEIGHT = "height"


class ScaleByMode(StrEnum):
    WIDTH = "width"
    HEIGHT = "height"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"


SCALE_BY_AXIS_MAP: dict[ScaleByMode, ScaleAxis] = {
    ScaleByMode.WIDTH: ScaleAxis.WIDTH,
    ScaleByMode.HORIZONTAL: ScaleAxis.WIDTH,
    ScaleByMode.LANDSCAPE: ScaleAxis.WIDTH,
    ScaleByMode.HEIGHT: ScaleAxis.HEIGHT,
    ScaleByMode.VERTICAL: ScaleAxis.HEIGHT,
    ScaleByMode.PORTRAIT: ScaleAxis.HEIGHT,
}


def parse_scale_by_mode(scale_by: ScaleByMode | str | None) -> ScaleByMode:
    if scale_by is None:
        return ScaleByMode.WIDTH
    if isinstance(scale_by, ScaleByMode):
        return scale_by

    return ScaleByMode(scale_by.strip().lower())


def resolve_scale_axis(scale_by: ScaleByMode | str | None) -> ScaleAxis:
    normalized_mode = parse_scale_by_mode(scale_by)
    return SCALE_BY_AXIS_MAP[normalized_mode]

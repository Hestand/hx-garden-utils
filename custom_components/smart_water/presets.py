"""Published defaults for soil, plants, sun, and sprinklers.

Every number below is copied from a cited source or is the midpoint of a
range that source publishes. The source string on each row says which.
Blank zone fields mean "use this module." A stored number replaces it.

Crop coefficients for turf are the monthly landscape coefficients from
Meyer, Gibeault, and Youngner (1985), as republished by UC ANR. Those are
for acceptable lawn performance, not the higher FAO-56 Table 12 values for
well-watered turf (cool-season Kc mid 0.95, warm-season 0.85). Texas A&M
AgriLife's water-wise checklist tells homeowners to replace about 60% of
reference ET, which matches the published warm-season annual average.
"""

from __future__ import annotations

from dataclasses import dataclass

# Month index 0 is January. UC ANR's published annual averages are 0.80 and
# 0.60. The arithmetic means of these monthly columns are about 0.79 and
# 0.65; the extensions still tell homeowners to use 0.80 and 0.60 when they
# are not using a month. January warm-season is 0.55, matching the UC ANR
# PDF tables. One HTML copy of the same table prints 0.61.
_COOL_MONTHLY = (
    0.61,
    0.64,
    0.75,
    1.04,
    0.95,
    0.88,
    0.94,
    0.86,
    0.74,
    0.75,
    0.69,
    0.60,
)
_WARM_MONTHLY = (
    0.55,
    0.54,
    0.76,
    0.72,
    0.79,
    0.68,
    0.71,
    0.71,
    0.62,
    0.54,
    0.58,
    0.55,
)

_MEYER = (
    "Meyer, Gibeault, and Youngner 1985, republished by UC ANR "
    "(ucanr.edu turfgrass crop coefficients; also the 2011 PDF table). "
    "Cool-season species in that trial: tall fescue, ryegrass, bentgrass, "
    "Kentucky bluegrass. Warm-season species: bermudagrass, zoysiagrass, "
    "and St. Augustinegrass."
)
_ASABE_PF = (
    "ANSI/ASABE S623 plant factors as republished by UC ANR "
    "(Plant Factor or Crop Coefficient, and the SLIDE rules page)."
)
_FAO_P50 = (
    "FAO-56 Chapter 8: a value of 0.50 for p is commonly used for many crops. "
    "Table 22 has no row for this landscape planting."
)
_FAO_ZR_NOTE = (
    "FAO-56 Table 22 footnote 1: the smaller root depth is for irrigation "
    "scheduling. Depths are converted from metres and rounded to the nearest inch."
)
_AGRILIFE_6IN = (
    "Texas A&M AgriLife, Water-Wise Checklist for Texas Home Lawns: water "
    "established turf to about 6 inches. FAO-56 Table 22 lists turf rooting "
    "at 0.5–1.0 m and says some grasses root deeper when depletion is allowed "
    "to encourage it. Six inches is the managed home-lawn depth, not that maximum."
)


@dataclass(frozen=True)
class SoilPreset:
    """One texture: available water and the four NRCS slope-band intake rates."""

    awc_low: float
    awc_high: float
    awc: float
    intake_in_hr: tuple[float, float, float, float]
    source: str


@dataclass(frozen=True)
class PlantPreset:
    """One planting. ``kc_monthly`` is January through December when known."""

    kc_annual: float
    kc_monthly: tuple[float, ...] | None
    p: float
    root_depth_in: float
    source: str


@dataclass(frozen=True)
class SprinklerPreset:
    """Typical rate and efficiency. ``precip_in_hr`` is None when unpublished."""

    precip_in_hr: float | None
    efficiency: float
    source: str


# FAO-56 Table 19, θFC − θWP (m³/m³, which is the same as in/in).
# The default is the midpoint of the published range unless the note says otherwise.
# Intake is inches per hour at NRCS slope bands 0–5 / 5–8 / 8–12 / 12–16,
# from the NRCS "suggested maximum application rates" sheet reproduced by
# Michigan State University (NRCSIrrMngmt.pdf):
#   coarse sandy soil to 6 ft;
#   light sandy loams to 6 ft;
#   silt loams to 6 ft;
#   silt loams over more compact soils;
#   heavy textured clays or clay loams.
SOILS: dict[str, SoilPreset] = {
    "sand": SoilPreset(
        0.05,
        0.11,
        0.08,
        (2.0, 1.5, 1.0, 0.50),
        "AWC midpoint of FAO-56 Table 19 sand (0.05–0.11). "
        "Intake: NRCS coarse sandy soil to 6 ft.",
    ),
    "sandy_loam": SoilPreset(
        0.11,
        0.15,
        0.13,
        (1.0, 0.80, 0.60, 0.40),
        "AWC midpoint of FAO-56 Table 19 sandy loam (0.11–0.15). "
        "Intake: NRCS light sandy loams to 6 ft.",
    ),
    "loam": SoilPreset(
        0.13,
        0.18,
        0.155,
        (0.50, 0.40, 0.30, 0.20),
        "AWC midpoint of FAO-56 Table 19 loam (0.13–0.18). "
        "The NRCS sheet has no loam row, so intake uses the silt-loam-to-6-ft row.",
    ),
    "silt_loam": SoilPreset(
        0.13,
        0.19,
        0.16,
        (0.50, 0.40, 0.30, 0.20),
        "AWC midpoint of FAO-56 Table 19 silt loam (0.13–0.19). "
        "Intake: NRCS silt loams to 6 ft.",
    ),
    "silt_loam_compact": SoilPreset(
        0.13,
        0.19,
        0.16,
        (0.30, 0.25, 0.15, 0.10),
        "FAO-56 Table 19 has no compact-silt row, so AWC uses the silt-loam "
        "midpoint (0.16). Intake: NRCS silt loams over more compact soils.",
    ),
    "clay_loam": SoilPreset(
        0.12,
        0.20,
        0.16,
        (0.15, 0.10, 0.08, 0.06),
        "FAO-56 Table 19 has no clay-loam row. AWC uses the clay range "
        "(0.12–0.20, midpoint 0.16) because the NRCS sheet groups heavy clays "
        "and clay loams. NRCS National Engineering Handbook Part 652 lists a "
        "typical clay-loam AWC near 0.20 in/in (2.4 in/ft); set the override "
        "to 0.20 to use that figure. Intake: NRCS heavy textured clays or clay loams.",
    ),
    "clay": SoilPreset(
        0.12,
        0.20,
        0.16,
        (0.15, 0.10, 0.08, 0.06),
        "AWC midpoint of FAO-56 Table 19 clay (0.12–0.20). "
        "Intake: NRCS heavy textured clays or clay loams.",
    ),
}

# p for turf is FAO-56 Table 22 at ETc ≈ 5 mm/day: cool season 0.40,
# warm season 0.50 (bermuda, buffalo, St. Augustine are named there).
# FAO also says p can be 5–10% lower on fine soil and 5–10% higher on coarse
# soil. That adjustment is not applied automatically; override MAD to use it.
PLANTS: dict[str, PlantPreset] = {
    "st_augustine": PlantPreset(
        0.60,
        _WARM_MONTHLY,
        0.50,
        6.0,
        _MEYER
        + " St. Augustine is in that warm-season group and in the ASABE/UC "
        "plant factor 0.6. A Texas A&M lysimeter thesis (Wherley, 2021–2022, "
        "oaktrust 1969.1/198974) measured well-watered St. Augustine nearer "
        "0.8–0.9; raise the Kc override for that condition. "
        + _AGRILIFE_6IN
        + " MAD is FAO-56 Table 22 warm-season turf, p=0.50. "
        "Peacock and Dudeck 1985, cited by a Texas A&M thesis, found about "
        "91% of St. Augustine roots in the top 30 cm; raise root depth toward "
        "12 in if you irrigate that whole layer.",
    ),
    "bermuda": PlantPreset(
        0.60,
        _WARM_MONTHLY,
        0.50,
        6.0,
        _MEYER
        + " The same Texas A&M lysimeter work found Tifway and TifTuf hybrid "
        "bermuda averaging about 0.6 under well-watered conditions, in line "
        "with this landscape coefficient. "
        + _AGRILIFE_6IN
        + " MAD is FAO-56 Table 22 warm-season turf, p=0.50. Bermuda in that "
        "trial produced roots at 10–20 inches (AgriLife 2010 TTREEE summary); "
        "the managed depth stays 6 inches unless you override it.",
    ),
    "zoysia": PlantPreset(
        0.60,
        _WARM_MONTHLY,
        0.50,
        6.0,
        _MEYER
        + " Zoysia is in the UC warm-season group. The Texas A&M lysimeter "
        "work called zoysia intermediate between bermuda and St. Augustine. "
        + _AGRILIFE_6IN
        + " MAD is FAO-56 Table 22 warm-season turf, p=0.50. Matrella zoysia "
        "in the 2010 AgriLife summary had few roots at 10–20 inches.",
    ),
    "buffalo": PlantPreset(
        0.60,
        _WARM_MONTHLY,
        0.50,
        6.0,
        "Buffalo is not in the Meyer species list. UC ANR / ASABE S623 group "
        "it with bermuda, zoysia, and St. Augustine at plant factor 0.6, so "
        "it uses that warm-season monthly table. FAO-56 Table 22 names buffalo "
        "under warm-season turf (p=0.50, rooting 0.5–1.0 m). " + _AGRILIFE_6IN,
    ),
    "warm_season_turf": PlantPreset(
        0.60,
        _WARM_MONTHLY,
        0.50,
        6.0,
        "Generic warm-season lawn: the Meyer / UC ANR monthly table and annual "
        "average 0.60, which matches AgriLife's 'about 60% of reference ET.' "
        "FAO-56 Table 12's well-watered warm-season Kc mid is 0.85 (0.75 with "
        "careful water management). MAD and the 6 inch depth are the same as "
        "the named warm-season grasses.",
    ),
    "cool_season_turf": PlantPreset(
        0.80,
        _COOL_MONTHLY,
        0.40,
        6.0,
        _MEYER
        + " Annual average 0.80. FAO-56 Table 12 cool-season Kc mid is 0.95 "
        "(0.85 with careful water management). MAD is FAO-56 Table 22 "
        "cool-season turf, p=0.40. Root depth is AgriLife's 6 inch managed "
        "depth; Table 22's range is 0.5–1.0 m.",
    ),
    "shrub": PlantPreset(
        0.50,
        None,
        0.50,
        24.0,
        _ASABE_PF
        + " Woody plants (trees, shrubs, vines, groundcovers) plant factor 0.5. "
        + _FAO_P50
        + " Root depth 24 in is the FAO-56 Table 22 berries (bushes) lower "
        "bound of 0.6 m (23.6 in), rounded, used as the scheduling depth for "
        "a woody shrub because Table 22 has no landscape-shrub row. " + _FAO_ZR_NOTE,
    ),
    "flower_bed": PlantPreset(
        0.80,
        None,
        0.50,
        12.0,
        _ASABE_PF
        + " Annual flowers and bedding plants, plant factor 0.8. "
        + _FAO_P50
        + " Root depth 12 in is a stand-in: FAO-56 has no bedding-plant row. "
        "It is the Table 22 lower scheduling depth for shallow vegetables "
        "(lettuce, spinach, celery, radish), 0.3 m rounded to 12 in.",
    ),
    "vegetable": PlantPreset(
        1.00,
        None,
        0.50,
        12.0,
        _ASABE_PF
        + " Home vegetable crops, plant factor 1.0. FAO-56 Table 12 mid-season "
        "coefficients for many vegetables are higher (often near 1.05–1.15) "
        "and Table 22 depletion runs from 0.20 (celery, spinach) to 0.50 "
        "(cucumber, squash). p=0.50 is the Chapter 8 common value, not a "
        "single-crop row. Root depth 12 in is the 0.3 m lower scheduling "
        "depth for shallow vegetables. Tomato's Table 22 lower bound is "
        "0.7 m (about 28 in); raise the override for deep fruiting crops.",
    ),
    "tree": PlantPreset(
        0.50,
        None,
        0.50,
        39.0,
        _ASABE_PF
        + " Woody plants, plant factor 0.5. "
        + _FAO_P50
        + " Root depth 39 in is the FAO-56 Table 22 lower bound for several "
        "fruit trees (apple, stone fruit, almond), 1.0 m rounded. Ornamental "
        "shade trees are not a Table 22 row.",
    ),
    "drip_bed": PlantPreset(
        0.50,
        None,
        0.50,
        24.0,
        "A mixed ornamental bed. " + _ASABE_PF + " The woody-plant factor 0.5 "
        "is used because a mixed bed takes the highest factor present only "
        "when annuals or vegetables are in it; this row is the shrub bed. "
        "Switch the plant type if the bed is flowers (0.8) or vegetables (1.0). "
        + _FAO_P50
        + " Root depth matches the shrub row (24 in).",
    ),
    "native": PlantPreset(
        0.30,
        None,
        0.50,
        24.0,
        _ASABE_PF
        + " Desert-adapted plants, plant factor 0.3. "
        + _FAO_P50
        + " Root depth matches the shrub scheduling depth (24 in); desert "
        "species are not given a separate depth in these sources.",
    ),
}

# Sun is a WUCOLS microclimate factor (kmc), from Costello and Jones,
# Estimating Irrigation Water Needs of Landscape Plantings in California
# (WUCOLS), the table of species, density, and microclimate factors:
# average 1.0, low/protected 0.5–0.9.
SUN: dict[str, tuple[float, str]] = {
    "full_sun": (
        1.0,
        "WUCOLS average microclimate, kmc = 1.0. Not an extra heat load.",
    ),
    "part_sun": (
        0.9,
        "Top of the WUCOLS low/protected range (0.5–0.9), for light or "
        "partial shade rather than a north-wall courtyard.",
    ),
    "shade": (
        0.7,
        "Midpoint of the WUCOLS low/protected range 0.5–0.9.",
    ),
}

# Efficiency here is the fraction the scheduler treats as useful (net / gross),
# the same role as a lower-quarter distribution uniformity in a runtime
# multiplier. It is a literature default, not an audit of your yard.
SPRINKLERS: dict[str, SprinklerPreset] = {
    "spray": SprinklerPreset(
        1.25,
        0.60,
        "Precipitation 1.25 in/hr is the midpoint of 1.0–1.5 in/hr. The "
        "Irrigation Association Homeowner's Guide (2017) says gear-drive "
        "rotors apply about 0.5 in/hr and fixed sprays apply two to three "
        "times that. Efficiency 0.60 is the midpoint of the Irrigation "
        "Association 2004 BMP minimum lower-quarter DU for fixed spray (0.55) "
        "and the EPA WaterSense draft spray-nozzle DULQ criterion (0.65).",
    ),
    "rotor": SprinklerPreset(
        0.50,
        0.70,
        "Precipitation 0.5 in/hr from the Irrigation Association Homeowner's "
        "Guide (2017): gear-drive rotors apply about one-half inch per hour. "
        "A city handout has also listed rotor heads at 0.8 in/hr; override "
        "if your heads match that. Efficiency 0.70 is the Irrigation "
        "Association 2004 BMP minimum lower-quarter DU for rotors.",
    ),
    "mp_rotator": SprinklerPreset(
        0.40,
        0.65,
        "Precipitation 0.4 in/hr from the Hunter MP Rotator design guide "
        "(standard nozzles, approximately 0.4 in/hr). MP800 is about 0.8 in/hr "
        "and has to be entered as an override. Efficiency 0.65 is the EPA "
        "WaterSense draft DULQ for spray nozzles; ASABE/ICC 802 classes "
        "multi-stream nozzles with spray nozzles. The rotor BMP minimum is "
        "0.70 if you would rather audit them as rotors.",
    ),
    "drip": SprinklerPreset(
        0.50,
        0.875,
        "Precipitation 0.5 in/hr is the drip figure on a municipal average-rate "
        "sheet, which assumes two 2 gph emitters per plant over an 800 sq ft "
        "canopy. It is not a universal drip rate; override it, or enter GPM "
        "and area. Efficiency 0.875 is the midpoint of 0.85 (surface drip) and "
        "0.90 (subsurface drip) from the 2021 IWAC landscape-efficiency "
        "webinar. EPA WaterSense at Work says drip can use 20–50% less water "
        "than sprays; that is not used as an efficiency number.",
    ),
    "bubbler": SprinklerPreset(
        None,
        1.0,
        "No single precipitation rate or distribution uniformity for landscape "
        "bubblers was found in FAO-56, the Irrigation Association guides, or "
        "the manufacturer design note used for MP Rotators. Adjustable bubblers "
        "are sold across roughly 0.25–2 gpm, which is not a precipitation rate "
        "until you know the basin area. Efficiency stays 1.0 so an unpublished "
        "uniformity is not assumed. Enter a precipitation rate, or GPM and area.",
    ),
}

SOIL_TYPES = tuple(SOILS)
PLANT_TYPES = tuple(PLANTS)
SUN_EXPOSURES = tuple(SUN)
SPRINKLER_TYPES = tuple(SPRINKLERS)


def soil_preset(soil_type: str) -> SoilPreset:
    """Return the soil row or raise KeyError."""
    return SOILS[soil_type]


def plant_preset(plant_type: str) -> PlantPreset:
    """Return the plant row or raise KeyError."""
    return PLANTS[plant_type]


def available_water_default(soil_type: str) -> float:
    """Midpoint (or noted choice) of available water, m³/m³."""
    return SOILS[soil_type].awc


def slope_band(slope_pct: float) -> int:
    """Return 0..3 for NRCS bands 0–5 / 5–8 / 8–12 / 12–16 percent.

    The upper edge of a band stays in that band (5% is 0–5). Steeper than
    16% uses the 12–16% rate, which is the lowest in the table.
    """
    if slope_pct <= 5:
        return 0
    if slope_pct <= 8:
        return 1
    if slope_pct <= 12:
        return 2
    return 3


def intake_default(soil_type: str, slope_pct: float) -> float:
    """NRCS maximum application rate for this texture and slope, in/hr."""
    return SOILS[soil_type].intake_in_hr[slope_band(slope_pct)]


def plant_kc(plant_type: str, month: int | None) -> float:
    """Monthly coefficient when the plant has one and the month is known."""
    plant = PLANTS[plant_type]
    if month is not None and plant.kc_monthly is not None:
        if not 1 <= month <= 12:
            raise ValueError("month must be 1–12")
        return plant.kc_monthly[month - 1]
    return plant.kc_annual


def sun_factor(sun_exposure: str) -> float:
    """WUCOLS microclimate factor for the exposure."""
    return SUN[sun_exposure][0]


def sprinkler_precip(sprinkler_type: str) -> float | None:
    """Typical precipitation rate, or None when the type has no published rate."""
    return SPRINKLERS[sprinkler_type].precip_in_hr


def sprinkler_efficiency(sprinkler_type: str) -> float:
    """Literature efficiency for this sprinkler type."""
    return SPRINKLERS[sprinkler_type].efficiency


def _blank(value: object) -> bool:
    return value is None or value == ""


def stored_float(data: dict[str, object], key: str) -> float | None:
    """Return a stored override, or None when the field was left blank."""
    value = data.get(key)
    if _blank(value):
        return None
    return float(value)  # type: ignore[arg-type]


def resolved_root_depth_in(data: dict[str, object]) -> float:
    """Stored root depth, otherwise the plant preset."""
    stored = stored_float(data, "root_depth_in")
    if stored is not None:
        return stored
    return PLANTS[str(data["plant_type"])].root_depth_in


def resolved_slope_pct(data: dict[str, object]) -> float:
    """Stored slope, otherwise 0 (the NRCS 0–5% band)."""
    stored = stored_float(data, "slope_pct")
    if stored is not None:
        return stored
    return 0.0


def resolved_efficiency(data: dict[str, object]) -> float:
    """Stored efficiency, otherwise the sprinkler preset."""
    stored = stored_float(data, "efficiency")
    if stored is not None:
        return stored
    sprinkler = str(data.get("sprinkler_type") or "spray")
    return sprinkler_efficiency(sprinkler)


# Sustained wind at or above these speeds skips overhead irrigation.
# Oklahoma State HLA-6610 says not to water in high wind and does not publish
# a speed. University of Florida overhead-irrigation guidance treats wind
# above about 10 mph as unsuitable. The Irrigation Association's 2013 wind
# paper shows smaller droplets drift more, so sprays use 10 mph, rotors 15,
# and MP rotators the midpoint (12). Drip and bubblers are not aerial.
WIND_SKIP_MPH: dict[str, float | None] = {
    "spray": 10.0,
    "mp_rotator": 12.0,
    "rotor": 15.0,
    "drip": None,
    "bubbler": None,
}

# AgriLife Water-Wise: established turf no more than 1–2 times a week, watered
# to about 6 inches. Three days is the short end of twice a week. Shrubs,
# trees, and native plantings wait a week. Vegetables and flowers wait 2.
MIN_INTERVAL_DAYS: dict[str, int] = {
    "st_augustine": 3,
    "bermuda": 3,
    "zoysia": 3,
    "buffalo": 3,
    "warm_season_turf": 3,
    "cool_season_turf": 3,
    "shrub": 7,
    "tree": 7,
    "native": 7,
    "drip_bed": 7,
    "vegetable": 2,
    "flower_bed": 2,
}


def wind_skip_mph(sprinkler_type: str) -> float | None:
    """Default sustained-wind skip, or None when wind does not apply."""
    return WIND_SKIP_MPH.get(sprinkler_type)


def min_interval_days(plant_type: str) -> int | None:
    """Days between waterings, or None when the planting has no default."""
    return MIN_INTERVAL_DAYS.get(plant_type)


def preset_placeholders(
    *,
    plant_type: str,
    soil_type: str,
    sprinkler_type: str,
    slope_pct: float,
    month: int,
    sun_exposure: str = "full_sun",
) -> dict[str, str]:
    """Text for the advanced-step descriptions. Blank fields use these.

    ``kc`` is the monthly (or annual) plant coefficient times the sun factor.
    A Kc override replaces that product.
    """
    plant = PLANTS[plant_type]
    soil = SOILS[soil_type]
    sprinkler = SPRINKLERS[sprinkler_type]
    kc = plant_kc(plant_type, month) * sun_factor(sun_exposure)
    precip = sprinkler.precip_in_hr
    return {
        "root_depth": f"{plant.root_depth_in:g}",
        "awc": f"{soil.awc:.3f}",
        "mad": f"{plant.p:.2f}",
        "kc": f"{kc:.2f}",
        "kc_annual": f"{plant.kc_annual:.2f}",
        "intake": f"{intake_default(soil_type, slope_pct):.2f}",
        "slope": f"{slope_pct:g}",
        "precip": "none published" if precip is None else f"{precip:.2f}",
        "efficiency": f"{sprinkler.efficiency:.3f}".rstrip("0").rstrip("."),
        "sun": f"{sun_factor(sun_exposure):.1f}",
    }

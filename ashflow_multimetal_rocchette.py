import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import rasterio
from rasterio.warp import reproject, Resampling
from scipy.ndimage import distance_transform_edt
from matplotlib.colors import ListedColormap

# ==========================================
# 1. INPUT FILES
# ==========================================
dnbr_path = "dnbr_rocchette_2025.tif"
ndwi_path = "real_ndwi_rocchette.tif"

metal_files = {
    "As": "As/As_EU27.tif",
    "Cd": "Cd/Cd_EU27.tif",
    "Co": "Co/Co_EU27.tif",
    "Cr": "Cr/Cr_EU27.tif",
    "Cu": "Cu/Cu_EU27.tif",
    "Hg": "Hg/Hg_EU27.tif",
    "Mn": "Mn/Mn_EU27.tif",
    "Ni": "Ni/Ni_EU27.tif",
    "Pb": "Pb/Pb_EU27.tif",
    "Sb": "Sb/Sb_EU27.tif",
}

# ==========================================
# 2. LOAD FIRE + WATER RASTERS
# ==========================================
with rasterio.open(dnbr_path) as src:
    dnbr = src.read(1).astype(np.float32)
    dst_transform = src.transform
    dst_crs = src.crs
    dst_shape = dnbr.shape

with rasterio.open(ndwi_path) as src:
    ndwi = src.read(1).astype(np.float32)

# ==========================================
# 3. BURN SEVERITY
# ==========================================
severity = np.zeros_like(dnbr, dtype=np.uint8)
severity[(dnbr >= 0.10) & (dnbr < 0.27)] = 1   # low
severity[(dnbr >= 0.27) & (dnbr < 0.44)] = 2   # moderate
severity[(dnbr >= 0.44)] = 3                   # high

severity_norm = severity / 3.0

# ==========================================
# 4. WATER MASK + PROXIMITY
# ==========================================
water_mask = ndwi > 0.0
distance_px = distance_transform_edt(~water_mask)
distance_m = distance_px * 10.0  # Sentinel-2 10 m pixels

near_water_factor = 1 - (distance_px / np.nanmax(distance_px))
near_water_factor = np.clip(near_water_factor, 0, 1)

# never treat water itself as burned land
severity[water_mask] = 0
severity_norm[water_mask] = 0

# ==========================================
# 5. LOAD + REPROJECT ALL METALS
# ==========================================
metal_scores = {}
metal_means = {}
metal_resampled_store = {}

# We calculate scores only on burned land
analysis_mask = severity > 0

for metal, path in metal_files.items():
    if not os.path.exists(path):
        print(f"Skipping {metal}: file not found -> {path}")
        continue

    resampled = np.full(dst_shape, np.nan, dtype=np.float32)

    with rasterio.open(path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=resampled,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
            dst_nodata=np.nan
        )

    # check if there are any valid values at all after reprojection
    valid = np.isfinite(resampled)
    if np.sum(valid) == 0:
        print(f"Skipping {metal}: no valid overlap after reprojection")
        continue

    # check if there are valid values specifically over the burned land area
    local_analysis = analysis_mask & valid
    if np.sum(local_analysis) == 0:
        print(f"Skipping {metal}: no valid metal values over the burned land area")
        continue

    metal_resampled_store[metal] = resampled

    # robust normalization inside the local AOI
    local_vals = resampled[valid]
    p5 = np.nanpercentile(local_vals, 5)
    p95 = np.nanpercentile(local_vals, 95)

    if p95 - p5 < 1e-6:
        norm = np.zeros_like(resampled, dtype=np.float32)
    else:
        norm = np.clip((resampled - p5) / (p95 - p5), 0, 1)

    # metal threat score
    score = severity_norm * near_water_factor * norm
    score[water_mask] = 0
    score[~analysis_mask] = 0

    metal_scores[metal] = score

    zone = score[analysis_mask]
    metal_means[metal] = float(np.nanmean(zone)) if zone.size > 0 else 0.0

    vals = resampled[local_analysis]
    print(f"{metal}: valid burned pixels = {vals.size}, mean = {np.nanmean(vals):.2f}")
# ==========================================
# 6. AGGREGATE MULTI-METAL SCORE
# ==========================================
if len(metal_scores) == 0:
    raise RuntimeError("No metal rasters were successfully loaded.")

metal_names = list(metal_scores.keys())
stack = np.stack([metal_scores[m] for m in metal_names], axis=0)

# where at least one metal has a valid value
any_valid_metal = np.any(np.isfinite(stack), axis=0)

# replace NaN with 0 so max/argmax do not crash
stack_safe = np.nan_to_num(stack, nan=0.0, posinf=0.0, neginf=0.0)

# overall score
overall_score = np.max(stack_safe, axis=0)

# dominant metal
dominant_idx = np.argmax(stack_safe, axis=0)
dominant_metal = np.full(dst_shape, "NoData", dtype=object)

for i, m in enumerate(metal_names):
    dominant_metal[(dominant_idx == i) & any_valid_metal] = m

overall_score[water_mask] = 0
overall_score[~analysis_mask] = 0

# monitoring priority classes
priority_class = np.zeros_like(overall_score, dtype=np.uint8)
priority_class[(overall_score > 0.10) & (overall_score <= 0.25)] = 1   # low
priority_class[(overall_score > 0.25) & (overall_score <= 0.50)] = 2   # medium
priority_class[(overall_score > 0.50)] = 3                             # high
priority_class[water_mask] = 0

# ==========================================
# 7. TOP CONTAMINANTS
# ==========================================
top_metals = sorted(metal_means.items(), key=lambda x: x[1], reverse=True)

# ==========================================
# 8. SUMMARY METRICS
# ==========================================
PIXEL_AREA_M2 = 100.0  # 10m x 10m
def px_to_hectares(n):
    return n * PIXEL_AREA_M2 / 10000.0

burned_pixels = int(np.sum(severity > 0))
burned_area_ha = round(px_to_hectares(burned_pixels), 2)

within_300m = int(np.sum((severity > 0) & (distance_m <= 300)))
within_300m_ha = round(px_to_hectares(within_300m), 2)

low_priority_ha = round(px_to_hectares(np.sum(priority_class == 1)), 2)
med_priority_ha = round(px_to_hectares(np.sum(priority_class == 2)), 2)
high_priority_ha = round(px_to_hectares(np.sum(priority_class == 3)), 2)

# ==========================================
# 9. BUILD CUSTOMER-FACING MAP
# ==========================================
display = np.zeros_like(priority_class, dtype=np.uint8)
display[(~water_mask) & (priority_class == 1)] = 2
display[(~water_mask) & (priority_class == 2)] = 3
display[(~water_mask) & (priority_class == 3)] = 4
display[water_mask] = 1

cmap = ListedColormap([
    "black",      # background
    "#1f4e9e",    # water
    "yellow",     # low
    "orange",     # medium
    "red"         # high
])

fig = plt.figure(figsize=(16, 9))

# Main map
ax1 = plt.subplot(1, 2, 1)
ax1.imshow(display, cmap=cmap, interpolation="nearest")
ax1.set_title("ASHFLOW — Multi-Metal Post-Fire Monitoring Priority", fontsize=16)
ax1.axis("off")

legend_patches = [
    mpatches.Patch(color="#1f4e9e", label="Water body"),
    mpatches.Patch(color="yellow", label="Low priority"),
    mpatches.Patch(color="orange", label="Medium priority"),
    mpatches.Patch(color="red", label="High priority"),
]
ax1.legend(handles=legend_patches, loc="lower left", fontsize=10, frameon=True)

# Text panel
ax2 = plt.subplot(1, 2, 2)
ax2.axis("off")

top_lines = []
for metal, value in top_metals[:5]:
    top_lines.append(f"- {metal}: {value:.3f}")

top_text = "\n".join(top_lines)

summary_text = f"""
CASE: Rocchette wildfire, Tuscany, Italy

What this map shows:
This is a post-fire contaminant-monitoring priority map.
It combines:
- wildfire damage
- distance to nearby water
- baseline heavy metals in soil

Key metrics:
- Total burned area: {burned_area_ha} ha
- Burned area within 300 m of water: {within_300m_ha} ha
- Low priority area: {low_priority_ha} ha
- Medium priority area: {med_priority_ha} ha
- High priority area: {high_priority_ha} ha

Likely contaminants of concern:
{top_text}

How to interpret this:
These metals are not directly measured in water here.
Instead, they represent contaminants that should be prioritised
for post-rain monitoring because the wildfire affected land
overlapping soils where these metals are present.

Recommended action:
- Prioritise water sampling after the next major rainfall event
- Focus on coastal segments closest to the burn scar
- Include the top-ranked metals in laboratory testing
"""

ax2.text(0.0, 1.0, summary_text, va="top", ha="left", fontsize=12, wrap=True)

plt.tight_layout()
plt.savefig("ashflow_multimetal_output_rocchette.png", dpi=200, bbox_inches="tight")
plt.show()

print("Saved: ashflow_multimetal_output_rocchette.png")
print("\nTop contaminants of concern:")
for metal, value in top_metals[:5]:
    print(f"{metal}: {value:.4f}")
# Technical Report: Satellite-Based Intelligence for Post-Fire Water Contamination

**Project Title:** ASHFLOW
**Category:** Tracking and preventing water pollution   
**Hackathon:** 11th Cassini EU Hackathon 2026

---



## 1. Problem Summary
This report details a high-fidelity API and monitoring system designed to mitigate the tetriary environmental impacts of wildfires. While fire damage is often measured in hectares burned, **the subsequent contamination of water reservoirs via ash runoff represents a multi-billion euro threat to the European insurance sectors**. By integrating **Copernicus Sentinel** data, we provide a predictive risk-modeling tool that tracks toxicrunoff from the burn scar to the reservoir. 
### Currently there doesn't exist any stakeholder for this specific detection, because systems usually focus on fire tracking and general water pollution, but not the bridge betweeen the two.


---

## 2. The Problem Landscape

### 2.1 The Fire-Ash-Water Phenomenon
Wildfires create a chemically complex layer of ash containing concentrated nitrates, phosphates, and heavy metals. When the first significant rain event occurs post-fire, this material is mobilized.
Water contamination is a tertiary consequence — fire burns structures → pressure drop in pipes → benzene leaches in → water system is unusable for months → property becomes uninhabitable → insurance claim. This entire chain is currently unmodeled. What is modeled well is fire detection and water contamination detection. 
* **The Erosion Factor:** Fires destroy the vegetation that stabilizes soil, leading to massive sediment transport.
* **The Hydrological Link:** Rain carries this sediment into streams and eventually into large-scale water reservoirs.

### 2.2 Business Model Analysis
We have identified two primary sectors suffering in post-fire recovery: **Reinsurance Companies that deal with catastrophies, Governmental bodies which are the first target after a catastrophy and Environmental Consulting Firms that already have tracking systems but would aid in a specific fire-ash-water niche**. There is also a new law implemented all around the world, recently implemented in Italy as - CATNAT **Police CATASTROFALI**, that states that every institution with headquarters has to have catastrophy specific insurance. This increases the demand for insurance -> which increases the demand for risk evaluation and detection systems.

---

## 3. Space Data & Earth Observation Strategy

Our solution relies on the synergy between Copernicus assets to create a holistic view of the disaster.

| Satellite / Service | Instrument / Data | Application |
| :--- | :--- | :--- |
| **Sentinel-2** | Multispectral (MSI) | NIR and SWIR bands are used to calculate the **Normalized Burn Ratio (NBR)** to map fire perimeters and severity.  OLCI & SLSTR | Monitoring water quality parameters like **Chlorophyll-a** and **Total Suspended Matter (TSM)** to validate runoff models. |
| **ERA5 ECMWF** | Rainfall forecats, intensity, water total precipitation and wind gusts
| **LUCAS topsoil Survey** | Comprehensive dataset that exhibits the contents of the soil in potential burn areas
| **CORINE LAND COVER** | Terrain specific data| Utilized to determine **topographic slope** and the flow direction of water toward reservoirs. |

---

## 4. Technical Architecture

### 4.1 The Contamination Risk API
The core of our project is a RESTful API that processes spatial data and returns a **Contamination Probability Index (CPI)**.

$$CPI = (B \times 0.45) + (S \times 0.25) + (P \times 0.30)$$

* **Burnt Content ($B$ - 45%):** High-severity burns produce more mobile ash.
* **Topographic Slope ($S$ - 25%):** Steeper terrain accelerates runoff.
* **Proximity & Connectivity ($P$ - 30%):** Calculated using distance to reservoirs and river network connectivity.

### 4.2 Threshold Logic & Visualization
When the API detects a CPI exceeding **0.75**, the system triggers a **"Critical State"** on the dashboard.

1.  **Primary Screen:** Interactive Map showing fire perimeters (Red) and Reservoir catchments (Blue).
2.  **Secondary Screen:** Displays estimated contaminant load and specific warnings (e.g., *"High Risk of Pump Clogging"*).

---

## 5. Implementation & Code Logic

### 5.1 Data Pipeline
The program follows a structured processing flow:

1.  **Collection Querying:** Using the **Sentinel OPENEO API** to pull the latest L2A imagery.
2.  **Masking & Indices:** Automated cloud masking followed by NBR calculation.
3.  **Watershed Analysis:** Utilizing libraries like **PySheds** to delineate the drainage basin of the target reservoir.
4.  **API Payload:** Results are serialized into JSON for the frontend.


## Specifics showcased example
[cite_start]This demo build focuses on the **Corinthia wildfire** in Greece (ignited 29 September 2024), which burned approximately 8,195 ha[cite: 4, 5].

---

### API Endpoint
[cite_start]The demo utilizes a single **FastAPI** endpoint to generate forecasts along with the open source Satellite database through the library **Openeo** in Python[cite: 17, 135].

[cite_start]**`POST /api/contamination-forecast`** [cite: 20]

**Request Body Example:**
```json
{
  "location": {
    "name": "Lake Stymfalia",
    "lon": 22.456,
    "lat": 37.852
  },
  "fire_event": {
    "ignition_date": "2024-09-29",
    "burned_area_bbox": {
      "west": 22.20, "east": 22.65,
      "south": 37.80, "north": 38.05
    }
  },
  "forecast_months": 6
}
```
[cite_start][cite: 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37]

---

## Calculation Methodology
[cite_start]The engine estimates monthly contaminant loads ($kg$) based on burned upstream areas and land use categories[cite: 80, 81, 82].

### Step 1: Upstream Analysis
[cite_start]Identify burned polygons within a **15km radius** that are at a higher elevation than the target lake[cite: 84].

### Step 2: Emission Factors
[cite_start]Base emission factors (kg of contaminant per hectare) vary by land use[cite: 87, 88]:

| Category | PAHs (kg/ha) | DOC (kg/ha) | Phosphorus (kg/ha) | Nitrates (kg/ha) |
| :--- | :--- | :--- | :--- | :--- |
| **Forest / Shrubland** | 0.04 – 0.06 | 0.25 – 0.35 | 0.018 – 0.025 | 0.06 – 0.08 |
| **Agricultural Land** | 0.01 – 0.02 | 0.10 – 0.18 | 0.035 – 0.055 | 0.12 – 0.18 |
| **Industrial / Mining**| 0.02 – 0.04 | 0.08 – 0.14 | — | — |
[cite_start][cite: 89]

### Step 3: Decay Function
[cite_start]Contamination follows a negative exponential decay curve after the first rain event[cite: 97, 98]:
[cite_start]$$load\_month\_m = base\_load \times severity\_multiplier \times decay(m)$$ [cite: 99]

* [cite_start]**Organic (PAHs, DOC):** $exp(-0.35 \times (m - 1))$ [cite: 100]
* [cite_start]**Nutrients (Phosphorus, Nitrates):** $exp(-0.20 \times (m - 1))$ [cite: 101]
* [cite_start]**Heavy Metals:** $exp(-0.10 \times (m - 1))$ [cite: 102]

---

## Development Checklist
[cite_start]To prepare the demo, the following delta work is required[cite: 116]:

Run this ONCE before starting the API:
    **python sentinel_pipeline.py**

It will:
  1. Connect to Copernicus Data Space (browser login on first run)
  2. Download pre-fire and post-fire Sentinel-2 composites
  3. Compute dNBR and save to output/dnbr_corinthia.tif
  4. Classify severity and save to output/severity_corinthia.tif
  5. Extract burned area stats per lake catchment
  6. Save output/lake_upstream_stats.json  ← the API reads this file

After this script finishes, start the API normally:
    **uvicorn api:app --reload --port 8000**

---

## File Structure
```text
aquafire/
├── config.py                 # AOI + date configuration
├── sentinel_pipeline.py                   # Core pipeline execution
├── api.py                    # FastAPI endpoint
├── requirements.txt          # Dependencies (fastapi, uvicorn)
├── engine/
│   ├── forecast.py           # Monthly load model logic
│ 
└── output/                   # Pre-generated geospatial data from sentinel_pipeline with openeo
```
[cite_start][cite: 176, 177, 178, 179, 180, 181, 187, 188]
---

##### Burn Severity and Perimeter Mapping
The process initiates with fire detection utilizing **Sentinel-2** satellite imagery. By calculating the **differenced Normalized Burn Ratio (dNBR)**, the system establishes a precise burned area perimeter and classifies fire severity levels. While these datasets are standard within the Copernicus ecosystem, they serve as the critical trigger for the downstream analytical chain.

The dNBR is calculated as:
$$\Delta NBR = NBR_{pre\_fire} - NBR_{post\_fire}$$
Where:
$$NBR = \frac{NIR - SWIR}{NIR + SWIR}$$

---

##### Geospatial Intersection and Baseline Analysis
The identified burned area is overlaid onto two preloaded, static EU datasets to determine the environmental baseline:
* **CORINE Land Cover:** Defines the land use of the affected area (e.g., forest, agricultural, industrial, or mining).
* **LUCAS Topsoil Map:** Provides a 1 km resolution profile of heavy metal concentrations inherently present in the soil.

This intersection establishes the specific "source term"—identifying exactly what material burned and what chemical constituents were present in the soil—forming a unique data layer not currently available in the commercial market.

---

##### Land-Use Based Contaminant Profiling
Following the intersection, the pipeline assigns a generalized contaminant profile based on the land-use class. This classification is the core differentiator of the system, recognizing that specific chemical risks vary by fuel source:

| Land-Use Class | Primary Contaminant Focus |
| :--- | :--- |
| **Forestry** | PAHs, organic carbon, and phosphorus. |
| **Agriculture** | Pesticide residues and fertilizer-derived copper ($Cu$) and zinc ($Zn$). |
| **Industrial / Mining** | High-risk heavy metal loads (e.g., $As, Cd, Cr, Hg, Pb$). |
| **Urban Fringe** | Volatile Organic Compounds (VOCs) and benzene. |

---

##### Hydrological Transport Modeling
The transport of these contaminants is modeled using **EU-DEM** elevation data and **EU-Hydro** river networks. By identifying reservoirs within the downstream catchment and integrating **ERA5 rainfall forecasts**, the model estimates slope-driven runoff velocity. This produces specific arrival windows:
* **Days to Weeks:** Arrival of sediment and organic contamination.
* **Months to 2 Years:** Arrival of heavy metal loads.

---

##### Risk Quantification and Interface Delivery
The final output is a localized risk score delivered via a map interface. Each downstream reservoir is assigned a risk profile categorized by contaminant class, providing water management authorities with:
1.  **Probability** of contamination.
2.  **Timing estimates** for arrival.
3.  **Specific chemical threats** based on the upstream burn profile.

---

## 6. Conclusion & Future Roadmap
By turning complex satellite imagery into a simple **"Risk Score,"** we empower Rensurance Businesses, Governmental Bodies and Environmental Consulting Firms to move from a reactive to a proactive stance in a specific underdeveloped niche, that currently holds no stakeholder. 


---

### 👥 Team Contributions
* **Iva Jefremova:** 
* **Aleksei Pankov:** 
* **Oskar Podkowa:** 
#### The team displays collective contribution to the code,the business model plan and the presentation

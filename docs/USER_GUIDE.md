# Fatal Flaw Analyzer — User Guide

**For energy developers, site screeners, and GIS analysts**

---

## What Is Fatal Flaw?

The Fatal Flaw Analyzer is a tool that helps you quickly screen candidate sites for Solar, Wind, Battery Storage (BESS), or Data Center projects. It checks your site boundary against 15 official government datasets and tells you:

- **Overall Risk Score (0–100):** How constrained this site is. Lower is better.
- **Fatal Flag:** Whether the site hits a "show-stopper" constraint that makes the project legally or practically impossible without major intervention.
- **Top Constraints:** Which specific issues are driving the risk score.
- **PDF Report:** A professional 4-page document you can share with your team or include in a feasibility package.

---

## Step 1: Open QGIS and Load Your Site

1. Open **QGIS** (version 3.28 or newer).
2. Load your candidate site polygon. This can be:
   - A shapefile (`.shp`)
   - A GeoPackage (`.gpkg`)
   - A GeoJSON file (`.geojson`)
   - Any polygon layer already in your project

   Go to **Layer → Add Layer → Add Vector Layer**, browse to your file, and click **Add**.

3. Your site polygon will appear on the map.

> **Tip:** Make sure your polygon is in a geographic coordinate system (WGS84 / EPSG:4326 is ideal). The tool reprojects automatically, but a correct CRS prevents unexpected results.

---

## Step 2: Open the Fatal Flaw Analyzer Panel

Click the **⚡ shield icon** in the QGIS toolbar, or go to:

**Plugins → Fatal Flaw Analyzer → Fatal Flaw Analyzer**

A panel opens on the right side of your screen.

---

## Step 3: Configure Your Assessment

In the panel, you'll see three settings:

### Polygon Layer
Use the dropdown to select the layer containing your site boundary. Only polygon layers appear in this list.

### Site Type
Choose the type of project you're screening:

| Type | Use When |
|------|----------|
| **Solar** | Utility-scale solar PV (>1 MW) |
| **Wind** | Wind farm or single turbine projects |
| **BESS** | Battery energy storage systems |
| **Datacenter** | Data centers or large compute facilities |

The site type changes which constraints are weighted more heavily. For example, "Datacenter" gives extra weight to substation proximity because power reliability is critical.

### Analyze
Choose whether to analyze:
- **Selected features:** Only the polygons you've selected in QGIS (recommended — select your site first using the selection tool)
- **All features:** Every polygon in the layer

> **Best practice:** Use the QGIS selection tool (click the polygon on the map) before running the analysis, then choose "Selected features."

---

## Step 4: Run the Analysis

Click **🔍 Analyze Site**.

A progress bar appears. The analysis typically completes in **under 1 second** once data is loaded. If it takes longer than 30 seconds, check that the API server is running (see Troubleshooting).

---

## Step 5: Read Your Results

### Risk Score
A large colored number appears at the top of the results panel:

| Color | Score Range | Meaning |
|-------|-------------|---------|
| 🟢 **Green** | 0 – 25 | **Low Risk.** Few or minor constraints. Proceed to detailed due diligence. |
| 🟡 **Yellow** | 26 – 50 | **Moderate Risk.** Some constraints present. Mitigation likely possible. |
| 🟠 **Orange** | 51 – 75 | **High Risk.** Significant constraints. Detailed engineering/legal review needed. |
| 🔴 **Red** | 76 – 100 | **Very High / Fatal.** Major constraints or fatal flag. Likely not viable without significant re-scoping. |

### Fatal Flag
Below the score, you'll see one of two messages:

- ✅ **No Fatal Constraints** — No show-stoppers detected. The score reflects the degree of mitigation required.
- ⛔ **FATAL FLAW DETECTED** — The site intersects at least one constraint that makes the project legally or practically impossible at this location. The name of the fatal constraint is shown (e.g., "critical_habitat", "tribal_lands").

**What makes a constraint "fatal"?**

| Constraint | Why Fatal |
|------------|-----------|
| Critical Habitat | ESA Section 7 consultation almost certainly results in jeopardy finding |
| Wilderness Areas | Wilderness Act prohibits all development |
| Tribal Lands | Sovereign nation — project would require formal government-to-government consultation and tribal approval |
| National Park / DOD (Federal Lands) | NPS/DOD lands are closed to commercial energy development |
| Superfund Sites (EPA NPL) | Strict cleanup liability; development prohibited without EPA approval |
| PAD-US GAP Status 1 & 2 | Strict conservation status; development incompatible with management objectives |

### Top Constraints Table
The table shows the **top 5 constraints** by their contribution to your risk score:

| Column | Meaning |
|--------|---------|
| **Layer** | Name of the constraint dataset |
| **Area (ac)** | Acres of your site that overlap this constraint |
| **% Site** | What percentage of your total site area is affected |
| **Score** | This constraint's contribution to the overall risk score (0–100 scale) |

Rows in red indicate fatal constraints.

### Map Overlay
After analysis, your site polygon is recolored on the QGIS map canvas to match its risk level (green/yellow/orange/red). This helps when you're comparing multiple candidate sites.

---

## Step 6: Generate a PDF Report

Click **📄 Generate PDF** to create a professional report.

A save dialog appears. Choose where to save the PDF, then click **Save**.

### What's in the Report?

**Page 1 — Executive Summary**
- Site name, type, area, assessment date
- Large risk score with color indicator
- Fatal flag status and which constraints triggered it
- Risk scale legend

**Page 2 — Top Constraint Analysis**
- Table of top constraints with area, percentage, and contribution score
- Horizontal bar chart showing relative contribution of each top constraint

**Page 3 — Site Map**
- Map view showing the site location in context
- Constraint layers visible in your current QGIS project are shown

**Page 4 — Complete Results**
- All 15 constraint layers in a detailed table
- Shows intersection status, area, distance to nearest feature, score, and weight for every layer

---

## Understanding the Risk Score in Depth

### How Scores Are Calculated

Each constraint layer contributes a score based on:

**For area-based constraints** (wetlands, floodplains, protected areas, etc.):
> Score contribution = Layer Weight × (Overlap Area ÷ Total Site Area)

Example: If 30% of your site overlaps with wetlands (weight 0.25):
> 0.25 × 0.30 = 0.075 → normalized to about 7.5 points

**For distance-based constraints** (transmission lines, substations):
> Closer = LOWER risk for grid infrastructure (favorable proximity)
> Closer = HIGHER risk for contaminated sites (hazard proximity)

**Overall score:**
> Sum of all layer contributions ÷ Maximum possible score × 100

### What the Weights Mean

Weights (0–1) represent the relative importance of each constraint for your site type. Higher weight = larger potential contribution to the overall score. Weights are set by your platform administrator and can be customized per site type.

---

## Tips for Better Screening

### Draw Accurate Boundaries
The accuracy of your risk assessment depends on the accuracy of your site boundary. Include the entire project footprint — not just the panel area, but also roads, substations, and setbacks.

### Compare Multiple Sites
Load several candidate polygons in one layer. Select them one at a time and run the analysis on each. The color-coded overlay makes it easy to compare at a glance.

### Use the Right Site Type
A wind project scored as "solar" may underweight slope constraints (wind often favors ridgelines). Always choose the correct site type for accurate relative weighting.

### Check the Distance Layers
For grid-connected projects, look at the **transmission_lines** and **substations** rows in the full results table. If `min_distance_meters` is large (>8000m), interconnection costs will be high — even if the site has no fatal constraints.

### Fatal ≠ Impossible (Usually)
A fatal flag from this tool means **automatic disqualification in Phase I screening**. It does NOT mean the project is absolutely impossible. Some fatal constraints (like certain federal land leases) can be navigated through formal processes. Use this tool to filter your portfolio quickly, then apply legal and engineering judgment to edge cases.

---

## Troubleshooting

### "Cannot connect to API"
1. Make sure the Fatal Flaw API server is running: `docker-compose up fastapi`
2. Check the API URL in **Plugins → Fatal Flaw Analyzer → Settings**: default is `http://localhost:8000`
3. Try the Test Connection button in Settings

### Analysis takes more than 30 seconds
- Check that the constraint data has been loaded into the database (ETL must have run)
- Ask your administrator to verify the API health: `curl http://localhost:8000/health`

### "Site geometry is outside CONUS bounds"
Your polygon is outside the Continental United States (Hawaii, Alaska, Puerto Rico, or offshore). This tool only covers the Lower 48 states.

### "Site area below minimum"
Your polygon is smaller than 1 acre. Either the geometry is incorrectly drawn or this site is too small for the screening tool.

### Colors don't appear on the map
- The color overlay requires a simple symbol renderer on the layer. If you're using a complex rule-based or categorized renderer, the overlay may not apply. Check **Layer Properties → Symbology** and switch to a Simple Fill renderer.

### PDF is blank or missing the map
- The map on Page 3 captures the current QGIS canvas view. Pan/zoom to show your site before generating the PDF.
- Make sure you have at least one layer visible in QGIS.

---

## Getting Help

- **API documentation:** http://localhost:8000/docs (Swagger UI)
- **Platform issues:** Contact your GIS administrator or platform team
- **Data questions:** See the Data Dictionary in `docs/ADR_and_data_dictionary.md`

---

*Fatal Flaw Geospatial Risk Assessment Platform v1.0.0*

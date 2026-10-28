# Pre-Registration Verification Design: VCS 2369 (Forestal Apepu)

**Document Status**: Pre-registered study design prior to satellite imagery acquisition.  
**Project ID**: VCS 2369  
**Project Name**: Forestal Apepu Carbon Project  
**Country**: Paraguay (Department of San Pedro)  
**Methodology**: AR-ACM0003  
**Registry**: Verra (VCS)  

---

## 1. Project Claims & Documentation

- **Primary Monitoring Document**: Monitoring Report 2 (Verra Doc ID `110200000310052`), covering the 2nd monitoring period: **2020-11-16 to 2022-08-30**.
- **Foundational PDD**: Joint PDD/MR1 (Verra Doc ID `110200000319295`).
- **Claimed Monitored Area**: **2,370.5 ha**, verbatim from Monitoring Report 2, Section 1.1, Page 3:
  > *"Of this total area, 2,370.5 ha are subject to monitoring, and 1,047 ha only for validation as plantations were too young for monitoring."*
- **Total Estate Area**: **3,417.5 ha** (comprising 2,370.5 ha monitored established in 2019–2021, and 1,047.0 ha established in 2022 subject to validation only).
- **Target Species**: Fast-growing commercial *Eucalyptus* plantations planted on former degraded grazing pastures.

---

## 2. Spatial Mask Selection Rule

- **Boundary Source File**: `validation_and_verification_v2.kml` (Verra Doc ID `110200000283779`, stored as `data/projects/2369/boundary.kml`).
- **Layer & Attribute Filter**:
  - The KML layer contains 148 feature records (159 exploded individual polygon parts) with attribute `Año` (float values `2019.0`, `2020.0`, `2021.0`, `2022.0`).
  - **Filter**: `Año in ["2019", "2020", "2021"]`.
  - Exactly **104 features** match this filter. The 44 features planted in 2022 (`Año == 2022`) are excluded from the monitoring mask as they were not subject to MR2 verification.
- **Geometric Processing**:
  - Matched geometries are repaired with Shapely `make_valid` and dissolved into a single unified `MultiPolygon`.
  - Coordinate reference system: UTM Zone 21S (`EPSG:32721`).
  - Dissolved mask area: **2,404.81 ha** (within 1.4% of the claimed 2,370.5 ha).
  - Mask bounding box: 10.92 km (E-W) x 16.25 km (N-S).

---

## 3. Reference Ring Construction Rule

- **Buffer Specifications**:
  - Outer buffer distance: **5,000 m**.
  - Inner buffer distance: **1,000 m**.
- **Exclusion Geometry**:
  - The dissolved spatial union of **ALL 148 features (159 polygons)** from the estate boundary file (including the 2022 unmonitored cohorts and non-monitored management blocks) serves as the exclusion footprint.
  - Ring formula: `Ring = buffer(outer, 5000m) - buffer(exclusion_union, 1000m)`.
- **Integrity Verification**:
  - Ring area in EPSG:32721: **27,244.60 ha**.
  - Ring bounding box: 20.91 km (E-W) x 26.25 km (N-S).
  - Zero-overlap guarantee: Intersection between the reference ring and each of the 159 estate polygons is strictly **0.0000 ha** (0 intersecting polygons).

---

## 4. Natural Forest Allowance

- **Allowance Value**: **0.0 ha**.
- **Justification**:
  - Document review of PDD and MR2 confirms that production plantation blocks are managed for commercial timber/pulpwood.
  - Monitored strata represent exclusively planted *Eucalyptus* cohorts.
  - Native gallery forests and natural riparian buffers on the estate are legally protected under Paraguayan forestry law (Ley 422/73) and excluded from the 2,370.5 ha verified carbon accounting area.
  - Consequently, the natural forest deduction is set to 0.0 ha.

---

## 5. Observation Year and Baseline Period

- **Observation Year**: **2022** (terminal monitoring year).
  - Window: Jun 1 – Aug 31, 2022 (Southern hemisphere winter dry season).
  - Coincides with the conclusion of Monitoring Period 2 (2022-08-30).
- **Baseline Period**: **2019** (dry season Jun 1 – Aug 31, 2019).
  - Planting commenced on **2019-09-15** (PDD Section 1.10).
  - The Jun–Aug 2019 dry-season composite strictly predates all ground preparation, nursery planting, and afforestation activities, providing an uncorrupted pre-project spectral baseline.

---

## 6. Stand Ages & Spectral Maturation Limits at Observation (Jun–Aug 2022)

- **2019 Cohort** (~472.5 ha): Plated Sept–Dec 2019. Stand age at observation is **~2.8–2.9 years**.
- **2020 Cohort** (~450.5 ha): Planted throughout 2020. Stand age at observation is **~1.8–2.2 years**.
- **2021 Cohort** (~1,447.5 ha): Planted throughout 2021. Stand age at observation is **~0.8–1.2 years**.
- **Methodological Caveat**:
  - The 2021 planting cohort represents >60% of the monitored area and is barely ~1 year old at the 2022 observation window.
  - Young *Eucalyptus* stands in subtropical Paraguay typically achieve partial canopy closure between 12 and 18 months, with NDVI values ranging between 0.60 and 0.68. Full spectral saturation (NDVI ≥ 0.70–0.75) is typically only reached at ages 2.5–3.5 years.
  - Lower threshold evaluations (e.g., 0.60 and 0.65) are critical to avoid misclassifying healthy developing 2021 stands as non-forested.

---

## 7. NDVI Threshold Grid

- Following the standardized verification protocol, pixel classification evaluates a 4-tier NDVI grid:
  - **0.60**: Emerging young canopy / open-canopy plantation threshold.
  - **0.65**: Intermediate developing canopy threshold.
  - **0.70**: Primary closed-canopy threshold (central benchmark).
  - **0.75**: High-density mature forest canopy threshold.

---

## 8. Hansen Global Forest Change Cross-Check Applicability

- **GFC Tile**: Primary tile `20S_060W`.
- **Applicability Scope**:
  - `treecover2000`: Validates baseline absence of dense forest prior to project start (<25% tree cover confirms degraded pastureland status).
  - `lossyear`: Cross-checks whether pre-existing woody vegetation or early plantings suffered clear-cut disturbance during the 2019–2022 period.
  - Limitation: Hansen GFC has 30 m resolution and cannot distinguish native forest from commercial timber plantations.

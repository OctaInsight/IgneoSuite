# IgneoSuite

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23919430.svg)](https://doi.org/10.5281/zenodo.23919430) · Web app: https://igneosuite.streamlit.app/

Open-source tools for incomplete igneous geochemical data, from Octa Insight.

This first module tests gap-filling methods on *your own* table, fills the gaps with the method that
works best, and gives every estimated value its own error. It implements the workflow in:

> Abu-Alam, T.S., Güzey, A., Khalil, T.T., Abu-Anber, M., Said, A., Abu-Alam, N.T., Ghoneim, M.
> *When simpler wins: recovering the structure of incomplete geochemical data.* Computers & Geosciences (submitted).

## What it does

1. **Load data** – download the Excel template, or upload your own CSV or Excel file (one sample per row).
   Sample ID, **latitude and longitude are required**; age (Ma) is optional but recommended. Coordinates may
   be decimal degrees or degrees-minutes-seconds with N/S/E/W; they are checked and converted to decimal
   degrees, and samples with missing or invalid locations are listed (fix them, or remove them to continue).
   The samples are then shown on a map and the user is asked whether the locations are correct.
   None of these columns are used in calculations. Blank cells and placeholders (`n.d.`, `b.d.l.`, `-`, `<0.5`) become missing values;
   numbers broken by hidden spaces are recovered and counted.
2. **Missing values** – share missing per variable, the missingness pattern, co-missingness (φ) between
   variables, and whether element groups such as the REE are reported all-or-nothing.
3. **Test methods** – two tests with their own run buttons (test 1: scattered gaps; test 2: block gaps,
   available once test 1 is done). Tests run in the background, so users can look at other steps; a panel
   shows progress, elapsed and expected time, a reminder not to refresh the page, and rotating geology facts.
    hides measured values and re-estimates them with Mean, Median, KNN, MICE, missForest,
   and (with PyTorch) a denoising autoencoder and GAIN. Two designs: scattered gaps and whole-block gaps
   (default block: REE). Reports median |log10(estimate/true)|, share within ×1.25 and ×2, runtime, and
   errors per variable, and recommends a method.
4. **Fill and export** – fills the gaps; for every variable the Excel output has *measured*, *estimated*
   and *± error* columns, plus the complete matrix, the error factor per variable and the test results.
   Measured values are never changed.
5. **Clusters** – optional K-means comparison between a small set of measured variables and the
   gap-filled data (share of samples kept, ARI, cross-table, PCA plots).
6. **Data geometry** – principal components (variance explained, loadings, scores), components needed
   for 80%/90% of the variance, participation ratio, intrinsic dimension (TwoNN), Hopkins statistic,
   nearest-neighbour distance relative to a Gaussian cloud, and (with a Reference column) how often a
   sample's nearest neighbour comes from the same publication.
7. **Clusters** – optional K-means comparison (as before).
8. **Save & share** – every step has a Save button. Saving creates a private project in the database with
   the data and the settings and results of each saved step (statistics, tables and the data behind every
   figure), so the work can be reopened later from its link or project code without recalculating.
   Authors can choose to share the dataset with the IgneoSuite compilation.

Model-based methods work on log10-transformed, standardised values (linear scale for any variable with
zero or negative values).

## Charts

Every chart is interactive: hover to read values (sample number, cluster, coordinates, errors), zoom and
pan. Under each chart, **Figure (PNG, 300 dpi)** downloads a publication-quality version and **Data (CSV)**
the numbers behind it. Step 6 adds a rotatable 3-D view of the clusters on PC1–PC3. No chart needs WebGL, so
everything shows in browsers where 3-D graphics are switched off.

## Run locally

```bash
pip install -r requirements.txt     # drop the torch line to skip DAE and GAIN
streamlit run app.py
```

## Saved projects (Supabase)

* `IgneoSuite_datasets` – one row per project: name, DOI/reference of the compilation, description,
  licence, consent, sharing choice and review status, column mapping, location check.
* `IgneoSuite_samples` – one row per sample (ID, location, age, reference, comment, measured values,
  estimated values and their errors).
* `IgneoSuite_steps` – one row per saved step (`load`, `missing`, `test_scattered`, `test_block`, `fill`,
  `geometry`, `clusters`) with its settings (`params`) and everything it produced (`results`).
* Access: all reads and writes go through the `igneosuite_*` database functions, which require the
  project's private key (only its SHA-256 hash is stored) or, once sign-in exists, the owner's account.

## Author submissions (earlier version)

Step 6 lets authors submit their dataset to the IgneoSuite database in the Octa Insight Supabase project
(`Octa_projects`), with their name, email, affiliation, title, reference, licence and consent.

* `IgneoSuite_datasets` – one row per submission (metadata, licence, consent, review status
  `submitted` / `approved` / `rejected`, and the author's answer to "are the locations correct?").
* `IgneoSuite_samples` – one row per sample: author's sample ID, `latitude` and `longitude`
  (decimal degrees, WGS84; required), the coordinates as the author wrote them, `age_ma` (Ma, optional), and `measured`, `estimated`, `estimate_error`
  (variable → value). Estimates are stored only if the author filled the gaps in step 4.
* `IgneoSuite_values` – view of the samples in long format (one row per sample and variable).

Latitude, longitude and age columns are chosen in step 1 and never used in calculations. Values outside
±90°, ±180° or 0–4,600 Ma are set to missing. Visitors can only add rows; samples can be added only to a
dataset submitted in the last two hours; nobody can read submissions through the public key.

## Usage records (Supabase)

If Supabase settings are present, the app records anonymous usage in three tables in the
Octa Insight Supabase project (`Octa_projects`): `IgneoSuite_runs` (one row per method test: table size,
share missing, methods, scores), `IgneoSuite_events` (steps used) and `IgneoSuite_feedback` (the form on the
About page). No data values or sample IDs are ever sent. The table definitions are in
`supabase/migrations/`. Anonymous visitors can only add rows; they cannot read, change or delete any.

To switch it on, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (local) or paste its
contents into *App settings → Secrets* on Streamlit Community Cloud. Without it the app runs the same and
records nothing.

## Tests

```bash
pip install pytest
pytest -q
```

The tests use a synthetic table (`tests/make_demo.py`); no real data are bundled.

## Deploy

Streamlit Community Cloud: point it at this repository and `app.py`. Upload limit is set in
`.streamlit/config.toml` (50 MB).

## Layout

```
app.py                 Streamlit entry point
igneosuite/io.py       reading and cleaning tables
igneosuite/diagnose.py missing-value description
igneosuite/imputers.py the seven methods
igneosuite/validate.py masking tests and scores
igneosuite/errors.py   element-specific errors for each estimate
igneosuite/export.py   Excel and CSV output
igneosuite/cluster.py  optional K-means comparison
igneosuite/plots.py    figures (paper colours, no text below 7 pt)
igneosuite/telemetry.py anonymous usage records and feedback (Supabase)
igneosuite/submit.py   author submissions (Supabase)
igneosuite/location.py coordinate parsing and checks, map view
igneosuite/template.py downloadable Excel template
igneosuite/ui.py       interface; render(user=None) for the future portal
supabase/migrations/   SQL for the IgneoSuite_ tables
portal/README.md       plan for the Octa Insight portal (Supabase)
```

## How to cite

Please cite the paper and the software (GitHub's "Cite this repository" button uses `CITATION.cff`):

> Abu-Alam, T.S., Güzey, A., Khalil, T.T., Abu-Anber, M., Said, A., Abu-Alam, N.T., Ghoneim, M., 2026. When simpler
> wins: recovering the structure of incomplete geochemical data. Computers & Geosciences (submitted).

> Abu-Alam, T.S., Güzey, A., Khalil, T.T., Abu Anbar, M., Masoud, A.E., Abu-Alam, N.E.T., Ghoneim, M.F., 2026.
> IgneoSuite 1.0.0: an open-source application for testing, filling and exploring gaps in igneous geochemical data.
> Zenodo. https://doi.org/10.5281/zenodo.23919430. Web app: https://igneosuite.streamlit.app/

## Licence

Copyright (C) 2026 Octa Insight. Produced by Octa Systems.

IgneoSuite is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General
Public License as published by the Free Software Foundation, version 3 only (AGPL-3.0-only). It is distributed in the
hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See `LICENSE` for the full text.

Because the AGPL covers use over a network, anyone who runs a modified version of IgneoSuite as a web service must
offer its users the corresponding source code. The app links to this repository from its sidebar and About page.

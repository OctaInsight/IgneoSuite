# IgneoSuite

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
6. **Submit to database** – authors can share their dataset (with location and age) with the
   IgneoSuite compilation.

Model-based methods work on log10-transformed, standardised values (linear scale for any variable with
zero or negative values).

## Run locally

```bash
pip install -r requirements.txt     # drop the torch line to skip DAE and GAIN
streamlit run app.py
```

## Author submissions (Supabase)

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

## Licence

MIT (see `LICENSE`).

# IgneoSuite

Open-source tools for incomplete igneous geochemical data, from Octa Insight.

This first module tests gap-filling methods on *your own* table, fills the gaps with the method that
works best, and gives every estimated value its own error. It implements the workflow in:

> Abu-Alam, T.S., Güzey, A., Khalil, T.T., Abu-Anber, M., Said, A., Abu-Alam, N.T., Ghoneim, M.
> *When simpler wins: recovering the structure of incomplete geochemical data.* Computers & Geosciences (submitted).

## What it does

1. **Load data** – CSV or Excel, one sample per row. Pick the sample-ID column (never used in calculations)
   and the variables. Blank cells and placeholders (`n.d.`, `b.d.l.`, `-`, `<0.5`) become missing values;
   numbers broken by hidden spaces are recovered and counted.
2. **Missing values** – share missing per variable, the missingness pattern, co-missingness (φ) between
   variables, and whether element groups such as the REE are reported all-or-nothing.
3. **Test methods** – hides measured values and re-estimates them with Mean, Median, KNN, MICE, missForest,
   and (with PyTorch) a denoising autoencoder and GAIN. Two designs: scattered gaps and whole-block gaps
   (default block: REE). Reports median |log10(estimate/true)|, share within ×1.25 and ×2, runtime, and
   errors per variable, and recommends a method.
4. **Fill and export** – fills the gaps; for every variable the Excel output has *measured*, *estimated*
   and *± error* columns, plus the complete matrix, the error factor per variable and the test results.
   Measured values are never changed.
5. **Clusters** – optional K-means comparison between a small set of measured variables and the
   gap-filled data (share of samples kept, ARI, cross-table, PCA plots).

Model-based methods work on log10-transformed, standardised values (linear scale for any variable with
zero or negative values).

## Run locally

```bash
pip install -r requirements.txt     # drop the torch line to skip DAE and GAIN
streamlit run app.py
```

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
igneosuite/ui.py       interface; render(user=None) for the future portal
portal/README.md       plan for the Octa Insight portal (Supabase)
```

## Licence

MIT (see `LICENSE`).

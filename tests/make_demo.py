"""Write a small synthetic table (not real data) for tests and demos."""
import numpy as np, pandas as pd
REE = ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"]


def demo(n=300, seed=1):
    rng = np.random.default_rng(seed)
    g = rng.integers(0, 3, n)
    si = np.array([62, 70, 75])[g] + rng.normal(0, 2.5, n)
    d = {"Sample": [f"S{i:04d}" for i in range(n)], "SiO2 (wt.%)": si,
         "TiO2 (wt.%)": np.exp(np.log(0.9) - 0.08 * (si - 62) + rng.normal(0, .2, n)),
         "Al2O3 (wt.%)": 18 - 0.12 * (si - 62) + rng.normal(0, .6, n),
         "MgO (wt.%)": np.exp(np.log(2.5) - 0.12 * (si - 62) + rng.normal(0, .3, n)),
         "K2O (wt.%)": 2 + 0.12 * (si - 62) + rng.normal(0, .3, n),
         "Rb (ppm)": np.exp(np.log(60) + 0.08 * (si - 62) + rng.normal(0, .3, n)),
         "Sr (ppm)": np.exp(np.log(500) - 0.12 * (si - 62) + rng.normal(0, .3, n)),
         "Zr (ppm)": np.exp(np.log(180) + rng.normal(0, .3, n))}
    la = np.exp(np.log(25) + 0.05 * (si - 62) + rng.normal(0, .3, n))
    slope = np.array([1.0, 0.85, 0.7])[g]
    for k, e in enumerate(REE):
        d[e] = la * np.exp(-0.18 * k * slope) * (0.5 if e == "Eu" else 1) * np.exp(rng.normal(0, .08, n))
    df = pd.DataFrame(d)
    vals = df.columns[1:]
    m = rng.random((n, len(vals))) < 0.08
    df[vals] = df[vals].mask(m)
    df.loc[rng.random(n) < 0.35, REE] = np.nan
    df = df.astype(object)
    df.iloc[3, 2] = "n.d."; df.iloc[5, 7] = "1 234"; df.iloc[8, 6] = "<0.5"
    return df


if __name__ == "__main__":
    demo().to_csv("demo_synthetic.csv", index=False)

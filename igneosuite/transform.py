"""Log-standardisation used by the model-based imputers."""
import numpy as np


class LogStandardiser:
    """log10 for strictly positive columns, linear otherwise; then z-scores from observed values."""

    def fit(self, X: np.ndarray):
        self.log = np.array([bool(np.all(X[~np.isnan(X[:, j]), j] > 0)) for j in range(X.shape[1])])
        L = self._fwd(X)
        self.mu = np.nanmean(L, 0)
        sd = np.nanstd(L, 0)
        self.sd = np.where((sd > 0) & np.isfinite(sd), sd, 1.0)
        self.mu = np.where(np.isfinite(self.mu), self.mu, 0.0)
        return self

    def _fwd(self, X):
        L = X.astype(float).copy()
        for j in np.where(self.log)[0]:
            L[:, j] = np.log10(X[:, j])
        return L

    def transform(self, X):
        return (self._fwd(X) - self.mu) / self.sd

    def inverse(self, Z):
        L = Z * self.sd + self.mu
        X = L.copy()
        for j in np.where(self.log)[0]:
            X[:, j] = 10 ** L[:, j]
        return X

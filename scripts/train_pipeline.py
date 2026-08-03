import json
import warnings
from pathlib import Path
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, StratifiedKFold, RandomizedSearchCV
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import VarianceThreshold
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.metrics import (roc_auc_score, roc_curve, precision_recall_curve,
                              average_precision_score, confusion_matrix,
                              recall_score, precision_score, f1_score, accuracy_score)
from xgboost import XGBClassifier

RANDOM_STATE = 42
np.random.seed(RANDOM_STATE)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---------- 1. Load ----------
df = pd.read_csv(DATA_DIR / "uci-secom.csv")
df["Time"] = pd.to_datetime(df["Time"])
y_raw = df["Pass/Fail"].map({-1: 0, 1: 1})  # 0=pass, 1=fail
X_raw = df.drop(columns=["Time", "Pass/Fail"])

n_samples, n_features_raw = X_raw.shape
fail_count = int(y_raw.sum())
pass_count = int((y_raw == 0).sum())

# ---------- 2. EDA stats ----------
missing_pct = X_raw.isna().mean().sort_values(ascending=False)
missing_hist, missing_bin_edges = np.histogram(missing_pct.values * 100, bins=10, range=(0, 100))

# ---------- 3. Preprocessing ----------
# drop columns with >40% missing
keep_cols = missing_pct[missing_pct <= 0.40].index
X = X_raw[keep_cols].copy()
cols_dropped_missing = n_features_raw - X.shape[1]

# impute remaining with median
imputer = SimpleImputer(strategy="median")
X_imp = pd.DataFrame(imputer.fit_transform(X), columns=X.columns)

# drop near-zero variance columns
vt = VarianceThreshold(threshold=1e-6)
vt.fit(X_imp)
cols_kept_var = X_imp.columns[vt.get_support()]
cols_dropped_var = X_imp.shape[1] - len(cols_kept_var)
X_var = X_imp[cols_kept_var]

n_features_final_pre_selection = X_var.shape[1]

# ---------- 4. Train/test split (before further feature selection to avoid leakage) ----------
X_train, X_test, y_train, y_test = train_test_split(
    X_var, y_raw, test_size=0.25, stratify=y_raw, random_state=RANDOM_STATE
)

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)

# ---------- 5. Feature selection via RandomForest importance (fit on train only) ----------
rf_selector = RandomForestClassifier(
    n_estimators=300, class_weight="balanced_subsample", random_state=RANDOM_STATE, n_jobs=-1
)
rf_selector.fit(X_train_s, y_train)
importances = pd.Series(rf_selector.feature_importances_, index=X_train.columns).sort_values(ascending=False)
TOP_K = 40
top_features = importances.head(TOP_K).index.tolist()
top_feature_idx = [X_train.columns.get_loc(c) for c in top_features]

X_train_sel = X_train_s[:, top_feature_idx]
X_test_sel = X_test_s[:, top_feature_idx]

# ---------- 6. Model definitions + tuning ----------
cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=RANDOM_STATE)
scale_pos_weight = pass_count / fail_count

model_specs = {
    "Logistic Regression": (
        LogisticRegression(class_weight="balanced", max_iter=2000, random_state=RANDOM_STATE),
        {"C": [0.01, 0.03, 0.1, 0.3, 1, 3, 10]},
    ),
    "Random Forest": (
        RandomForestClassifier(class_weight="balanced_subsample", random_state=RANDOM_STATE, n_jobs=-1),
        {
            "n_estimators": [200, 400, 600],
            "max_depth": [4, 6, 8, 12, None],
            "min_samples_leaf": [1, 2, 4, 8],
            "max_features": ["sqrt", "log2", 0.5],
        },
    ),
    "Gradient Boosting": (
        GradientBoostingClassifier(random_state=RANDOM_STATE),
        {
            "n_estimators": [100, 200, 300],
            "learning_rate": [0.01, 0.03, 0.1, 0.2],
            "max_depth": [2, 3, 4],
            "subsample": [0.7, 0.85, 1.0],
        },
    ),
    "XGBoost": (
        XGBClassifier(
            eval_metric="logloss", random_state=RANDOM_STATE,
            scale_pos_weight=scale_pos_weight, n_jobs=-1
        ),
        {
            "n_estimators": [150, 300, 450],
            "max_depth": [2, 3, 4, 6],
            "learning_rate": [0.01, 0.03, 0.1, 0.2],
            "subsample": [0.7, 0.85, 1.0],
            "colsample_bytree": [0.6, 0.8, 1.0],
        },
    ),
    "SVM (RBF)": (
        SVC(kernel="rbf", class_weight="balanced", probability=True, random_state=RANDOM_STATE),
        {"C": [0.1, 1, 3, 10, 30], "gamma": ["scale", "auto", 0.001, 0.01]},
    ),
}

results = {}
fitted_models = {}

for name, (estimator, param_dist) in model_specs.items():
    search = RandomizedSearchCV(
        estimator, param_dist, n_iter=8, scoring="roc_auc",
        cv=cv, random_state=RANDOM_STATE, n_jobs=-1, refit=True
    )
    search.fit(X_train_sel, y_train)
    best_model = search.best_estimator_
    fitted_models[name] = best_model

    y_proba = best_model.predict_proba(X_test_sel)[:, 1]

    fpr, tpr, _ = roc_curve(y_test, y_proba)
    prec, rec, pr_thresh = precision_recall_curve(y_test, y_proba)

    # find threshold that maximizes F1 (better fit for rare-defect detection than default 0.5)
    f1_scores = np.divide(
        2 * prec[:-1] * rec[:-1], prec[:-1] + rec[:-1],
        out=np.zeros_like(prec[:-1]), where=(prec[:-1] + rec[:-1]) != 0
    )
    best_f1_idx = int(np.argmax(f1_scores)) if len(f1_scores) else 0
    best_threshold = float(pr_thresh[best_f1_idx]) if len(pr_thresh) else 0.5

    y_pred_default = (y_proba >= 0.5).astype(int)
    y_pred_opt = (y_proba >= best_threshold).astype(int)
    cm = confusion_matrix(y_test, y_pred_opt).tolist()

    results[name] = {
        "best_params": search.best_params_,
        "cv_best_auc": float(search.best_score_),
        "test_auc": float(roc_auc_score(y_test, y_proba)),
        "test_avg_precision": float(average_precision_score(y_test, y_proba)),
        "optimal_threshold": round(best_threshold, 4),
        "test_accuracy": float(accuracy_score(y_test, y_pred_opt)),
        "test_precision": float(precision_score(y_test, y_pred_opt, zero_division=0)),
        "test_recall": float(recall_score(y_test, y_pred_opt, zero_division=0)),
        "test_f1": float(f1_score(y_test, y_pred_opt, zero_division=0)),
        "default_threshold_recall": float(recall_score(y_test, y_pred_default, zero_division=0)),
        "roc_curve": {"fpr": fpr.tolist()[::3], "tpr": tpr.tolist()[::3]},
        "pr_curve": {"precision": prec.tolist()[::3], "recall": rec.tolist()[::3]},
        "confusion_matrix": cm,  # [[TN, FP],[FN, TP]]
    }
    print(name, "AUC:", round(results[name]["test_auc"],3),
          "| thr:", round(best_threshold,3),
          "| recall:", round(results[name]["test_recall"],3),
          "| precision:", round(results[name]["test_precision"],3))

# ---------- 7. Best model feature importances for dashboard ----------
# pick by F1 at optimized threshold - more meaningful than raw AUC for rare-defect detection
best_name = max(results, key=lambda k: results[k]["test_f1"])
best_model = fitted_models[best_name]
best_threshold_final = results[best_name]["optimal_threshold"]

if hasattr(best_model, "feature_importances_"):
    imp = pd.Series(best_model.feature_importances_, index=top_features).sort_values(ascending=False)
elif hasattr(best_model, "coef_"):
    imp = pd.Series(np.abs(best_model.coef_[0]), index=top_features).sort_values(ascending=False)
else:
    imp = importances[top_features].sort_values(ascending=False)

top_15_features = imp.head(15)

# ---------- 8. Control-chart style data: top feature over time, pass vs fail ----------
top1_feature = top_15_features.index[0]
cc_df = df[["Time", top1_feature, "Pass/Fail"]].copy()
cc_df = cc_df.sort_values("Time").reset_index(drop=True)
cc_df["idx"] = range(len(cc_df))
cc_sample = cc_df.iloc[::4]  # thin for display
mean_val = cc_df[top1_feature].mean()
std_val = cc_df[top1_feature].std()

control_chart = {
    "feature": top1_feature,
    "mean": float(mean_val),
    "ucl": float(mean_val + 3 * std_val),
    "lcl": float(mean_val - 3 * std_val),
    "points": [
        {"idx": int(r["idx"]), "value": None if pd.isna(r[top1_feature]) else float(r[top1_feature]),
         "fail": int(r["Pass/Fail"] == 1)}
        for _, r in cc_sample.iterrows()
    ],
}

# ---------- 9. Simulated "live" prediction samples for dashboard demo ----------
rng = np.random.RandomState(7)
demo_idx = rng.choice(len(X_test_sel), size=12, replace=False)
demo_samples = []
best_proba_all = best_model.predict_proba(X_test_sel)[:, 1]
for i in demo_idx:
    demo_samples.append({
        "true_label": int(y_test.iloc[i]),
        "pred_proba": float(best_proba_all[i]),
        "pred_label": int(best_proba_all[i] >= best_threshold_final),
    })

# ---------- 9b. Full test-set streaming queue (for live monitoring simulation) ----------
stream_records = []
for pos, orig_idx in enumerate(X_test.index):
    stream_records.append({
        "time": df.loc[orig_idx, "Time"].isoformat(),
        "true_label": int(y_test.loc[orig_idx]),
        "pred_proba": float(best_proba_all[pos]),
        "pred_label": int(best_proba_all[pos] >= best_threshold_final),
        "feature_value": None if pd.isna(df.loc[orig_idx, top1_feature]) else float(df.loc[orig_idx, top1_feature]),
    })
stream_records.sort(key=lambda r: r["time"])

# ---------- 10. Assemble output JSON ----------
output = {
    "dataset": {
        "n_samples": n_samples,
        "n_features_raw": n_features_raw,
        "fail_count": fail_count,
        "pass_count": pass_count,
        "fail_rate_pct": round(fail_count / n_samples * 100, 2),
    },
    "preprocessing": {
        "missing_hist_counts": missing_hist.tolist(),
        "missing_hist_edges": missing_bin_edges.tolist(),
        "cols_dropped_missing_gt40pct": int(cols_dropped_missing),
        "cols_dropped_zero_variance": int(cols_dropped_var),
        "features_after_cleaning": int(n_features_final_pre_selection),
        "features_selected_top_k": TOP_K,
    },
    "models": results,
    "best_model": best_name,
    "best_threshold": best_threshold_final,
    "top_features": [{"name": k, "importance": float(v)} for k, v in top_15_features.items()],
    "control_chart": control_chart,
    "demo_samples": demo_samples,
    "stream_queue": stream_records,
}

out_path = DATA_DIR / "dashboard_data.json"
with open(out_path, "w") as f:
    json.dump(output, f)

print("\nBest model:", best_name)
print(f"Saved {out_path}")

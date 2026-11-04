"""Data profile: the tables behind the numbers in results/RESULTS.md (section 3).

It only reads the three staged files and prints tables. It writes nothing.

    uv run python experiments/data_profile.py

The numbers in RESULTS.md come from these tables. Run it to see them yourself.
"""

import sys

import pandas as pd

from taxi_revenue import config, pipeline

PARTS = [
    "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
    "improvement_surcharge", "congestion_surcharge", "cbd_congestion_fee", "ehail_fee",
]


def load_trips(paths):
    """Read the files into one table with a month column and a few helper columns."""
    frames, columns = [], {}
    for month, path in zip(config.MONTHS, paths):
        frame = pd.read_parquet(path)
        columns[month] = list(frame.columns)
        frame["month"] = month
        frame["size_bytes"] = path.stat().st_size
        frames.append(frame)
    trips = pd.concat(frames, ignore_index=True)
    trips.attrs["columns"] = columns
    trips.attrs["original"] = columns[config.MONTHS[0]]
    trips["pickup"] = pd.to_datetime(trips[config.PICKUP_COLUMN], errors="coerce")
    trips["amount"] = pd.to_numeric(trips[config.AMOUNT_COLUMN], errors="coerce")
    present = [name for name in PARTS if name in trips.columns]
    trips["parts"] = trips[present].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1).round(2)
    trips["inside"] = (trips["pickup"] >= config.WINDOW_START) & (trips["pickup"] < config.WINDOW_END)
    return trips


def month_table(trips):
    """Section 3.2: the three months side by side."""
    original = trips.attrs["original"]
    own_month = trips["pickup"].dt.strftime("%Y-%m") == trips["month"]
    duplicated = trips.groupby("month", group_keys=False)[original].apply(lambda g: g.duplicated())
    flags = pd.DataFrame({
        "month": trips["month"],
        "Empty pickup date": trips["pickup"].isna(),
        "Pickup before the window start": trips["pickup"] < config.WINDOW_START,
        "Pickup on or after the window end": trips["pickup"] >= config.WINDOW_END,
        "Pickup outside the file's own month": trips["pickup"].notna() & ~own_month,
        "Empty amount": trips["amount"].isna(),
        "Negative amount": trips["amount"] < 0,
        "Zero amount": trips["amount"] == 0,
        "Duplicate rows": duplicated,
    })
    counts = flags.groupby("month").sum().T.astype(int)
    by_month = trips.groupby("month")
    same_columns = {m: ("yes" if cols == trips.attrs["original"] else "NO") for m, cols in trips.attrs["columns"].items()}
    table = pd.concat([
        pd.DataFrame([by_month.size()], index=["Trips"]),
        pd.DataFrame([same_columns], index=["Same columns as the first file"]),
        counts,
    ])
    table.loc["Sum of the negative amounts"] = trips[trips["amount"] < 0].groupby("month")["amount"].sum().reindex(table.columns).fillna(0).round(2)
    table.loc["Sum of total_amount (all rows)"] = by_month["amount"].sum().round(2)
    return table


def outside_window(trips):
    """Section 3.3: the trips outside the date window, and what they are worth."""
    outside = trips[~trips["inside"] & trips["pickup"].notna()]
    by_month = outside.groupby(outside["pickup"].dt.strftime("%Y-%m")).size()
    return by_month, len(outside), round(float(outside["amount"].sum()), 2)


def payment_types(trips, mask):
    """Counts by payment type (empty = no value) and file, for the chosen trips."""
    chosen = trips[mask]
    labels = chosen["payment_type"].fillna(-1).astype(int).astype(str).replace("-1", "empty")
    return pd.crosstab(labels, chosen["month"])


def vendor_zero_table(trips):
    """Section 3.5, table A: trips and zero totals per vendor (inside the window)."""
    inside = trips[trips["inside"]]
    table = inside.groupby("VendorID").agg(trips=("amount", "size"), zero_total=("amount", lambda s: int((s == 0).sum())))
    table["zero share (%)"] = (table["zero_total"] / table["trips"] * 100).round(2)
    return table


def parts_equal_table(trips):
    """Section 3.5, table B: how often does total_amount equal the sum of its parts?"""
    normal = trips[trips["inside"] & (trips["amount"] != 0)].copy()
    normal["equal"] = (normal["parts"] - normal["amount"]).abs() <= 0.005
    table = normal.groupby("VendorID").agg(trips=("equal", "size"), equal=("equal", "sum"))
    table["share (%)"] = (table["equal"] / table["trips"] * 100).round(2)
    return table


def zero_parts_table(trips):
    """Section 3.5, table C: for the zero totals, what do the parts add up to?"""
    zero = trips[trips["inside"] & (trips["amount"] == 0)]
    table = zero.groupby("VendorID").agg(
        zero_total=("parts", "size"),
        parts_above_0=("parts", lambda s: int((s > 0).sum())),
        sum_of_parts=("parts", "sum"),
        largest_parts=("parts", "max"),
    )
    table["sum_of_parts"] = table["sum_of_parts"].round(2)
    return table


def zero_days(trips, top=5):
    """Section 3.5, table D: the days with the most zero totals, per file."""
    zero = trips[trips["inside"] & (trips["amount"] == 0)]
    result = {}
    for month, part in zero.groupby("month"):
        counts = part["pickup"].dt.strftime("%Y-%m-%d").value_counts().head(top)
        result[month] = list(counts.items())
    return result


def impact(trips):
    """Section 3.5, table E: the total now, and if zero totals used the sum of their parts."""
    inside = trips[trips["inside"]]
    zero = inside[inside["amount"] == 0]
    now = round(float(inside["amount"].sum()), 2)
    extra = round(float(zero.loc[zero["parts"] > 0, "parts"].sum()), 2)
    return now, extra, round(now + extra, 2)


def other_checks(trips):
    """Section 3.6: payment types left empty, decimals, and the highest amounts."""
    inside = trips[trips["inside"]]
    off_cents = ((inside["amount"] * 100 - (inside["amount"] * 100).round()).abs() > 1e-6).sum()
    empty_type = trips[trips["payment_type"].isna()].groupby("month").size()
    top = trips.nlargest(5, "amount")[["month", "pickup", "trip_distance", "amount", "payment_type"]]
    return int(off_cents), empty_type, top


def show(value):
    if isinstance(value, str):
        return value
    if isinstance(value, float) and not float(value).is_integer():
        return format(value, ",.2f")
    return format(int(value), ",")


def print_frame(frame):
    width = max(len(str(name)) for name in frame.index) + 2
    print(" " * width + "".join(f"{c:>14}" for c in frame.columns))
    for name, row in frame.iterrows():
        print(f"{str(name):<{width}}" + "".join(f"{show(v):>14}" for v in row))


def main():
    paths = pipeline.raw_paths()
    missing = [path.name for path in paths if not path.exists()]
    if missing:
        sys.exit(f"Missing staged file(s): {missing}. Run: uv run taxi-revenue download")
    trips = load_trips(paths)

    print("--- 3.1 the files")
    sizes = trips.groupby("month").agg(bytes=("size_bytes", "first"), trips=("amount", "size"))
    sizes.loc["total"] = sizes.sum()
    print(sizes.to_string())

    print("\n--- 3.2 the three months side by side")
    print_frame(month_table(trips))

    by_month, count, worth = outside_window(trips)
    print("\n--- 3.3 trips outside the date window, by pickup month")
    print(by_month.to_string())
    print(f"{count} trips in total, worth {worth:,.2f}")

    print("\n--- 3.4 negative amounts by payment type (empty = no value)")
    print(payment_types(trips, trips["amount"] < 0).to_string())

    print("\n--- 3.5 A. trips and zero totals per vendor (inside the window)")
    print(vendor_zero_table(trips).to_string())
    print("\n--- 3.5 B. non-zero totals: share where total_amount equals the sum of its parts")
    print(parts_equal_table(trips).to_string())
    print("\n--- 3.5 C. zero totals: what do the parts add up to?")
    print(zero_parts_table(trips).to_string())
    print("\n--- 3.5 D. days with the most zero totals")
    for month, days in zero_days(trips).items():
        print(month + ": " + ", ".join(f"{day} ({n})" for day, n in days))
    now, extra, total = impact(trips)
    print("\n--- 3.5 E. impact if zero totals used the sum of their parts")
    print(f"total now {now:,.2f} | extra {extra:,.2f} | total would be {total:,.2f} (+{extra / now * 100:.3f} %)")
    print("\n--- 3.5 zero amounts by payment type")
    print(payment_types(trips, trips["amount"] == 0).to_string())

    off_cents, empty_type, top = other_checks(trips)
    print("\n--- 3.6 other checks")
    print(f"amounts with more than two decimals (inside the window): {off_cents}")
    print("trips with an empty payment type, per file: " + ", ".join(f"{m} {n:,}" for m, n in empty_type.items()))
    print("the 5 highest amounts:")
    print(top.to_string(index=False))


if __name__ == "__main__":
    main()

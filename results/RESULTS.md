# Results and study notes

This is the long version of the project. The [README](../README.md) is short. This file explains what the data looked like, which decisions I made and why, and what I measured. Where I did not measure something, it says so.

All numbers in this file come from real runs on one Windows computer, with the three files for January to March 2025. Nothing here is estimated unless the text says "estimate" or "guess". The tables in section 3 can be reproduced with `uv run python experiments/data_profile.py`.

## 1. Summary

- The project calculates the **daily revenue** of the NYC green taxi trips of January, February and March 2025.
- I built the same calculation **three times**: with pandas, with polars and with DuckDB. The three results are **exactly identical**: the CSV files are the same byte for byte.
- The real data has **146,486 trips**. After the rules, **146,475 trips on 90 days** are used. Total revenue: **3,395,290.56**.
- Three rules came from looking at the real data first: a date window, keeping negative and zero amounts, and dropping unusable rows. Money is added in whole cents.
- The three engines differ in speed: polars 0.022 s, pandas 0.090 s, DuckDB 0.131 s (0.045 s as one single query). Section 7 shows how I found out why DuckDB was slowest.
- 89 tests check the code. I also broke the code on purpose in a test copy to see if the tests notice.
- One data problem is **not solved**: vendor 6 reports a total of 0 on 160 trips that do have fare parts. It is worth only 0.02 percent of the total, so I documented it and did not change a rule.

## 2. The task and the work

The school brief asks for two things: a script that downloads the first three months of 2025 of the green taxi data into a local staging folder, and an ETL or ELT pipeline that reads the staged files and calculates revenue per day. A bonus is to use Prefect. The brief says the structure and the tools are my choice.

I worked in this order, and I looked at the data before I wrote any calculation:

1. Download one file and look at it (columns, dates, amounts).
2. Download all three files and look at them side by side.
3. Write the rules down, with the numbers behind them.
4. Build the download code, then the three engines, then the output files.
5. Prove that the three results are the same, then measure the time.
6. Add a command line, tests and the Prefect flow.
7. Run an experiment to explain the timing, and look closer at the zero amounts.

## 3. The data

### 3.1 The files

| File | Size in bytes | Trips (rows) |
|---|---|---|
| green_tripdata_2025-01.parquet | 1,178,451 | 48,326 |
| green_tripdata_2025-02.parquet | 1,117,474 | 46,621 |
| green_tripdata_2025-03.parquet | 1,253,510 | 51,539 |
| **Total** | 3,549,435 | **146,486** |

Every file has the same **21 columns**: VendorID, lpep_pickup_datetime, lpep_dropoff_datetime, store_and_fwd_flag, RatecodeID, PULocationID, DOLocationID, passenger_count, trip_distance, fare_amount, extra, mta_tax, tip_amount, tolls_amount, ehail_fee, improvement_surcharge, total_amount, payment_type, trip_type, congestion_surcharge and cbd_congestion_fee. The calculation needs only two of them: `lpep_pickup_datetime` (when the trip started) and `total_amount`.

### 3.2 The three months side by side

| What I checked | January | February | March |
|---|---|---|---|
| Trips | 48,326 | 46,621 | 51,539 |
| Same columns as January | yes | yes | yes |
| Empty pickup date | 0 | 0 | 0 |
| Pickup before 1 January 2025 | 6 | 0 | 0 |
| Pickup on or after 1 April 2025 | 0 | 0 | 5 |
| Pickup outside the file's own month | 43 | 19 | 11 |
| Empty amount | 0 | 0 | 0 |
| Negative amount | 153 | 165 | 160 |
| Sum of the negative amounts | -1,914.16 | -1,698.90 | -2,849.55 |
| Zero amount | 33 | 74 | 147 |
| Duplicate rows | 0 | 0 | 0 |
| Sum of `total_amount` (all rows) | 1,093,822.36 | 1,066,625.78 | 1,235,147.15 |

### 3.3 Trips outside the date window

The task is January to March 2025, but the files hold a few trips from other dates. In the January file, the pickup dates run from 25 December 2024 to 5 February 2025: 6 trips from December and 37 from February. The 37 February trips are inside our three months, so they are kept. The 6 December trips and the 5 trips from April 2025 (in the March file) are not.

These 11 trips are worth **304.73** in total (the total of all rows, 3,395,595.29, minus the total of the used rows, 3,395,290.56).

### 3.4 Negative amounts

There are 478 trips with a negative amount, together -6,462.61. That is 0.19 percent of the total revenue.

The payment types of the negative trips, per file:

| Payment type | January | February | March | Total |
|---|---|---|---|---|
| 3 (no charge) | 107 | 120 | 110 | 337 |
| 4 (dispute) | 42 | 40 | 45 | 127 |
| 2 (cash) | 4 | 5 | 5 | 14 |
| **All negative** | 153 | 165 | 160 | **478** |

The official TLC data dictionary (version of 18 March 2025) says: 0 = Flex Fare trip, 1 = Credit card, 2 = Cash, **3 = No charge, 4 = Dispute**, 5 = Unknown, 6 = Voided trip. So 464 of the 478 negative amounts (97.1 percent) belong to no-charge and disputed trips, which fits the idea of corrections. The other 14 are cash trips. I do not know why a cash trip has a negative amount.

### 3.5 Zero amounts, and vendor 6

There are 254 trips with an amount of exactly 0. The number looks like it jumps in March (33, 74 and 147 trips). I took a closer look, and the jump has a clear cause: a new data provider appears.

The trip records come from three technology providers, shown in the column `VendorID`. According to the data dictionary, 1 is Creative Mobile Technologies, 2 is Curb Mobility, and **6 is Myle Technologies**. Vendor 6 has no trips in the January file (inside the date window). In the February and March files it has 731 and 1,222 trips.

| Vendor | Trips in the window | Zero totals | Share |
|---|---|---|---|
| 1 | 18,883 | 92 | 0.49 percent |
| 2 | 125,639 | 2 | 0.00 percent |
| 6 | 1,953 | 160 | 8.19 percent |
| **All** | **146,475** | **254** | 0.17 percent |

- Vendor 6 causes 50 of the 74 zero totals in February and 110 of the 147 in March. Without vendor 6, the zero totals would be 33, 24 and 37: a steady level.
- The zero-total trips with an empty payment type number 50 (February) and 110 (March). These are exactly the vendor 6 counts, so they are very likely the same trips, but I did not check this row by row.
- **The 160 vendor 6 trips have a total of 0, but they do have fare parts.** Adding up the columns fare_amount, extra, mta_tax, tip_amount, tolls_amount, improvement_surcharge, congestion_surcharge, cbd_congestion_fee and ehail_fee gives more than 0 on all 160 trips. Together the parts are worth **677.15** (about 4.23 per trip, the largest is 10.64). That is **0.02 percent** of the total.
- The 92 zero totals of vendor 1 are different: their parts also add up to 0. These look like real zero trips.
- On 20 March there are 28 zero totals, many more than on any other day in March (the next-highest day has 9). They come from vendor 1 (18) and vendor 6 (10). I do not know the reason.

**Does `total_amount` equal the sum of its parts?** I checked it for all trips with a non-zero total. For vendor 2 it does in 98.55 percent of the trips (123,814 of 125,637). For vendor 1 it does in only 1.65 percent (310 of 18,791), and for vendor 6 in none of 1,793 trips. I did not find out why. It may be a column I did not add up, or a different way of calculating. Because of this, I do **not** recalculate totals from their parts: the result would be numbers that no vendor reported.

### 3.6 Other things I noticed

- **No duplicate rows** in any file.
- **Payment type empty:** 1,836 trips in January (3.8 percent), 2,517 in February (5.4 percent) and 3,549 in March (6.9 percent), which is 7,902 in total. The share grows from month to month. The dictionary has no "empty" code. I did not look into the reason, because the calculation does not use the payment type. The vendor 6 zero totals with an empty payment type (160) are only a small part of these trips.
- **The highest amounts** across the three files are 642.14 (176.49 miles, paid in cash), 579.50 (147.40 miles, cash), 473.10, 403.86 and 401.90. Most are long trips. The 473.10 trip has a distance of only 0.78 miles and payment type 4 (dispute), which looks odd. In January, I also saw an amount of 251.00 with a distance of 0.00. I cannot prove that these are wrong, so I keep them.
- **Amounts have at most two decimals.** No amount has more than two decimals (checked on all rows that are used).

### 3.7 What "revenue" means here

Revenue in this project is the sum of `total_amount`. According to the data dictionary, `total_amount` is the total amount charged to passengers and **does not include cash tips**. So the real money that drivers and vendors received can be higher than our number. The data dictionary also says that the tip amount is filled in automatically for credit card tips, and that cash tips are not included.

## 4. The decisions

Each decision has the problem, the options, my choice, the reason and the evidence.

### D1. The date window

- **Problem:** the files hold trips from other dates (11 trips outside January to March).
- **Options:** (a) keep every trip under its own pickup date, so December and April days appear in the result; (b) keep only trips inside January to March.
- **Choice:** (b), from 1 January 2025 00:00:00 up to, but **not including**, 1 April 2025 00:00:00.
- **Reason:** the task is three months. The end is not included, so that a trip at exactly midnight on 1 April belongs to April and no trip is counted twice or lost.
- **Evidence:** 11 trips dropped, worth 304.73. A test checks both edges (31 December 23:59:59 is out, 1 January 00:00:00 is in, 31 March 23:59:59 is in, 1 April 00:00:00 is out).

### D2. Keep negative and zero amounts

- **Problem:** 478 negative and 254 zero amounts.
- **Options:** (a) drop them; (b) use the absolute value; (c) keep them as they are.
- **Choice:** (c). The result is **net revenue**.
- **Reason:** 464 of the 478 negative amounts (97 percent) are no-charge or disputed trips, so they look like corrections. Dropping or flipping them would hide real money movements. The zero amounts are too few (0.17 percent) to matter, and I could not explain all of them.
- **Evidence:** the negative amounts add up to -6,462.61 (0.19 percent). The zero totals with real fare parts are worth 677.15 (0.02 percent). The metadata file counts both groups, so nothing is hidden.
- **What I did not do:** I did not recalculate the 160 vendor 6 totals from their parts (section 3.5). The numbers are tiny, and the recalculation would not be reliable.

### D3. Trips without a pickup date or without an amount

- **Problem:** such a trip cannot be assigned to a day, or has an unknown amount.
- **Choice:** drop it and count it in the metadata (`rows_dropped_missing_values`).
- **Reason:** a missing amount is **unknown**, not zero. Counting it as zero would pretend that we know the revenue.
- **Evidence:** in this data it is 0 trips. The rule exists for safety, and the tests check it with empty dates, empty amounts and a real NaN ("not a number") amount.

### D4. Money is added in whole cents

- **Problem:** adding decimals can give tiny differences in the last digit, depending on the order of the additions. For instance, 0.1 + 0.2 gives 0.30000000000000004. Three tools add in different orders, so they could disagree.
- **Choice:** convert each amount to whole cents (an integer), add the integers, and divide by 100 at the end.
- **Reason:** integer sums are exact, so all three engines must give the same number.
- **Evidence:** no amount in the data has more than two decimals (the metadata field `amounts_not_in_whole_cents` is 0), so the conversion loses nothing. A test checks that 0.10 + 0.20 gives exactly 0.3.

### D5. The staging folder and the download checks

- **Problem:** a download can fail halfway, or an error page can arrive instead of data.
- **Choice:** the download saves each file under a temporary name (`.part`), checks that it starts and ends with the 4 bytes `PAR1` (the marker of every parquet file), and only then gives it its final name. Files that are already there are kept, unless `--force` is used.
- **Reason:** a half file or an error page should never look like finished data. The calculation reads only the staged files from disk, never from the internet.
- **Evidence:** 8 tests, run against a small test server on the same computer: a fake file is refused and nothing is left behind, a missing file gives an HTTP error and nothing is left behind, and a broken existing file is refused.

### D6. Three engines, and the default

- **Problem:** the task allows ETL or ELT, and the tool is my choice.
- **Choice:** build all three on purpose. pandas and polars are ETL, DuckDB is ELT. The default engine is **pandas**.
- **Reason:** I wanted a study that compares them on the same task, and the school asks to explain ETL against ELT. pandas is the default because it is the simplest to read, and the data is small.
- **Evidence:** section 6 (identical results) and section 7 (timing).
- **dbt:** No dbt was used. The ELT engine writes its five tables with plain SQL in DuckDB. The brief lists dbt as a topic to revisit, but it does not require it.

### D7. The result table and the output files

- **Choice:** one row per day with three columns: `service_date`, `trip_count`, `daily_revenue`. Three files are written: a CSV (easy to open anywhere), a parquet file (typed and compact) and a JSON metadata file with the counts. Line endings are always LF, so the files are the same on Windows and Linux.
- **Reason:** the three columns answer the task and show how many trips stand behind each day. The metadata file explains what happened to every row: read, dropped, kept.
- **Evidence:** the CSV of all three engines has the same fingerprint (section 6).

### D8. Comparison without tolerance

- **Choice:** the comparison checks the tables **exactly**, with no rounding tolerance.
- **Reason:** with a tolerance, a small difference of one cent would pass unnoticed.
- **Evidence:** this decision came from a mistake. My first check allowed a tiny rounding tolerance by default. A planted error of 0.01 was not noticed. I fixed it and the planted error was found. Section 6 tells the story.

### D9. Project layout and command line

- **Choice:** the code lives in `src/taxi_revenue/` and is installed in editable mode. The command `taxi-revenue` has four commands: `download`, `run`, `compare` and `flow`. Settings sit in one file (`config.py`).
- **Reason:** with an installed package, the commands, the tests and the Prefect flow find the code without path tricks. Settings in one place mean that no other file repeats them.
- **Limit:** `config.py` finds the data folders from its own location. That works for the editable install, and not for a normal install into another folder.

### D10. What Git must not publish

- **Problem:** the school `.gitignore` only hid `solution/data/raw` and `solution/data/processed`. My data folders are `data/raw` and `data/processed`, so the three parquet files would have gone into the repository.
- **Choice:** six lines (a blank line, a comment and four rules) were added to `.gitignore` for my two data folders, with an exception for the placeholder files.
- **Evidence:** the rule was tested in a sandbox test repository with dummy files: the data files were ignored, and the placeholder file was not.

### D11. Prefect runs in its own temporary home

- **Problem:** Prefect keeps settings and a database on the computer, and a saved server address from an earlier project can break a new flow.
- **Choice:** run the flow with a temporary Prefect folder and without a saved server address, for this one command only.
- **Reason:** my own Prefect settings and database stay untouched.
- **Evidence:** the flow ran with the same result as the normal run (same CSV fingerprint) and the tests use Prefect's own test server. Section 9 shows the exact command.

## 5. How the three engines work

All three engines follow the same agreement. They take the list of staged files, and they return two things: a **table** with one row per day, and a dictionary of **counts** (the metadata). They apply the same three rules, and they add up the money in whole cents. That is why they can be compared fairly.

| | pandas | polars | DuckDB |
|---|---|---|---|
| Style | ETL | ETL | ELT |
| Where the work happens | in Python, in memory | in Python, with a lazy plan | inside a database, with SQL |
| What it reads | each file completely (21 columns), then keeps 2 | only the 2 columns it needs | the raw files completely (21 columns) into a table |
| File | `engine_pandas.py` | `engine_polars.py` | `engine_duckdb.py` |

### 5.1 pandas

pandas reads each file into a table in memory, applies the rules with true/false columns, and then groups by day. The core of the code:

~~~
has_values = pickup.notna() & amount.notna()
in_window = (pickup >= config.WINDOW_START) & (pickup < config.WINDOW_END)
used = has_values & in_window
...
cents = (amount * 100).round().astype("int64")
table = (
    pd.DataFrame({"service_date": pickup.dt.strftime("%Y-%m-%d"), "cents": cents})
    .groupby("service_date", as_index=False)
    .agg(trip_count=("cents", "size"), total_cents=("cents", "sum"))
    .sort_values("service_date", ignore_index=True)
)
~~~

Every line runs at once, on the full table. I read all 21 columns on purpose, so that the code can check that the two needed columns exist and give a clear error message if they do not.

### 5.2 polars

polars works **lazily**. `scan_parquet` does not read anything. It builds a plan, and the plan only runs when `collect()` is called. That lets polars read only the two columns it needs. The rules look like this:

~~~
.with_columns(
    has_values=(
        pl.col("pickup").is_not_null()
        & pl.col("amount").is_not_null()
        & pl.col("amount").is_not_nan()
    ),
    in_window=(
        (pl.col("pickup") >= window_start) & (pl.col("pickup") < window_end)
    ).fill_null(False),
)
~~~

One difference in practice: in polars, an empty value (null) and a real "not a number" (NaN) are two different things, so the rule needs both checks. The tests contain a file with a real NaN, and all three engines drop that trip. The finished table is handed back as a pandas table, so that the three results can be compared directly.

### 5.3 DuckDB

DuckDB is the ELT engine. **Extract and load come first:** the raw files are copied, unchanged, into a table. **Then the transformation runs inside the database**, as five tables, each built from the one before:

| Layer | What it holds |
|---|---|
| `raw_trips` | the files exactly as they are, all 21 columns |
| `trips` | the two needed columns with clean types |
| `flagged` | every trip marked: does it have values? is it inside the date window? |
| `used_trips` | only the trips that count, with the amount in whole cents |
| `daily` | one row per day |

The SQL of two of the layers:

~~~
CREATE OR REPLACE TABLE flagged AS
SELECT pickup, amount,
       COALESCE(pickup IS NOT NULL AND amount IS NOT NULL
                AND NOT isnan(amount), FALSE) AS has_values,
       COALESCE(pickup >= {start} AND pickup < {end}, FALSE) AS in_window
FROM trips

CREATE OR REPLACE TABLE daily AS
SELECT service_date,
       CAST(count(*) AS BIGINT) AS trip_count,
       CAST(sum(cents) AS BIGINT) AS total_cents,
       round(sum(cents) / 100.0, 2) AS daily_revenue
FROM used_trips
GROUP BY service_date
~~~

The database lives in memory and disappears at the end of the run. The engine function can also be given a file name (`database`), so that the layers stay and can be looked at later with SQL. I tried this in a test environment, but there is **no automated test** for it, and the command line does not offer it.

## 6. Proof that the three results are identical

"The same result" is easy to say and hard to prove. I used four levels of proof.

| Proof | Result |
|---|---|
| 1. The result tables are compared **exactly**, with no rounding tolerance (`taxi-revenue compare`) | identical on the real data |
| 2. The CSV files are compared byte by byte, through a fingerprint (the first 12 characters of the SHA-256 hash) | pandas, polars and DuckDB all give `573c923d786f` |
| 3. The metadata is compared, apart from the engine name | identical |
| 4. A test with 150,000 random trips (decimals, empty values, trips outside the window) compares the three engines exactly | passes |

### 6.1 A mistake in my first check

My first comparison used the default setting of the pandas function `assert_frame_equal`. By default it allows a tiny relative difference. I found out by accident: while testing the comparison code, I planted an error of 0.01 in one engine's result, and the check said nothing. A difference of 0.01 on an amount of about 10,000 is a relative difference of about one in a million, which the default setting allows.

I fixed it with `check_exact=True`. With the exact check, a planted error is found, even one as small as a billionth. Two tests check this, one for `compare.py` and one for the experiment script. When I removed the exact setting again on purpose, both tests failed.

The lesson is to **test the test**. Before the fix, I had described the results as "identical" while building, which was too strong. The byte-by-byte proof (level 2) is the one that makes the claim solid, and it was already in place for the real data.

### 6.2 Why whole cents matter

Adding decimals can give different last digits, depending on the order of the additions. For instance, 0.1 + 0.2 gives 0.30000000000000004 in most programming languages. The three engines add in different orders (pandas, polars and DuckDB group and sum in their own ways). Adding whole cents (integers) removes the problem, because integer sums do not depend on the order. I did **not** run the decimal version to see whether the engines would really have disagreed on this data. The decision is a protection, not a result I measured.

## 7. Timing

### 7.1 How steady are the numbers?

`taxi-revenue compare` times the three engines on the whole calculation. I ran it twice, and I got these medians in seconds:

| Run | pandas | polars | DuckDB |
|---|---|---|---|
| Run 1 (5 timed runs) | 0.094 | 0.023 | 0.157 |
| Run 2 (2 timed runs) | 0.127 | 0.034 | 0.154 |
| Experiment, part 2 (7 timed runs) | 0.090 | 0.022 | 0.131 |

The code did not change, but pandas moved from 0.094 to 0.127 seconds, which is 35 percent. The order of the engines stayed the same. As a rule of thumb, I treat differences **below about 20 percent as noise**. This rule is my own choice, based on these runs, and not a statistical test.

### 7.2 The experiment

In the first run, DuckDB was the slowest engine. My first explanation was that DuckDB loads all 21 columns into a table and builds five layers. That was a guess. `experiments/engine_timing_experiment.py` tests it, in three parts. Before it times anything, it checks that all variants give exactly the same table.

Every line below is the median of 7 timed runs after 1 warm-up run. The numbers are in seconds, from one run on one Windows computer with 146,486 trips. The library versions are saved in `results/engine_timing_experiment.json`.

**Part 1: only reading the files, with no calculation**

| | median | fastest | slowest |
|---|---|---|---|
| pandas, all columns | 0.023 | 0.020 | 0.026 |
| pandas, 2 columns | 0.010 | 0.009 | 0.011 |
| polars, all columns | 0.020 | 0.017 | 0.021 |
| polars, 2 columns | 0.007 | 0.007 | 0.008 |
| DuckDB, all columns (into a table) | 0.085 | 0.081 | 0.102 |
| DuckDB, 2 columns (into a table) | 0.038 | 0.033 | 0.043 |

**Part 2: the whole calculation**

| | median | fastest | slowest |
|---|---|---|---|
| pandas as built (reads all columns) | 0.090 | 0.085 | 0.097 |
| pandas, reads only the 2 columns | 0.079 | 0.067 | 0.085 |
| polars as built (lazy, 2 columns) | 0.022 | 0.022 | 0.024 |
| DuckDB as built (5 table layers) | 0.131 | 0.120 | 0.150 |
| DuckDB, one query on the files | 0.045 | 0.039 | 0.055 |

**Part 3: the DuckDB layers, one by one**

| Step | median | fastest | slowest |
|---|---|---|---|
| 0 start the database | 0.023 | 0.021 | 0.026 |
| 1 `raw_trips`: load the files, all columns | 0.045 | 0.040 | 0.055 |
| 2 `trips`: 2 columns, clean types | 0.003 | 0.003 | 0.003 |
| 3 `flagged`: mark every trip | 0.005 | 0.004 | 0.006 |
| 4 `used_trips`: keep the trips that count | 0.018 | 0.017 | 0.022 |
| 5 `daily`: one row per day | 0.008 | 0.007 | 0.009 |
| 6 read the table and the counts out | 0.004 | 0.003 | 0.005 |
| **Sum of the medians** | **0.106** | | |

### 7.3 What I measured

1. **Reading only the two needed columns is 2.2 to 2.9 times faster** in all three tools (pandas 0.023 to 0.010, polars 0.020 to 0.007, DuckDB 0.085 to 0.038).
2. **That does not rescue pandas.** The whole calculation is only 12 percent faster (0.090 to 0.079), which is close to the noise level. Most of the pandas time is in the calculation, not in reading.
3. **DuckDB spends most of its time before the SQL starts.** Starting the database and loading all columns take 0.068 of the 0.106 seconds (64 percent). The four SQL steps in between take 0.034 seconds together.
4. **One single query straight on the files takes 0.045 seconds.** That is 2.9 times faster than the five-layer version, and still 2.0 times slower than polars.
5. **polars is the fastest in every comparison**: 4.1 times faster than pandas as built, and 6.0 times faster than DuckDB as built.

### 7.4 What I guessed, and how it turned out

| My guess | What the measurement says |
|---|---|
| DuckDB is slow because it loads all 21 columns into a table | **Partly right.** Loading is the biggest single step (0.045 s). |
| DuckDB is slow because it builds five layers | **Not right.** The SQL layers cost only 0.034 s. |
| (I had not thought of it) | Starting a new database for every run costs 0.023 s. |

### 7.5 What is still not explained

- The five-layer DuckDB engine takes 0.131 seconds, but the layers in part 3 add up to 0.106. The missing 0.025 seconds are probably work that the layer experiment leaves out, such as checking the columns of each file first and counting the rows. This is a guess, and I did **not** measure it.
- I did not look into why polars is faster than pandas in both reading and calculation.

### 7.6 Limits

- One Windows computer and 146,486 trips. For millions of rows, the order of the engines could change. I did not test this.
- Memory use was not measured.
- "As built" is not a like-for-like comparison: pandas reads 21 columns, polars reads 2, and DuckDB loads 21 into a table. The variants in parts 1 and 2 make the comparison fairer.
- The DuckDB variant with one query is only a table, without the metadata counts, so it does a little less work.
- ELT with five tables is slower here, but speed is not its purpose. Every layer can be looked at on its own. That value did not show up in this timing.

## 8. Tests

The project has **89 automated tests**. They run with `uv run pytest` and take about 35 seconds on my computer. The Prefect test starts a temporary server, which takes part of that time. I did not time it separately. The very first run after a fresh install took about 3 minutes (188 seconds). I did not measure why. I think that new files being scanned by Windows and the first start of Prefect's temporary server are part of it.

| Test file | Tests | What it checks |
|---|---|---|
| `test_config.py` | 4 | the file names, the links, the date window and the folders |
| `test_engines.py` | 28 | the same 9 checks for each of the three engines, plus one test that compares them on 150,000 random trips |
| `test_download.py` | 8 | the download, against a small web server that runs on the same computer during the test |
| `test_pipeline.py` | 18 | the output files for each engine (the CSV text exactly, the parquet file, the metadata), the folders and the error messages |
| `test_cli.py` | 10 | the four commands and their error messages |
| `test_flow.py` | 5 | the three Prefect tasks and the whole flow |
| `test_compare.py` | 6 | the comparison: identical results, a difference of one billionth, different metadata |
| `test_experiment.py` | 4 | the timing experiment: its variants must give the same table |
| `test_data_profile.py` | 6 | the data profile script, on a small dataset with known answers |

The 9 checks that run for every engine: a known answer on a small dataset, the shape of the table, the window edges, negative and zero amounts, a real NaN, the same day in two files, exact money, "no files" and "missing column".

### 8.1 Do the tests really notice mistakes?

A test that never fails proves nothing. So I broke the code on purpose, in a test copy and not in the repository, and I checked that a test fails. I did this more than 20 times. For instance:

| What I broke | Result |
|---|---|
| The end of the date window made inclusive | tests fail |
| Decimals added instead of whole cents | tests fail |
| The missing-value rule removed | tests fail |
| The download no longer checks the file | tests fail |
| The temporary `.part` file no longer removed | tests fail |
| The CSV written with an extra index column | tests fail |
| The download step skipped | tests fail |
| A traceback shown instead of a short error message | tests fail |
| The exact comparison switched to the tolerant default | tests fail |

### 8.2 Three times my tests missed a mistake

This is the part I learned most from. In three places, my first tests did **not** notice the broken code:

1. **The experiment script.** I made the window end inclusive, and the tests still passed. My test data had no trip at exactly 1 April 00:00:00, so the mistake changed nothing. I added the edge trips and ran the same break again. It was caught.
2. **The data profile script.** Two of four breaks were not caught. One used the absolute value of negative parts, and one made the comparison tolerance too loose. My test data had no negative parts, and no total that differed from its parts by a small amount. I added both cases, and then all four breaks were caught.
3. **The exact comparison.** `compare.py` had no test of this kind at all, and the test of the experiment script planted an error of 0.01 on small amounts. That is so large that even the tolerant check would find it, so the test could not protect the exact setting. I added a test for `compare.py` and changed both planted errors to one billionth. Now only the exact check finds them, and removing the exact setting makes both tests fail.

The lesson is the same each time: a test only protects against mistakes that its data can show. Good test data contains the edges.

## 9. The Prefect flow

The school brief has a bonus task: use Prefect for orchestration. `flow.py` is the same pipeline as a Prefect flow named `daily-revenue`. It has three tasks: `download` (with 2 retries, 5 seconds apart, for network problems), `calculate` and `write`. The tasks only call the functions that the normal run already uses, so no code is repeated. An unknown engine name is refused before any task starts.

Start it with `uv run taxi-revenue flow` (add `--engine duckdb` or `--engine polars` to change the engine).

**On my computer:** the flow ran with the same result as the normal run. The CSV fingerprint was `573c923d786f` before and after. The three tasks together took about a third of a second (from the time stamps in the log). Starting Prefect's temporary server before them took about 17 seconds.

**What Prefect gives here, and what it does not:** for three tasks that run in a third of a second, Prefect is more machinery than the job needs. Its value is visible state, logs and retries for each task. That would matter more for a pipeline that runs every day. I did not test a scheduled run.

### Note: if you already use Prefect

Prefect keeps a global settings file and a database on the computer, and it may hold a saved server address from an earlier project. A saved address can make a new flow fail. To protect your own setup, I run the flow with a temporary Prefect folder and without a saved server address, **for this one command only**. On Windows with Git Bash, that is:

~~~
PH=$(cygpath -m "$(mktemp -d)")
env -u PREFECT_API_URL PREFECT_HOME="$PH" \
    PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true \
    PREFECT_SERVER_ANALYTICS_ENABLED=false \
    uv run taxi-revenue flow
~~~

What the settings do: `PREFECT_HOME` points to a throwaway folder, so your own settings and database are not read or changed. `env -u PREFECT_API_URL` removes a saved server address for this command. `PREFECT_SERVER_ALLOW_EPHEMERAL_MODE=true` lets Prefect start a temporary local server. `PREFECT_SERVER_ANALYTICS_ENABLED=false` switches off Prefect's usage statistics for this run.

On Linux, the same command works with `PH=$(mktemp -d)` instead of the first line. I tried this in a Linux test environment with generated data. I did not test macOS. The tests of the flow use Prefect's own test server, which is also temporary, so running `uv run pytest` does not touch your Prefect setup either.

## 10. Limits, what I did not verify, and ideas

### 10.1 Limits

- One Windows computer and 146,486 trips. The timings say nothing about very large data.
- "Revenue" here is `total_amount`, which does not include cash tips (see section 3.7).
- The date window drops 11 trips (worth 304.73). Someone who wants every trip under its own date would need a different rule.
- `config.py` finds the data folders from its own location. That works for the editable install and not for a normal install into another folder.
- The calculation does not use the payment type. The empty payment types (7,902 trips) are therefore not handled in any way.

### 10.2 What I did not verify

- **The reason for the vendor 6 zero totals.** The data cannot tell it. It needs the data provider.
- **Why the totals of vendors 1 and 6 do not equal the sum of their parts** (1.65 percent and 0 percent match, against 98.55 percent for vendor 2).
- **Why 20 March has 28 zero totals.**
- **Why the share of empty payment types grows** (3.8, 5.4 and 6.9 percent).
- **The terms of use of the data.** I did not read them. The TLC trip record user guide (2019 version) says that the data came from technology providers and that the TLC cannot guarantee its accuracy.
- **The missing 0.025 seconds** in the DuckDB timing (section 7.5).
- **Other systems.** Developed on Windows with Git Bash. The code was also run in a Linux test environment with generated data. It was not tested on macOS.
- **Keeping the DuckDB layers in a file.** It works through the engine function. There is no command line option and no automated test.

### 10.3 Ideas for more time

1. Ask the data provider why vendor 6 trips have a total of 0, and why the totals of vendors 1 and 6 differ from the sum of their parts.
2. Test with a full year of data, and measure memory as well as time.
3. Add automatic checks on GitHub for every change (the tests, and a style check).
4. Offer the DuckDB layers in a file from the command line, with a test, and offer the "one query" variant as a fourth engine.
5. Add the data quality counts (empty payment types, vendor 6 zero totals) to the metadata file.
6. Run the flow on a schedule, which is where Prefect would pay off.

## 11. Glossary

| Word | Meaning in this project |
|---|---|
| **ETL** | Extract, transform, load. The data is read, changed in the program, and only the result is saved. Used by pandas and polars here. |
| **ELT** | Extract, load, transform. The raw data is loaded first, unchanged, and the change happens inside the database. Used by DuckDB here. |
| **Staging folder** | The place (`data/raw`) where the downloaded files are kept exactly as they arrived. |
| **Parquet** | A file format for tables. It stores each column separately, so a program can read only the columns it needs. |
| **Whole cents** | Money written as an integer number of cents (12.34 becomes 1234). Integers add up exactly. |
| **Net revenue** | The sum of all amounts, including negative ones. |
| **Metadata** | The small file with counts that explain what happened to every row. |
| **Lazy** | Work that is planned first and run later. polars' `scan_parquet` is lazy. |
| **Null and NaN** | Null means "no value". NaN means "not a number". They are different things, and polars treats them differently. |
| **Median** | The middle value of the timed runs. It is less affected by one slow run than the average. |
| **Warm-up run** | A run before the timed runs that is not counted, so that the first read from disk does not hurt one engine. |
| **Exact comparison** | Two tables must be equal to the last digit. A tolerance would allow small differences. |
| **Fingerprint (hash)** | A short code calculated from a file. Two files with the same fingerprint are the same, byte for byte. |
| **Edge case** | A value right at the border of a rule, for instance a trip at exactly midnight on 1 April. |
| **Breaking the code on purpose** | Changing a copy of the code to make it wrong, to check that a test fails. |
| **Editable install** | The project is installed so that changes in the code count at once, without installing again. |
| **Flow and task (Prefect)** | A flow is the whole workflow. A task is one step in it. |
| **VendorID** | The company that sent the trip records: 1, 2 or 6. |
| **Payment type** | A code for how the passenger paid: for instance 1 = credit card, 3 = no charge, 4 = dispute. |

## 12. Sources and versions

- **NYC Taxi and Limousine Commission trip record data:** https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
- **Data dictionary for the green taxi records** (version of 18 March 2025): https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_green.pdf. I used it for the payment types, the vendor names and the meaning of `total_amount`.
- **TLC trip records user guide** (version of 23 September 2019): https://www.nyc.gov/assets/tlc/downloads/pdf/trip_record_user_guide.pdf. I used it for the sentence about the accuracy of the data.
- **The school template:** the neuefische data pipeline project (MIT licence). The school's reference solution is not part of this repository.
- **Versions on my computer:** Python 3.13.17, pandas 3.1.0, polars 2.1.0, DuckDB 2.0.0, PyArrow 26.0.0, Prefect 3.9.0, NumPy 2.5.4, Click 8.5.0, Requests 2.34.2.

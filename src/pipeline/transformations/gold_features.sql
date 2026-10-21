-- features use only data available before each transaction
CREATE MATERIALIZED VIEW gold.fraud_features
COMMENT 'Model features per transaction: amount vs history, velocity, distance, time of day, category risk.'
AS WITH base AS (
  SELECT f.*, unix_timestamp(f.transaction_ts) AS ts_sec, c.risk_group
  FROM gold.fact_transactions f
  JOIN gold.dim_category c ON f.category = c.category
)
SELECT
  transaction_id,
  customer_id,
  date_key,
  transaction_ts,
  amount,
  COALESCE(distance_from_home_km, 0)                       AS distance_from_home_km,
  hour(transaction_ts)                                     AS hour_of_day,
  CAST(hour(transaction_ts) < 6 AS INT)                    AS is_night,
  CAST(channel = 'online' AS INT)                          AS is_online,
  CAST(risk_group = 'high' AS INT)                         AS is_high_risk_category,
  COUNT(*)    OVER w_1h                                    AS txn_count_1h,
  SUM(amount) OVER w_1h                                    AS amount_sum_1h,
  COALESCE(amount / NULLIF(AVG(amount) OVER w_30d, 0), 1.0) AS amount_vs_30d_avg,
  CAST(is_fraud AS INT)                                    AS is_fraud
FROM base
WINDOW
  w_1h  AS (PARTITION BY customer_id ORDER BY ts_sec RANGE BETWEEN 3600 PRECEDING AND CURRENT ROW),
  w_30d AS (PARTITION BY customer_id ORDER BY ts_sec RANGE BETWEEN 2592000 PRECEDING AND 1 PRECEDING);
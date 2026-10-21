CREATE MATERIALIZED VIEW gold.dim_date
COMMENT 'Calendar dimension.'
AS SELECT
  CAST(date_format(d, 'yyyyMMdd') AS INT) AS date_key,
  d                                       AS date,
  year(d)                                 AS year,
  quarter(d)                              AS quarter,
  month(d)                                AS month,
  date_format(d, 'MMMM')                  AS month_name,
  date_format(d, 'EEEE')                  AS day_name,
  dayofweek(d) IN (1, 7)                  AS is_weekend
FROM (SELECT explode(sequence(DATE'2026-01-01', DATE'2027-12-31', INTERVAL 1 DAY)) AS d);


CREATE MATERIALIZED VIEW gold.dim_category
COMMENT 'Merchant categories grouped by fraud risk.'
AS SELECT
  category,
  CASE WHEN category IN ('online_retail', 'electronics', 'gas', 'travel') THEN 'high' ELSE 'standard' END AS risk_group
FROM (SELECT DISTINCT category FROM silver.merchants);


CREATE MATERIALIZED VIEW gold.dim_merchant
COMMENT 'Merchant dimension (SCD Type 1).'
AS SELECT merchant_id, merchant_name, category, city, state, lat, lon, is_online
FROM silver.merchants;


CREATE MATERIALIZED VIEW gold.dim_customer
COMMENT 'Customer dimension (SCD Type 2). No names and no card number.'
AS SELECT
  xxhash64(customer_id, __START_AT) AS customer_sk,
  customer_id,
  gender,
  CASE
    WHEN floor(months_between(current_date(), birth_date) / 12) < 30 THEN '18-29'
    WHEN floor(months_between(current_date(), birth_date) / 12) < 45 THEN '30-44'
    WHEN floor(months_between(current_date(), birth_date) / 12) < 60 THEN '45-59'
    ELSE '60+'
  END AS age_band,
  segment,
  credit_limit,
  city,
  state,
  lat        AS home_lat,
  lon        AS home_lon,
  card_last4,
  __START_AT AS valid_from,
  __END_AT   AS valid_to,
  __END_AT IS NULL AS is_current
FROM silver.customers;


-- each transaction joins the customer version valid at transaction time
CREATE MATERIALIZED VIEW gold.fact_transactions
COMMENT 'One row per valid transaction.'
CLUSTER BY (date_key)
AS SELECT
  t.transaction_id,
  CAST(date_format(t.transaction_ts, 'yyyyMMdd') AS INT) AS date_key,
  c.customer_sk,
  t.customer_id,
  t.merchant_id,
  m.category,
  t.channel,
  t.device_type,
  t.transaction_ts,
  t.amount,
  ROUND(2 * 6371 * asin(sqrt(
      pow(sin(radians(m.lat - c.home_lat) / 2), 2)
    + cos(radians(c.home_lat)) * cos(radians(m.lat)) * pow(sin(radians(m.lon - c.home_lon) / 2), 2)
  )), 1) AS distance_from_home_km,
  t.is_fraud
FROM silver.transactions t
LEFT JOIN gold.dim_customer c
  ON  t.customer_id = c.customer_id
  AND t.transaction_ts >= c.valid_from
  AND (c.valid_to IS NULL OR t.transaction_ts < c.valid_to)
LEFT JOIN gold.dim_merchant m
  ON t.merchant_id = m.merchant_id;
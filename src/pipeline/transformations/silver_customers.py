from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window


@dp.temporary_view(name="customers_changes")
def customers_changes():
    return (
        spark.readStream.table("bronze.customers")
        .withColumn("updated_at", F.to_timestamp("updated_at"))
        .withColumn("birth_date", F.to_date("birth_date"))
        .withColumn("card_hash", F.sha2("card_number", 256))
        .withColumn("card_last4", F.substring("card_number", -4, 4))
        .drop("card_number", "_rescued_data")
    )


dp.create_streaming_table(
    name="silver.customers",
    comment="Customer history as SCD Type 2. One row per version, valid between __START_AT and __END_AT.",
    expect_all_or_drop={"valid_customer_id": "customer_id IS NOT NULL"},
)

dp.create_auto_cdc_flow(
    target="silver.customers",
    source="customers_changes",
    keys=["customer_id"],
    sequence_by="updated_at",
    except_column_list=["_source_file", "_ingested_at"],
    stored_as_scd_type=2,
)


@dp.materialized_view(name="silver.merchants", comment="Latest version of each merchant.")
@dp.expect_or_drop("valid_merchant_id", "merchant_id IS NOT NULL")
def silver_merchants():
    latest = Window.partitionBy("merchant_id").orderBy(F.col("_ingested_at").desc())
    return (
        spark.read.table("bronze.merchants")
        .withColumn("_rn", F.row_number().over(latest))
        .where("_rn = 1")
        .drop("_rn", "_rescued_data", "_source_file", "_ingested_at")
    )
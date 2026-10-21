
from pyspark import pipelines as dp
from pyspark.sql import functions as F

LANDING = "/Volumes/fraud_lakehouse/raw/landing"


def auto_load(folder, schema_hints):
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaHints", schema_hints)
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .load(f"{LANDING}/{folder}")
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dp.table(name="bronze.transactions", comment="Raw card transactions from the landing Volume.")
def bronze_transactions():
    return auto_load("transactions", "card_number STRING, amount DOUBLE, transaction_ts STRING")


@dp.table(name="bronze.customers", comment="Raw customer records: initial load plus daily changes.")
def bronze_customers():
    return auto_load("customers", "card_number STRING, updated_at STRING, birth_date STRING")


@dp.table(name="bronze.merchants", comment="Raw merchant reference data.")
def bronze_merchants():
    return auto_load("merchants", "merchant_id STRING")
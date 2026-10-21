from pyspark import pipelines as dp
from pyspark.sql import functions as F

TXN_RULES = {
    "valid_amount": "amount IS NOT NULL AND amount > 0",
    "valid_card": "card_hash IS NOT NULL",
    "valid_timestamp": "transaction_ts IS NOT NULL AND transaction_ts <= current_timestamp()",
    "valid_currency": "currency = 'MXN'",
}


def mask_card(df):
    valid = F.col("card_number").rlike("^[0-9]{16}$")
    return (
        df.withColumn("card_hash", F.when(valid, F.sha2("card_number", 256)))
        .withColumn("card_last4", F.when(valid, F.substring("card_number", -4, 4)))
        .drop("card_number")
    )


@dp.temporary_view(name="transactions_typed")
def transactions_typed():
    return mask_card(
        spark.readStream.table("bronze.transactions")
        .withColumn("transaction_ts", F.to_timestamp("transaction_ts"))
        .drop("_rescued_data")
    )


@dp.table(
    name="silver.transactions",
    comment="Valid, deduplicated transactions. Card number replaced by hash and last 4 digits.",
    cluster_by=["transaction_ts"],
)
@dp.expect_all_or_drop(TXN_RULES)
def silver_transactions():
    return (
        spark.readStream.table("transactions_typed")
        .withWatermark("_ingested_at", "1 day")
        .dropDuplicatesWithinWatermark(["transaction_id"])
    )


@dp.table(
    name="silver.transactions_quarantine",
    comment="Transactions that failed at least one data quality rule.",
)
def silver_transactions_quarantine():
    failed = F.filter(
        F.array(*[
            F.when(~F.coalesce(F.expr(rule), F.lit(False)), F.lit(name))
            for name, rule in TXN_RULES.items()
        ]),
        lambda x: x.isNotNull(),
    )
    return (
        spark.readStream.table("transactions_typed")
        .withColumn("failed_rules", failed)
        .where(F.size("failed_rules") > 0)
    )
import json
import math
import os
import random
from datetime import datetime, timedelta

START_DATE = datetime(2026, 1, 1)
N_CUSTOMERS = 1_000
N_MERCHANTS = 800
SCHEMA_DRIFT_DAY = 120  # from this day on, transactions carry a new `device_type` field

CITIES = [  # name, state, lat, lon
    ("Ciudad de Mexico", "CDMX", 19.4326, -99.1332),
    ("Naucalpan", "Estado de Mexico", 19.4785, -99.2396),
    ("Toluca", "Estado de Mexico", 19.2826, -99.6557),
    ("Guadalajara", "Jalisco", 20.6597, -103.3496),
    ("Monterrey", "Nuevo Leon", 25.6866, -100.3161),
    ("Puebla", "Puebla", 19.0414, -98.2063),
    ("Queretaro", "Queretaro", 20.5888, -100.3899),
    ("Merida", "Yucatan", 20.9674, -89.5926),
    ("Cancun", "Quintana Roo", 21.1619, -86.8515),
    ("Tijuana", "Baja California", 32.5149, -117.0382),
    ("Leon", "Guanajuato", 21.1250, -101.6860),
    ("Veracruz", "Veracruz", 19.1738, -96.1342),
    ("Oaxaca", "Oaxaca", 17.0732, -96.7266),
    ("Chihuahua", "Chihuahua", 28.6320, -106.0691),
    ("San Luis Potosi", "San Luis Potosi", 22.1565, -100.9855),
]
CITY_WEIGHTS = [30, 8, 5, 12, 12, 6, 5, 4, 3, 5, 4, 3, 2, 3, 2]

# category -> (relative frequency, ticket multiplier)
CATEGORIES = {
    "grocery": (30, 0.8), "restaurant": (20, 0.6), "gas": (12, 1.0),
    "clothing": (8, 1.5), "health": (6, 1.0), "entertainment": (6, 0.8),
    "online_retail": (10, 1.3), "electronics": (4, 4.0), "travel": (4, 5.0),
}
FRAUD_CATEGORIES = ["online_retail", "electronics", "gas", "travel"]

FIRST_NAMES = ["Ana", "Luis", "Maria", "Jose", "Sofia", "Carlos", "Fernanda", "Jorge",
               "Valeria", "Miguel", "Daniela", "Ricardo", "Paola", "Alejandro", "Lucia", "Diego"]
LAST_NAMES = ["Hernandez", "Garcia", "Martinez", "Lopez", "Gonzalez", "Perez", "Rodriguez",
              "Sanchez", "Ramirez", "Cruz", "Flores", "Gomez", "Morales", "Vazquez", "Reyes"]
MERCHANT_WORDS = ["Sol", "Norte", "Azteca", "Central", "Plaza", "Express", "Real", "Nova",
                  "Jardin", "Max", "Punto", "Mundo", "Prime", "Union", "Delta", "Luna"]

# Fraction of transactions that get each data-quality problem
DQ_RATES = {"null_amount": 0.003, "negative_amount": 0.002, "bad_card": 0.002,
            "future_ts": 0.001, "bad_currency": 0.001}
DUPLICATE_RATE = 0.005    # same transaction re-sent in the same file
LATE_RATE = 0.01          # transaction from 1-2 days earlier arriving today
FRAUD_EVENT_RATE = 0.004  # probability a customer's card is compromised on a given day


def _luhn_card(rng):
    digits = [4] + [rng.randint(0, 9) for _ in range(14)]
    total = 0
    for i, d in enumerate(reversed(digits)):  # check digit not yet appended
        if i % 2 == 0:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return "".join(map(str, digits)) + str((10 - total % 10) % 10)


def _jitter(rng, lat, lon, km=8):
    d = km / 111
    return round(lat + rng.uniform(-d, d), 5), round(lon + rng.uniform(-d, d), 5)


def build_merchants(seed):
    rng = random.Random(seed)
    cats, weights = list(CATEGORIES), [w for w, _ in CATEGORIES.values()]
    merchants = []
    for i in range(1, N_MERCHANTS + 1):
        city, state, lat, lon = rng.choices(CITIES, CITY_WEIGHTS)[0]
        category = rng.choices(cats, weights)[0]
        mlat, mlon = _jitter(rng, lat, lon)
        merchants.append({
            "merchant_id": f"M{i:04d}",
            "merchant_name": f"{rng.choice(MERCHANT_WORDS)} {rng.choice(MERCHANT_WORDS)} {category.replace('_', ' ').title()}",
            "category": category, "city": city, "state": state,
            "lat": mlat, "lon": mlon, "is_online": category == "online_retail",
        })
    return merchants


def build_customers(seed):
    rng = random.Random(seed + 1)
    customers = []
    for i in range(1, N_CUSTOMERS + 1):
        city, state, lat, lon = rng.choices(CITIES, CITY_WEIGHTS)[0]
        clat, clon = _jitter(rng, lat, lon)
        segment = rng.choices(["mass", "affluent", "premium"], [70, 22, 8])[0]
        customers.append({
            "customer_id": f"C{i:05d}",
            "first_name": rng.choice(FIRST_NAMES), "last_name": rng.choice(LAST_NAMES),
            "gender": rng.choice(["F", "M"]),
            "birth_date": (datetime(1960, 1, 1) + timedelta(days=rng.randint(0, 15000))).date().isoformat(),
            "city": city, "state": state, "lat": clat, "lon": clon,
            "card_number": _luhn_card(rng), "segment": segment,
            "credit_limit": {"mass": 20_000, "affluent": 60_000, "premium": 150_000}[segment],
            "updated_at": START_DATE.isoformat(),
            # spending profile; used by the generator only, never written to files
            "_avg_ticket": {"mass": 350, "affluent": 900, "premium": 2200}[segment] * rng.uniform(0.6, 1.4),
        })
    return customers


def _public(customer):
    return {k: v for k, v in customer.items() if not k.startswith("_")}


def customer_updates(day, customers, seed):
    """Mutate a few customers (move city / raise limit). Returns the changed records."""
    if day == 0:
        return []
    rng = random.Random(seed * 1_000 + day)
    ts = (START_DATE + timedelta(days=day, hours=1)).isoformat()
    changed = []
    for c in rng.sample(customers, k=3):
        if rng.random() < 0.5:
            city, state, lat, lon = rng.choices(CITIES, CITY_WEIGHTS)[0]
            c["lat"], c["lon"] = _jitter(rng, lat, lon)
            c["city"], c["state"] = city, state
        else:
            c["credit_limit"] = int(c["credit_limit"] * 1.25)
        c["updated_at"] = ts
        changed.append(_public(c))
    return changed


def _txn(tid, c, m, amount, ts, is_fraud, day, rng):
    t = {"transaction_id": tid, "card_number": c["card_number"], "customer_id": c["customer_id"],
         "merchant_id": m["merchant_id"], "amount": round(amount, 2), "currency": "MXN",
         "transaction_ts": ts.isoformat(), "channel": "online" if m["is_online"] else "pos",
         "is_fraud": is_fraud}
    if day >= SCHEMA_DRIFT_DAY:
        t["device_type"] = "web" if m["is_online"] else rng.choice(["chip", "contactless", "chip", "swipe"])
    return t


def transactions_for_day(day, customers, merchants, seed):
    rng = random.Random(seed * 7_919 + day)
    base = START_DATE + timedelta(days=day)
    by_city, by_cat = {}, {}
    for m in merchants:
        by_city.setdefault(m["city"], []).append(m)
        by_cat.setdefault(m["category"], []).append(m)
    cat_mult = {k: mult for k, (_, mult) in CATEGORIES.items()}
    hours = list(range(24))
    hour_w = [1, 1, 1, 1, 1, 2, 4, 6, 8, 9, 10, 10, 11, 11, 10, 9, 9, 10, 11, 11, 9, 7, 4, 2]
    txns, seq = [], 0

    def next_id():
        nonlocal seq
        seq += 1
        return f"T{day:04d}{seq:06d}"

    for c in customers:
        # normal spending: mostly local merchants, daytime hours
        for _ in range(rng.choices(range(7), [8, 20, 25, 20, 13, 9, 5])[0]):
            pool = by_city.get(c["city"]) if rng.random() < 0.85 else None
            m = rng.choice(pool or merchants)
            amount = rng.lognormvariate(math.log(c["_avg_ticket"] * cat_mult[m["category"]]), 0.6)
            ts = base + timedelta(hours=rng.choices(hours, hour_w)[0], minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
            txns.append(_txn(next_id(), c, m, amount, ts, False, day, rng))

        # card compromised: a burst of large purchases, far from home, mostly at night
        if rng.random() < FRAUD_EVENT_RATE:
            hour = rng.randint(0, 5) if rng.random() < 0.7 else rng.randint(6, 23)
            ts = base + timedelta(hours=hour, minutes=rng.randint(0, 20))
            for _ in range(rng.randint(3, 6)):
                m = rng.choice([x for x in by_cat[rng.choice(FRAUD_CATEGORIES)] if x["city"] != c["city"]])
                amount = min(c["_avg_ticket"] * rng.uniform(3, 8), c["credit_limit"] * 0.4)
                txns.append(_txn(next_id(), c, m, amount, ts, True, day, rng))
                ts += timedelta(minutes=rng.randint(1, 8))

    # data-quality problems
    for t in txns:
        r = rng.random()
        cut = 0.0
        for issue, rate in DQ_RATES.items():
            cut += rate
            if r < cut:
                if issue == "null_amount":
                    t["amount"] = None
                elif issue == "negative_amount":
                    t["amount"] = -t["amount"]
                elif issue == "bad_card":
                    t["card_number"] = t["card_number"][:12]
                elif issue == "future_ts":
                    t["transaction_ts"] = (datetime.fromisoformat(t["transaction_ts"]) + timedelta(days=3650)).isoformat()
                elif issue == "bad_currency":
                    t["currency"] = "XXX"
                break
        if day >= 2 and rng.random() < LATE_RATE:
            t["transaction_ts"] = (datetime.fromisoformat(t["transaction_ts"]) - timedelta(days=rng.randint(1, 2))).isoformat()

    txns += [dict(t) for t in rng.sample(txns, k=int(len(txns) * DUPLICATE_RATE))]
    rng.shuffle(txns)
    return txns


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def next_day(root):
    """Index of the first day not yet written (0 if the landing folder is empty)."""
    folder = os.path.join(root, "transactions")
    return len(os.listdir(folder)) if os.path.isdir(folder) else 0


def write_days(root, n_days, seed=42):
    """Write the next `n_days` days of data after whatever is already in `root`."""
    first = next_day(root)
    merchants = build_merchants(seed)
    customers = build_customers(seed)
    if first == 0:
        _write_jsonl(f"{root}/merchants/merchants.json", merchants)
        _write_jsonl(f"{root}/customers/customers_{START_DATE.date()}.json", [_public(c) for c in customers])
    for day in range(first + n_days):
        updates = customer_updates(day, customers, seed)  # replayed so state is identical every run
        if day < first:
            continue
        date = (START_DATE + timedelta(days=day)).date()
        if updates:
            _write_jsonl(f"{root}/customers/customers_{date}.json", updates)
        _write_jsonl(f"{root}/transactions/transactions_{date}.json",
                     transactions_for_day(day, customers, merchants, seed))
    return first, first + n_days - 1
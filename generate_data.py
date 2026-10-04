"""
Synthetic transaction data generator for AML monitoring demo.
Creates realistic banking transaction data with embedded suspicious patterns.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

np.random.seed(42)
random.seed(42)

# FATF high-risk and monitored jurisdictions (as of 2024/2025 grey/black lists)
HIGH_RISK_JURISDICTIONS = [
    "IR", "KP", "MM",  # FATF blacklist: Iran, North Korea, Myanmar
    "SY", "YE", "AF",  # Conflict/sanctions exposure
]
MONITORED_JURISDICTIONS = [
    "PA", "AE", "TR", "VN", "PH", "NG", "KE", "ZA", "HR", "BG", "MC",
]
STANDARD_JURISDICTIONS = [
    "DE", "FR", "LU", "NL", "BE", "IT", "ES", "AT", "CH", "GB",
    "US", "CA", "JP", "SG", "AU", "SE", "DK", "FI", "IE", "PL",
]

BUSINESS_TYPES = [
    "Manufacturing", "Retail Trade", "Professional Services", "Construction",
    "Real Estate", "Import/Export", "Hospitality", "Logistics",
    "Financial Services", "Technology", "Precious Metals Trading",
    "Art & Antiquities", "Money Service Business", "Crypto Exchange",
]

TRANSACTION_TYPES = ["WIRE_IN", "WIRE_OUT", "SEPA_IN", "SEPA_OUT", "CASH_DEPOSIT", "CASH_WITHDRAWAL"]


def generate_customers(n=180):
    """Generate customer base with risk attributes."""
    customers = []
    for i in range(n):
        # ~8% in high-risk business types
        if random.random() < 0.08:
            biz = random.choice(["Precious Metals Trading", "Art & Antiquities",
                                 "Money Service Business", "Crypto Exchange"])
        else:
            biz = random.choice(BUSINESS_TYPES[:10])

        # Jurisdiction distribution
        r = random.random()
        if r < 0.04:
            jur = random.choice(HIGH_RISK_JURISDICTIONS)
        elif r < 0.18:
            jur = random.choice(MONITORED_JURISDICTIONS)
        else:
            jur = random.choice(STANDARD_JURISDICTIONS)

        customers.append({
            "customer_id": f"CUS{10000 + i}",
            "customer_name": f"Entity {i+1} {random.choice(['GmbH', 'S.A.', 'Ltd', 'B.V.', 'SARL', 'AG'])}",
            "jurisdiction": jur,
            "business_type": biz,
            "account_opened": (datetime(2020, 1, 1) + timedelta(days=random.randint(0, 2000))).date(),
            "pep_flag": random.random() < 0.05,
            "expected_monthly_volume": random.choice([25000, 50000, 100000, 250000, 500000, 1000000]),
        })
    return pd.DataFrame(customers)


def generate_transactions(customers_df, start_date="2026-07-01", end_date="2026-09-30"):
    """Generate transactions with embedded suspicious patterns."""
    transactions = []
    txn_id = 100000
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    days = (end - start).days

    for _, cust in customers_df.iterrows():
        cid = cust["customer_id"]
        expected = cust["expected_monthly_volume"]
        # Baseline: normal business activity
        n_txns = random.randint(15, 60)

        for _ in range(n_txns):
            txn_date = start + timedelta(days=random.randint(0, days),
                                         hours=random.randint(8, 18),
                                         minutes=random.randint(0, 59))
            amount = round(np.random.lognormal(mean=np.log(expected / 12), sigma=0.8), 2)
            amount = min(amount, expected * 0.8)

            # Counterparty jurisdiction: mostly matches customer's region
            if random.random() < 0.75:
                cp_jur = cust["jurisdiction"]
            else:
                cp_jur = random.choice(STANDARD_JURISDICTIONS + MONITORED_JURISDICTIONS)

            transactions.append({
                "transaction_id": f"TXN{txn_id}",
                "customer_id": cid,
                "timestamp": txn_date,
                "amount_eur": amount,
                "transaction_type": random.choice(TRANSACTION_TYPES),
                "counterparty_jurisdiction": cp_jur,
                "counterparty_name": f"CP-{random.randint(1000, 9999)}",
                "channel": random.choice(["ONLINE", "BRANCH", "API", "MOBILE"]),
            })
            txn_id += 1

    # ===== EMBED SUSPICIOUS PATTERNS =====
    suspects = customers_df.sample(14, random_state=7)["customer_id"].tolist()

    # PATTERN 1: Structuring (smurfing) - amounts just below 10k reporting threshold
    for cid in suspects[:4]:
        base = start + timedelta(days=random.randint(10, 60))
        for d in range(random.randint(6, 11)):
            transactions.append({
                "transaction_id": f"TXN{txn_id}",
                "customer_id": cid,
                "timestamp": base + timedelta(days=d, hours=random.randint(9, 17)),
                "amount_eur": round(random.uniform(8700, 9850), 2),
                "transaction_type": "CASH_DEPOSIT",
                "counterparty_jurisdiction": customers_df.loc[
                    customers_df.customer_id == cid, "jurisdiction"].iloc[0],
                "counterparty_name": f"CP-{random.randint(1000,9999)}",
                "channel": "BRANCH",
            })
            txn_id += 1

    # PATTERN 2: Rapid pass-through (funds in and out within 48h, similar amounts)
    for cid in suspects[4:8]:
        for _ in range(random.randint(4, 7)):
            t0 = start + timedelta(days=random.randint(5, 80), hours=random.randint(9, 16))
            amt = round(random.uniform(180000, 900000), 2)
            transactions.append({
                "transaction_id": f"TXN{txn_id}", "customer_id": cid, "timestamp": t0,
                "amount_eur": amt, "transaction_type": "WIRE_IN",
                "counterparty_jurisdiction": random.choice(MONITORED_JURISDICTIONS),
                "counterparty_name": f"CP-{random.randint(1000,9999)}", "channel": "API",
            })
            txn_id += 1
            transactions.append({
                "transaction_id": f"TXN{txn_id}", "customer_id": cid,
                "timestamp": t0 + timedelta(hours=random.randint(3, 40)),
                "amount_eur": round(amt * random.uniform(0.94, 0.99), 2),
                "transaction_type": "WIRE_OUT",
                "counterparty_jurisdiction": random.choice(HIGH_RISK_JURISDICTIONS + MONITORED_JURISDICTIONS),
                "counterparty_name": f"CP-{random.randint(1000,9999)}", "channel": "API",
            })
            txn_id += 1

    # PATTERN 3: Round-amount high-value wires to high-risk jurisdictions
    for cid in suspects[8:11]:
        for _ in range(random.randint(3, 6)):
            transactions.append({
                "transaction_id": f"TXN{txn_id}", "customer_id": cid,
                "timestamp": start + timedelta(days=random.randint(0, days), hours=random.randint(9, 18)),
                "amount_eur": float(random.choice([250000, 500000, 750000, 1000000, 1500000])),
                "transaction_type": "WIRE_OUT",
                "counterparty_jurisdiction": random.choice(HIGH_RISK_JURISDICTIONS),
                "counterparty_name": f"CP-{random.randint(1000,9999)}", "channel": "ONLINE",
            })
            txn_id += 1

    # PATTERN 4: Volume spike far beyond expected profile
    for cid in suspects[11:]:
        expected = customers_df.loc[customers_df.customer_id == cid, "expected_monthly_volume"].iloc[0]
        spike_month = start + timedelta(days=random.randint(30, 60))
        for _ in range(random.randint(12, 20)):
            transactions.append({
                "transaction_id": f"TXN{txn_id}", "customer_id": cid,
                "timestamp": spike_month + timedelta(days=random.randint(0, 25), hours=random.randint(0, 23)),
                "amount_eur": round(expected * random.uniform(0.6, 1.4), 2),
                "transaction_type": random.choice(["WIRE_IN", "WIRE_OUT"]),
                "counterparty_jurisdiction": random.choice(MONITORED_JURISDICTIONS + STANDARD_JURISDICTIONS),
                "counterparty_name": f"CP-{random.randint(1000,9999)}", "channel": "ONLINE",
            })
            txn_id += 1

    df = pd.DataFrame(transactions)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


if __name__ == "__main__":
    customers = generate_customers(180)
    transactions = generate_transactions(customers)
    customers.to_csv("data/customers.csv", index=False)
    transactions.to_csv("data/transactions.csv", index=False)
    print(f"Generated {len(customers)} customers and {len(transactions)} transactions")
    print(f"Date range: {transactions.timestamp.min()} to {transactions.timestamp.max()}")
    print(f"Total volume: EUR {transactions.amount_eur.sum():,.0f}")

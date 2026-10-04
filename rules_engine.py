"""
AML Rules Engine
Rule-based transaction monitoring aligned with FATF typologies and
EU AMLD requirements. Each rule produces alerts with a risk score,
typology classification, and supporting evidence.
"""
import pandas as pd
import numpy as np
from datetime import timedelta

# FATF-listed jurisdictions (high-risk / call for action)
HIGH_RISK_JURISDICTIONS = {"IR", "KP", "MM", "SY", "YE", "AF"}
# Increased monitoring ("grey list") and higher-risk corridors
MONITORED_JURISDICTIONS = {"PA", "AE", "TR", "VN", "PH", "NG", "KE", "ZA", "HR", "BG", "MC"}

HIGH_RISK_BUSINESS = {
    "Precious Metals Trading", "Art & Antiquities",
    "Money Service Business", "Crypto Exchange",
}

# Cash reporting threshold (EU AMLD / typical national threshold)
CASH_REPORTING_THRESHOLD = 10000


class Alert:
    """Represents a single AML alert."""
    def __init__(self, customer_id, rule_id, rule_name, typology,
                 risk_score, description, evidence, transaction_ids):
        self.customer_id = customer_id
        self.rule_id = rule_id
        self.rule_name = rule_name
        self.typology = typology
        self.risk_score = risk_score
        self.description = description
        self.evidence = evidence
        self.transaction_ids = transaction_ids

    def to_dict(self):
        return {
            "customer_id": self.customer_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "typology": self.typology,
            "risk_score": self.risk_score,
            "description": self.description,
            "evidence": self.evidence,
            "transaction_count": len(self.transaction_ids),
            "transaction_ids": ";".join(self.transaction_ids[:10]),
        }


# ============ RULE 1: STRUCTURING / SMURFING ============

def rule_structuring(txns, customers, threshold=CASH_REPORTING_THRESHOLD,
                     window_days=14, min_count=4, proximity=0.15):
    """
    FATF Typology: Structuring (smurfing)
    Detects multiple cash transactions deliberately kept below the
    reporting threshold within a short window.
    """
    alerts = []
    lower_bound = threshold * (1 - proximity)

    cash = txns[txns.transaction_type.isin(["CASH_DEPOSIT", "CASH_WITHDRAWAL"])].copy()
    near_threshold = cash[(cash.amount_eur >= lower_bound) & (cash.amount_eur < threshold)]

    for cid, grp in near_threshold.groupby("customer_id"):
        grp = grp.sort_values("timestamp")
        for i in range(len(grp)):
            window_start = grp.iloc[i].timestamp
            window_end = window_start + timedelta(days=window_days)
            window = grp[(grp.timestamp >= window_start) & (grp.timestamp <= window_end)]

            if len(window) >= min_count:
                total = window.amount_eur.sum()
                # Risk scales with count and aggregate value
                score = min(95, 55 + len(window) * 4 + min(15, total / 50000))
                alerts.append(Alert(
                    customer_id=cid,
                    rule_id="R001",
                    rule_name="Structuring Below Reporting Threshold",
                    typology="Structuring / Smurfing",
                    risk_score=round(score),
                    description=(
                        f"{len(window)} cash transactions between EUR {lower_bound:,.0f} and "
                        f"{threshold:,.0f} within {window_days} days, aggregating EUR {total:,.0f}. "
                        f"Pattern is consistent with deliberate avoidance of the cash reporting threshold."
                    ),
                    evidence=(
                        f"Count: {len(window)} | Aggregate: EUR {total:,.0f} | "
                        f"Mean: EUR {window.amount_eur.mean():,.0f} | "
                        f"Window: {window_start.date()} to {window.timestamp.max().date()}"
                    ),
                    transaction_ids=window.transaction_id.tolist(),
                ))
                break  # one alert per customer per rule
    return alerts


# ============ RULE 2: RAPID PASS-THROUGH ============

def rule_pass_through(txns, customers, window_hours=72, amount_tolerance=0.10,
                      min_amount=50000):
    """
    FATF Typology: Layering via pass-through accounts
    Detects funds received and transferred out shortly after in similar
    amounts, indicating the account is used as a conduit rather than for
    genuine business activity.
    """
    alerts = []
    inflows = txns[txns.transaction_type.isin(["WIRE_IN", "SEPA_IN"])]
    outflows = txns[txns.transaction_type.isin(["WIRE_OUT", "SEPA_OUT"])]

    for cid in txns.customer_id.unique():
        cust_in = inflows[inflows.customer_id == cid].sort_values("timestamp")
        cust_out = outflows[outflows.customer_id == cid].sort_values("timestamp")
        if cust_in.empty or cust_out.empty:
            continue

        matches = []
        for _, inf in cust_in.iterrows():
            if inf.amount_eur < min_amount:
                continue
            window_end = inf.timestamp + timedelta(hours=window_hours)
            candidates = cust_out[
                (cust_out.timestamp > inf.timestamp) &
                (cust_out.timestamp <= window_end) &
                (abs(cust_out.amount_eur - inf.amount_eur) / inf.amount_eur <= amount_tolerance)
            ]
            for _, out in candidates.iterrows():
                hours = (out.timestamp - inf.timestamp).total_seconds() / 3600
                matches.append({
                    "in_id": inf.transaction_id, "out_id": out.transaction_id,
                    "amount": inf.amount_eur, "hours": hours,
                    "out_jurisdiction": out.counterparty_jurisdiction,
                })
                break

        if len(matches) >= 2:
            total = sum(m["amount"] for m in matches)
            hr_destinations = [m for m in matches
                               if m["out_jurisdiction"] in HIGH_RISK_JURISDICTIONS]
            score = min(98, 60 + len(matches) * 6 + len(hr_destinations) * 10)
            txn_ids = [m["in_id"] for m in matches] + [m["out_id"] for m in matches]
            alerts.append(Alert(
                customer_id=cid,
                rule_id="R002",
                rule_name="Rapid Pass-Through Activity",
                typology="Layering / Conduit Account",
                risk_score=round(score),
                description=(
                    f"{len(matches)} matched in/out pairs where funds left the account within "
                    f"{window_hours}h of receipt at similar value. Aggregate EUR {total:,.0f}. "
                    f"{len(hr_destinations)} pair(s) routed to FATF high-risk jurisdictions. "
                    f"Account shows conduit characteristics inconsistent with operating business activity."
                ),
                evidence=(
                    f"Pairs: {len(matches)} | Aggregate: EUR {total:,.0f} | "
                    f"Mean turnaround: {np.mean([m['hours'] for m in matches]):.1f}h | "
                    f"High-risk destinations: {len(hr_destinations)}"
                ),
                transaction_ids=txn_ids,
            ))
    return alerts


# ============ RULE 3: HIGH-RISK JURISDICTION EXPOSURE ============

def rule_high_risk_jurisdiction(txns, customers, min_amount=100000):
    """
    EU AMLD Art. 18a: Enhanced due diligence for high-risk third countries
    Flags material value transferred to or received from FATF-listed
    jurisdictions.
    """
    alerts = []
    exposed = txns[
        (txns.counterparty_jurisdiction.isin(HIGH_RISK_JURISDICTIONS)) &
        (txns.amount_eur >= min_amount)
    ]

    for cid, grp in exposed.groupby("customer_id"):
        total = grp.amount_eur.sum()
        jurisdictions = sorted(grp.counterparty_jurisdiction.unique())
        round_amounts = grp[grp.amount_eur % 50000 == 0]
        score = min(96, 65 + len(grp) * 3 + len(round_amounts) * 4)

        desc = (
            f"{len(grp)} transaction(s) totalling EUR {total:,.0f} involving FATF high-risk "
            f"jurisdictions ({', '.join(jurisdictions)}). Enhanced due diligence required "
            f"under EU AMLD Article 18a."
        )
        if len(round_amounts) >= 2:
            desc += (f" {len(round_amounts)} transaction(s) are exact round amounts, "
                     f"which is atypical of commercial settlement.")

        alerts.append(Alert(
            customer_id=cid,
            rule_id="R003",
            rule_name="High-Risk Jurisdiction Exposure",
            typology="Sanctions / High-Risk Country Exposure",
            risk_score=round(score),
            description=desc,
            evidence=(
                f"Jurisdictions: {', '.join(jurisdictions)} | Count: {len(grp)} | "
                f"Aggregate: EUR {total:,.0f} | Round amounts: {len(round_amounts)}"
            ),
            transaction_ids=grp.transaction_id.tolist(),
        ))
    return alerts


# ============ RULE 4: VOLUME DEVIATION FROM PROFILE ============

def rule_volume_deviation(txns, customers, threshold_multiple=4.0):
    """
    Risk-based approach: activity inconsistent with the customer's
    declared business profile (KYC expected volume).
    """
    alerts = []
    t = txns.copy()
    t["month"] = t.timestamp.dt.to_period("M")
    monthly = t.groupby(["customer_id", "month"]).agg(
        volume=("amount_eur", "sum"), count=("transaction_id", "count")
    ).reset_index()

    cust_lookup = customers.set_index("customer_id")

    for cid, grp in monthly.groupby("customer_id"):
        if cid not in cust_lookup.index:
            continue
        expected = cust_lookup.loc[cid, "expected_monthly_volume"]
        # Absolute floor: avoid alerting on immaterial breaches from small accounts
        breaches = grp[(grp.volume > expected * threshold_multiple) &
                       (grp.volume >= 250000)]
        if breaches.empty:
            continue

        worst = breaches.loc[breaches.volume.idxmax()]
        multiple = worst.volume / expected
        score = min(92, 50 + multiple * 8)
        month_txns = t[(t.customer_id == cid) & (t.month == worst.month)]

        alerts.append(Alert(
            customer_id=cid,
            rule_id="R004",
            rule_name="Activity Inconsistent with Customer Profile",
            typology="Unusual Activity / Profile Deviation",
            risk_score=round(score),
            description=(
                f"Monthly turnover of EUR {worst.volume:,.0f} in {worst.month} is "
                f"{multiple:.1f}x the expected volume of EUR {expected:,.0f} declared at onboarding. "
                f"{int(worst['count'])} transactions in the period. KYC profile refresh and "
                f"source-of-funds enquiry recommended."
            ),
            evidence=(
                f"Period: {worst.month} | Actual: EUR {worst.volume:,.0f} | "
                f"Expected: EUR {expected:,.0f} | Multiple: {multiple:.1f}x | "
                f"Months breached: {len(breaches)}"
            ),
            transaction_ids=month_txns.transaction_id.tolist(),
        ))
    return alerts


# ============ RULE 5: ROUND-AMOUNT CONCENTRATION ============

def rule_round_amounts(txns, customers, min_amount=100000, min_count=3):
    """
    Typology indicator: genuine commercial payments rarely settle at exact
    round values. Concentration of round-value high-material transfers is
    an indicator of non-commercial fund movement.
    """
    alerts = []
    large = txns[txns.amount_eur >= min_amount].copy()
    large["is_round"] = (large.amount_eur % 50000 == 0)
    round_txns = large[large.is_round]

    for cid, grp in round_txns.groupby("customer_id"):
        if len(grp) < min_count:
            continue
        total = grp.amount_eur.sum()
        all_large = large[large.customer_id == cid]
        ratio = len(grp) / len(all_large)
        score = min(85, 45 + len(grp) * 5 + ratio * 20)

        alerts.append(Alert(
            customer_id=cid,
            rule_id="R005",
            rule_name="Round-Amount Transaction Concentration",
            typology="Unusual Transaction Characteristics",
            risk_score=round(score),
            description=(
                f"{len(grp)} of {len(all_large)} high-value transactions ({ratio:.0%}) settled at "
                f"exact round amounts, totalling EUR {total:,.0f}. Commercial invoicing rarely "
                f"produces exact round settlements at this frequency."
            ),
            evidence=(
                f"Round transactions: {len(grp)}/{len(all_large)} ({ratio:.0%}) | "
                f"Aggregate: EUR {total:,.0f} | Max: EUR {grp.amount_eur.max():,.0f}"
            ),
            transaction_ids=grp.transaction_id.tolist(),
        ))
    return alerts


# ============ CUSTOMER RISK SCORING ============

def score_customer_risk(customers, txns, alerts_df):
    """
    Composite customer risk rating combining static KYC risk factors with
    dynamic transaction-monitoring outcomes. Mirrors a risk-based approach
    under EU AMLD.
    """
    scores = []
    for _, cust in customers.iterrows():
        cid = cust.customer_id
        static_score = 0
        factors = []

        if cust.jurisdiction in HIGH_RISK_JURISDICTIONS:
            static_score += 35
            factors.append(f"FATF high-risk domicile ({cust.jurisdiction})")
        elif cust.jurisdiction in MONITORED_JURISDICTIONS:
            static_score += 15
            factors.append(f"Increased-monitoring domicile ({cust.jurisdiction})")

        if cust.business_type in HIGH_RISK_BUSINESS:
            static_score += 25
            factors.append(f"High-risk sector ({cust.business_type})")

        if cust.pep_flag:
            static_score += 20
            factors.append("PEP association")

        cust_alerts = alerts_df[alerts_df.customer_id == cid] if not alerts_df.empty else pd.DataFrame()
        if not cust_alerts.empty:
            dynamic_score = min(60, cust_alerts.risk_score.max() * 0.5 + len(cust_alerts) * 5)
            factors.append(f"{len(cust_alerts)} open alert(s)")
        else:
            dynamic_score = 0

        total = min(100, static_score + dynamic_score)
        if total >= 70:
            rating = "HIGH"
        elif total >= 40:
            rating = "MEDIUM"
        else:
            rating = "LOW"

        cust_txns = txns[txns.customer_id == cid]
        scores.append({
            "customer_id": cid,
            "customer_name": cust.customer_name,
            "jurisdiction": cust.jurisdiction,
            "business_type": cust.business_type,
            "pep_flag": cust.pep_flag,
            "static_risk": static_score,
            "dynamic_risk": round(dynamic_score),
            "total_risk_score": round(total),
            "risk_rating": rating,
            "alert_count": len(cust_alerts),
            "transaction_count": len(cust_txns),
            "total_volume": cust_txns.amount_eur.sum() if not cust_txns.empty else 0,
            "risk_factors": "; ".join(factors) if factors else "No elevated risk factors identified",
        })
    return pd.DataFrame(scores).sort_values("total_risk_score", ascending=False)


# ============ ORCHESTRATOR ============

def run_all_rules(txns, customers):
    """Execute the full rule set and return consolidated alerts."""
    all_alerts = []
    all_alerts += rule_structuring(txns, customers)
    all_alerts += rule_pass_through(txns, customers)
    all_alerts += rule_high_risk_jurisdiction(txns, customers)
    all_alerts += rule_volume_deviation(txns, customers)
    all_alerts += rule_round_amounts(txns, customers)

    if not all_alerts:
        return pd.DataFrame(columns=[
            "customer_id", "rule_id", "rule_name", "typology", "risk_score",
            "description", "evidence", "transaction_count", "transaction_ids"])

    df = pd.DataFrame([a.to_dict() for a in all_alerts])
    df = df.sort_values("risk_score", ascending=False).reset_index(drop=True)
    df.insert(0, "alert_id", [f"ALT{2000+i}" for i in range(len(df))])
    return df


RULE_CATALOGUE = [
    {"id": "R001", "name": "Structuring Below Reporting Threshold",
     "typology": "Structuring / Smurfing",
     "basis": "FATF Recommendation 20; EU AMLD cash reporting thresholds",
     "logic": "4+ cash transactions within 85-100% of the EUR 10,000 reporting threshold in a 14-day window."},
    {"id": "R002", "name": "Rapid Pass-Through Activity",
     "typology": "Layering / Conduit Account",
     "basis": "FATF layering typology; EBA ML/TF risk factor guidelines",
     "logic": "2+ matched inflow/outflow pairs within 72 hours at ≤10% value difference, minimum EUR 50,000."},
    {"id": "R003", "name": "High-Risk Jurisdiction Exposure",
     "typology": "Sanctions / High-Risk Country Exposure",
     "basis": "EU AMLD Article 18a; FATF high-risk jurisdiction list",
     "logic": "Any transaction ≥ EUR 100,000 to or from a FATF-listed high-risk jurisdiction."},
    {"id": "R004", "name": "Activity Inconsistent with Customer Profile",
     "typology": "Unusual Activity / Profile Deviation",
     "basis": "Risk-based approach; EU AMLD ongoing monitoring obligation",
     "logic": "Monthly turnover exceeding 4x the expected volume declared at onboarding, with a EUR 250,000 materiality floor."},
    {"id": "R005", "name": "Round-Amount Transaction Concentration",
     "typology": "Unusual Transaction Characteristics",
     "basis": "FATF trade-based money laundering indicators",
     "logic": "3+ high-value transactions (≥ EUR 100,000) settling at exact EUR 50,000 multiples."},
]

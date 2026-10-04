"""
SAR (Suspicious Activity Report) narrative generator.
Produces structured, regulator-ready case narratives from alert data,
following the standard FIU reporting structure used across EU jurisdictions.
"""
import pandas as pd
from datetime import datetime


def generate_sar_narrative(customer_id, customers, transactions, alerts, risk_scores):
    """
    Build a complete SAR narrative for a flagged customer.
    Structure follows typical FIU submission requirements: subject details,
    account activity summary, grounds for suspicion, and supporting evidence.
    """
    cust = customers[customers.customer_id == customer_id].iloc[0]
    cust_txns = transactions[transactions.customer_id == customer_id]
    cust_alerts = alerts[alerts.customer_id == customer_id].sort_values("risk_score", ascending=False)
    risk = risk_scores[risk_scores.customer_id == customer_id].iloc[0]

    lines = []
    lines.append("SUSPICIOUS ACTIVITY REPORT")
    lines.append("INTERNAL DRAFT - FOR COMPLIANCE REVIEW")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"Report reference:      SAR-{customer_id}-{datetime.now().strftime('%Y%m%d')}")
    lines.append(f"Date of preparation:   {datetime.now().strftime('%d %B %Y')}")
    lines.append(f"Prepared by:           Transaction Monitoring (automated detection)")
    lines.append(f"Status:                Pending compliance officer review")
    lines.append("")

    # --- 1. SUBJECT DETAILS ---
    lines.append("1. SUBJECT DETAILS")
    lines.append("-" * 78)
    lines.append(f"Customer ID:           {cust.customer_id}")
    lines.append(f"Legal name:            {cust.customer_name}")
    lines.append(f"Domicile:              {cust.jurisdiction}")
    lines.append(f"Business activity:     {cust.business_type}")
    lines.append(f"Relationship start:    {cust.account_opened}")
    lines.append(f"PEP status:            {'YES - enhanced due diligence applies' if cust.pep_flag else 'No'}")
    lines.append(f"Declared volume:       EUR {cust.expected_monthly_volume:,.0f} per month")
    lines.append(f"Composite risk rating: {risk.risk_rating} (score {risk.total_risk_score}/100)")
    lines.append("")

    # --- 2. ACCOUNT ACTIVITY ---
    lines.append("2. ACCOUNT ACTIVITY SUMMARY")
    lines.append("-" * 78)
    lines.append(f"Review period:         {cust_txns.timestamp.min().date()} to {cust_txns.timestamp.max().date()}")
    lines.append(f"Transaction count:     {len(cust_txns):,}")
    lines.append(f"Aggregate value:       EUR {cust_txns.amount_eur.sum():,.2f}")
    lines.append(f"Mean transaction:      EUR {cust_txns.amount_eur.mean():,.2f}")
    lines.append(f"Largest transaction:   EUR {cust_txns.amount_eur.max():,.2f}")

    months = (cust_txns.timestamp.max() - cust_txns.timestamp.min()).days / 30.44
    actual_monthly = cust_txns.amount_eur.sum() / max(months, 1)
    variance = actual_monthly / cust.expected_monthly_volume
    lines.append(f"Actual monthly avg:    EUR {actual_monthly:,.0f} ({variance:.1f}x declared volume)")
    lines.append("")

    lines.append("Transaction type breakdown:")
    for ttype, grp in cust_txns.groupby("transaction_type"):
        lines.append(f"  {ttype:<18} {len(grp):>4} transactions   EUR {grp.amount_eur.sum():>15,.2f}")
    lines.append("")

    lines.append("Counterparty jurisdiction exposure (top 6 by value):")
    jur = cust_txns.groupby("counterparty_jurisdiction").agg(
        count=("transaction_id", "count"), value=("amount_eur", "sum")
    ).sort_values("value", ascending=False).head(6)
    for j, row in jur.iterrows():
        flag = ""
        if j in {"IR", "KP", "MM", "SY", "YE", "AF"}:
            flag = "  [FATF HIGH-RISK]"
        elif j in {"PA", "AE", "TR", "VN", "PH", "NG", "KE", "ZA", "HR", "BG", "MC"}:
            flag = "  [INCREASED MONITORING]"
        lines.append(f"  {j:<4} {int(row['count']):>4} transactions   EUR {row['value']:>15,.2f}{flag}")
    lines.append("")

    # --- 3. GROUNDS FOR SUSPICION ---
    lines.append("3. GROUNDS FOR SUSPICION")
    lines.append("-" * 78)
    lines.append(f"{len(cust_alerts)} monitoring rule(s) triggered during the review period.")
    lines.append("")
    for i, (_, alert) in enumerate(cust_alerts.iterrows(), 1):
        lines.append(f"{i}. {alert.rule_name}  [{alert.rule_id}]")
        lines.append(f"   Typology:    {alert.typology}")
        lines.append(f"   Risk score:  {alert.risk_score}/100")
        lines.append(f"   Finding:     {alert.description}")
        lines.append(f"   Evidence:    {alert.evidence}")
        lines.append("")

    # --- 4. CUSTOMER RISK PROFILE ---
    lines.append("4. CUSTOMER RISK PROFILE")
    lines.append("-" * 78)
    lines.append(f"Static (KYC) risk component:       {risk.static_risk}/100")
    lines.append(f"Dynamic (monitoring) component:    {risk.dynamic_risk}/100")
    lines.append(f"Composite rating:                  {risk.risk_rating} ({risk.total_risk_score}/100)")
    lines.append("")
    lines.append("Contributing risk factors:")
    for factor in risk.risk_factors.split("; "):
        lines.append(f"  - {factor}")
    lines.append("")

    # --- 5. RECOMMENDED ACTIONS ---
    lines.append("5. RECOMMENDED ACTIONS")
    lines.append("-" * 78)
    actions = []
    typologies = set(cust_alerts.typology.tolist())

    if "Structuring / Smurfing" in typologies:
        actions.append("Obtain source-of-funds documentation for all cash deposits in the review period.")
        actions.append("Interview the relationship manager regarding the customer's stated cash-handling needs.")
    if "Layering / Conduit Account" in typologies:
        actions.append("Request commercial rationale and underlying contracts for matched inflow/outflow pairs.")
        actions.append("Identify and verify ultimate beneficial owners of the counterparty entities involved.")
    if "Sanctions / High-Risk Country Exposure" in typologies:
        actions.append("Escalate to Sanctions team for secondary screening against consolidated lists.")
        actions.append("Apply enhanced due diligence measures under EU AMLD Article 18a.")
    if "Unusual Activity / Profile Deviation" in typologies:
        actions.append("Initiate KYC profile refresh; update expected activity parameters.")
        actions.append("Request explanation for the volume increase and supporting commercial documentation.")
    if "Unusual Transaction Characteristics" in typologies:
        actions.append("Request invoices or settlement documentation for round-value transfers.")

    if risk.risk_rating == "HIGH":
        actions.append("Consider account restriction pending completion of the review.")
        actions.append("Prepare submission to the national Financial Intelligence Unit if suspicion is confirmed.")

    actions.append("Document the review outcome and rationale in the case management system.")

    for i, action in enumerate(actions, 1):
        lines.append(f"{i}. {action}")
    lines.append("")

    # --- 6. SUPPORTING TRANSACTIONS ---
    lines.append("6. SUPPORTING TRANSACTIONS (highest value, up to 15)")
    lines.append("-" * 78)
    lines.append(f"{'Transaction ID':<14}{'Date':<12}{'Type':<16}{'Amount (EUR)':>16}  {'CP Jur.':<8}")
    top = cust_txns.nlargest(15, "amount_eur")
    for _, t in top.iterrows():
        lines.append(
            f"{t.transaction_id:<14}{str(t.timestamp.date()):<12}{t.transaction_type:<16}"
            f"{t.amount_eur:>16,.2f}  {t.counterparty_jurisdiction:<8}"
        )
    lines.append("")
    lines.append("=" * 78)
    lines.append("END OF REPORT")
    lines.append("")
    lines.append("This report was generated by an automated transaction monitoring system and")
    lines.append("requires review and sign-off by a designated compliance officer before any")
    lines.append("regulatory submission. Alert outcomes must be documented whether the case is")
    lines.append("escalated or closed as a false positive.")

    return "\n".join(lines)

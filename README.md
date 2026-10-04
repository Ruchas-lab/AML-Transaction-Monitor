# AML Transaction Monitoring System

A rule-based transaction monitoring and alert triage system built to replicate how a
financial institution detects, scores, and documents suspicious activity under EU
anti-money-laundering requirements.

The system ingests customer and transaction data, applies five detection rules mapped to
recognised FATF typologies, produces risk-scored alerts with supporting evidence, maintains
a composite customer risk register, and generates draft Suspicious Activity Report narratives
for compliance officer review.

---

## Why this exists

Most AML tooling demos stop at flagging large transactions. The harder problems in real
transaction monitoring are different: writing detection logic that maps to an actual
regulatory basis, calibrating thresholds so the alert volume is reviewable by a human team,
and producing output a compliance officer can defend to a regulator.

This project addresses those three problems directly.

---

## What it does

### 1. Detection rules

Five rules, each mapped to a documented typology and regulatory basis:

| ID | Rule | Typology | Basis |
|----|------|----------|-------|
| R001 | Structuring Below Reporting Threshold | Structuring / Smurfing | FATF Rec. 20; EU AMLD cash thresholds |
| R002 | Rapid Pass-Through Activity | Layering / Conduit Account | FATF layering typology; EBA ML/TF guidelines |
| R003 | High-Risk Jurisdiction Exposure | Sanctions / High-Risk Country | EU AMLD Art. 18a; FATF high-risk list |
| R004 | Activity Inconsistent with Customer Profile | Unusual Activity / Profile Deviation | Risk-based approach; ongoing monitoring obligation |
| R005 | Round-Amount Transaction Concentration | Unusual Transaction Characteristics | FATF trade-based ML indicators |

Each alert carries a risk score, a plain-language finding, and the specific evidence and
transaction IDs that triggered it.

### 2. Composite customer risk scoring

Customer risk combines two components, mirroring a risk-based approach under EU AMLD:

- **Static risk** from KYC attributes: FATF-listed domicile, high-risk business sector, PEP status
- **Dynamic risk** from monitoring outcomes: alert severity and alert count

The composite score drives a HIGH / MEDIUM / LOW rating used to prioritise review.

### 3. SAR narrative generation

For any flagged customer, the system produces a structured draft report following standard
FIU submission structure: subject details, account activity summary, grounds for suspicion
with per-rule findings, risk profile breakdown, recommended next actions tailored to the
typologies detected, and a supporting transaction schedule.

### 4. Review dashboard

Five views: monitoring overview, alert queue with filtering and drill-down, customer risk
register, case file with SAR drafting, and a rule catalogue documenting detection logic and
current calibration.

---

## Threshold calibration

The central trade-off in transaction monitoring is detection coverage against alert volume.
A rule that catches everything is useless if it produces more alerts than a team can review.

R004 (profile deviation) was initially calibrated at 2.5x expected monthly volume. Across a
180-customer portfolio this produced **46 alerts**, an alert rate of roughly 26% that would
overwhelm a small compliance function and bury genuine cases.

Raising the threshold to 4x and adding a EUR 250,000 materiality floor reduced this to
**9 alerts** while retaining every genuine outlier in the dataset. Total portfolio alerts
dropped from 71 to 34, an alert rate of approximately 13% of customers, which is a reviewable
caseload.

This calibration decision is documented in the Rule Catalogue view rather than hidden in
the code, because in a real deployment threshold choices need to be explainable to both
internal audit and the regulator.

---

## Running it

```bash
pip install -r requirements.txt
python generate_data.py      # creates synthetic customer and transaction data
streamlit run app.py
```

---

## Data

The dataset is synthetic. 180 corporate customers and approximately 6,600 transactions
across a three-month period, with realistic jurisdiction distribution, business-type mix,
and declared volume profiles.

Suspicious patterns are deliberately embedded: structuring sequences below the cash reporting
threshold, rapid pass-through pairs routed to high-risk jurisdictions, round-value transfers
to FATF-listed countries, and volume spikes well beyond declared profiles. This allows the
rules to be validated against known positives.

No real customer data is used.

---

## Project structure

```
aml-monitor/
├── app.py              # Streamlit dashboard
├── rules_engine.py     # Detection rules, risk scoring, rule catalogue
├── sar_generator.py    # SAR narrative construction
├── generate_data.py    # Synthetic dataset generator
├── data/
│   ├── customers.csv
│   └── transactions.csv
└── requirements.txt
```

---

## Limitations

This is a demonstration system, not production software. A deployed monitoring platform
would additionally require: integration with sanctions and PEP screening providers, adverse
media screening, network analysis to detect related-party structures, case management with
audit trails and four-eyes sign-off, model validation and back-testing, and tuning against
historical confirmed-SAR outcomes rather than synthetic patterns.

The rules here are deterministic and transparent by design. Production systems increasingly
supplement rule-based detection with behavioural models, but rules remain the explainable
backbone that regulators expect to see documented.

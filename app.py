"""
AML Transaction Monitoring System
Streamlit dashboard for alert triage, customer risk review, and SAR drafting.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from rules_engine import run_all_rules, score_customer_risk, RULE_CATALOGUE
from sar_generator import generate_sar_narrative

st.set_page_config(page_title="AML Transaction Monitoring", layout="wide",
                   initial_sidebar_state="expanded")

ACCENT = "#2c3e6b"
RISK_COLORS = {"HIGH": "#c0392b", "MEDIUM": "#e67e22", "LOW": "#27ae60"}

st.markdown("""
<style>
.main .block-container {padding-top: 2rem;}
h1 {color: #2c3e6b; font-size: 1.9rem;}
h2 {color: #2c3e6b; font-size: 1.3rem; margin-top: 1.2rem;}
h3 {color: #333; font-size: 1.05rem;}
.stMetric {background: #f8f9fa; padding: 0.8rem; border-radius: 6px;
           border-left: 3px solid #2c3e6b;}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_data():
    txns = pd.read_csv("data/transactions.csv", parse_dates=["timestamp"])
    custs = pd.read_csv("data/customers.csv")
    return txns, custs


@st.cache_data
def run_monitoring(_txns, _custs):
    alerts = run_all_rules(_txns, _custs)
    scores = score_customer_risk(_custs, _txns, alerts)
    return alerts, scores


txns, custs = load_data()
alerts, risk_scores = run_monitoring(txns, custs)

# ===== SIDEBAR =====
st.sidebar.markdown("### AML Transaction Monitoring")
st.sidebar.caption("Rule-based detection aligned with FATF typologies and EU AMLD requirements.")
st.sidebar.markdown("---")

page = st.sidebar.radio("View", [
    "Monitoring Overview",
    "Alert Queue",
    "Customer Risk Register",
    "Case File & SAR",
    "Rule Catalogue",
])

st.sidebar.markdown("---")
st.sidebar.markdown("**Portfolio**")
st.sidebar.write(f"Customers: {len(custs):,}")
st.sidebar.write(f"Transactions: {len(txns):,}")
st.sidebar.write(f"Volume: EUR {txns.amount_eur.sum()/1e6:,.1f}M")
st.sidebar.write(f"Period: {txns.timestamp.min().date()} to {txns.timestamp.max().date()}")
st.sidebar.markdown("---")
st.sidebar.caption("Synthetic data. Built for demonstration of AML monitoring logic.")


# ===== PAGE 1: OVERVIEW =====
if page == "Monitoring Overview":
    st.title("Transaction Monitoring Overview")
    st.caption(
        f"Review period {txns.timestamp.min().date()} to {txns.timestamp.max().date()} · "
        f"{len(custs)} customers · {len(txns):,} transactions"
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Open alerts", len(alerts))
    c2.metric("Customers alerted", alerts.customer_id.nunique() if not alerts.empty else 0)
    c3.metric("High risk", (risk_scores.risk_rating == "HIGH").sum())
    c4.metric("Medium risk", (risk_scores.risk_rating == "MEDIUM").sum())
    alert_rate = alerts.customer_id.nunique() / len(custs) * 100 if not alerts.empty else 0
    c5.metric("Alert rate", f"{alert_rate:.1f}%")

    st.markdown("---")
    left, right = st.columns([1.2, 1])

    with left:
        st.subheader("Alerts by typology")
        if not alerts.empty:
            by_typ = alerts.groupby("typology").agg(
                alerts=("alert_id", "count"),
                avg_score=("risk_score", "mean")
            ).reset_index().sort_values("alerts", ascending=True)
            fig = px.bar(by_typ, x="alerts", y="typology", orientation="h",
                         color="avg_score", color_continuous_scale="Reds",
                         labels={"alerts": "Alert count", "typology": "",
                                 "avg_score": "Mean risk score"})
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                              coloraxis_colorbar=dict(title="Mean<br>score"))
            st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("Customer risk distribution")
        dist = risk_scores.risk_rating.value_counts().reindex(["HIGH", "MEDIUM", "LOW"]).fillna(0)
        fig = go.Figure(go.Bar(
            x=dist.index, y=dist.values,
            marker_color=[RISK_COLORS[r] for r in dist.index],
            text=dist.values.astype(int), textposition="outside",
        ))
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                          yaxis_title="Customers", xaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Transaction volume over time")
    daily = txns.set_index("timestamp").resample("D").agg(
        volume=("amount_eur", "sum"), count=("transaction_id", "count")
    ).reset_index()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily.timestamp, y=daily.volume, mode="lines",
                             name="Daily volume", line=dict(color=ACCENT, width=1.5),
                             fill="tozeroy", fillcolor="rgba(44,62,107,0.12)"))
    fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                      yaxis_title="EUR", xaxis_title="")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Jurisdiction exposure")
    HIGH_RISK = {"IR", "KP", "MM", "SY", "YE", "AF"}
    MONITORED = {"PA", "AE", "TR", "VN", "PH", "NG", "KE", "ZA", "HR", "BG", "MC"}
    jur = txns.groupby("counterparty_jurisdiction").agg(
        transactions=("transaction_id", "count"), volume=("amount_eur", "sum")
    ).reset_index()
    jur["category"] = jur.counterparty_jurisdiction.apply(
        lambda x: "FATF high-risk" if x in HIGH_RISK
        else ("Increased monitoring" if x in MONITORED else "Standard"))
    jur = jur.sort_values("volume", ascending=False).head(18)
    fig = px.bar(jur, x="counterparty_jurisdiction", y="volume", color="category",
                 color_discrete_map={"FATF high-risk": "#c0392b",
                                     "Increased monitoring": "#e67e22",
                                     "Standard": "#95a5a6"},
                 labels={"volume": "Volume (EUR)", "counterparty_jurisdiction": "", "category": ""})
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)


# ===== PAGE 2: ALERT QUEUE =====
elif page == "Alert Queue":
    st.title("Alert Queue")
    st.caption("Alerts ranked by risk score. Each alert carries the triggering rule, typology, and supporting evidence.")

    if alerts.empty:
        st.info("No alerts generated.")
    else:
        f1, f2, f3 = st.columns(3)
        typ_filter = f1.multiselect("Typology", sorted(alerts.typology.unique()),
                                    default=sorted(alerts.typology.unique()))
        rule_filter = f2.multiselect("Rule", sorted(alerts.rule_id.unique()),
                                     default=sorted(alerts.rule_id.unique()))
        min_score = f3.slider("Minimum risk score", 0, 100, 0)

        filtered = alerts[
            alerts.typology.isin(typ_filter) &
            alerts.rule_id.isin(rule_filter) &
            (alerts.risk_score >= min_score)
        ]

        st.write(f"**{len(filtered)} alert(s)**")
        st.markdown("---")

        for _, a in filtered.iterrows():
            cust = custs[custs.customer_id == a.customer_id].iloc[0]
            risk = risk_scores[risk_scores.customer_id == a.customer_id].iloc[0]
            color = "#c0392b" if a.risk_score >= 75 else ("#e67e22" if a.risk_score >= 55 else "#f1c40f")

            with st.expander(
                f"{a.alert_id}  ·  {a.rule_name}  ·  {a.customer_id} ({cust.customer_name})  ·  Score {a.risk_score}",
                expanded=False
            ):
                m1, m2, m3, m4 = st.columns(4)
                m1.markdown(f"**Risk score**<br><span style='font-size:1.6rem;color:{color}'>{a.risk_score}</span>",
                            unsafe_allow_html=True)
                m2.markdown(f"**Rule**<br>{a.rule_id}", unsafe_allow_html=True)
                m3.markdown(f"**Customer rating**<br><span style='color:{RISK_COLORS[risk.risk_rating]}'>{risk.risk_rating}</span>",
                            unsafe_allow_html=True)
                m4.markdown(f"**Transactions**<br>{a.transaction_count}", unsafe_allow_html=True)

                st.markdown(f"**Typology:** {a.typology}")
                st.markdown(f"**Finding:** {a.description}")
                st.markdown(f"**Evidence:** `{a.evidence}`")
                st.markdown(f"**Customer profile:** {cust.business_type} · domicile {cust.jurisdiction}"
                            + (" · **PEP**" if cust.pep_flag else ""))

                tids = a.transaction_ids.split(";")
                detail = txns[txns.transaction_id.isin(tids)][
                    ["transaction_id", "timestamp", "transaction_type",
                     "amount_eur", "counterparty_jurisdiction", "channel"]
                ].sort_values("timestamp")
                st.markdown("**Triggering transactions:**")
                st.dataframe(detail, use_container_width=True, hide_index=True)


# ===== PAGE 3: CUSTOMER RISK REGISTER =====
elif page == "Customer Risk Register":
    st.title("Customer Risk Register")
    st.caption("Composite risk rating combining static KYC factors with transaction-monitoring outcomes.")

    f1, f2, f3 = st.columns(3)
    rating_filter = f1.multiselect("Risk rating", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM"])
    jur_filter = f2.multiselect("Jurisdiction", sorted(risk_scores.jurisdiction.unique()), default=[])
    alerted_only = f3.checkbox("Alerted customers only", value=False)

    view = risk_scores[risk_scores.risk_rating.isin(rating_filter)]
    if jur_filter:
        view = view[view.jurisdiction.isin(jur_filter)]
    if alerted_only:
        view = view[view.alert_count > 0]

    st.write(f"**{len(view)} customer(s)**")

    display = view[["customer_id", "customer_name", "jurisdiction", "business_type",
                    "pep_flag", "static_risk", "dynamic_risk", "total_risk_score",
                    "risk_rating", "alert_count", "transaction_count", "total_volume"]].copy()
    display["total_volume"] = display.total_volume.apply(lambda x: f"{x:,.0f}")

    st.dataframe(display, use_container_width=True, hide_index=True,
                 column_config={
                     "customer_id": "Customer ID",
                     "customer_name": "Name",
                     "jurisdiction": "Jur.",
                     "business_type": "Business type",
                     "pep_flag": "PEP",
                     "static_risk": st.column_config.NumberColumn("Static", help="KYC-based risk"),
                     "dynamic_risk": st.column_config.NumberColumn("Dynamic", help="Monitoring-based risk"),
                     "total_risk_score": st.column_config.ProgressColumn("Composite", min_value=0, max_value=100),
                     "risk_rating": "Rating",
                     "alert_count": "Alerts",
                     "transaction_count": "Txns",
                     "total_volume": "Volume (EUR)",
                 })

    st.markdown("---")
    st.subheader("Risk composition: static vs dynamic")
    fig = px.scatter(view, x="static_risk", y="dynamic_risk", size="total_volume",
                     color="risk_rating", color_discrete_map=RISK_COLORS,
                     hover_data=["customer_id", "business_type", "jurisdiction"],
                     labels={"static_risk": "Static (KYC) risk",
                             "dynamic_risk": "Dynamic (monitoring) risk",
                             "risk_rating": "Rating"})
    fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)


# ===== PAGE 4: CASE FILE & SAR =====
elif page == "Case File & SAR":
    st.title("Case File and SAR Drafting")
    st.caption("Select a flagged customer to review the full case and generate a draft suspicious activity report.")

    alerted = risk_scores[risk_scores.alert_count > 0].sort_values("total_risk_score", ascending=False)
    if alerted.empty:
        st.info("No alerted customers.")
    else:
        options = [f"{r.customer_id} — {r.customer_name} ({r.risk_rating}, {r.alert_count} alert(s))"
                   for _, r in alerted.iterrows()]
        choice = st.selectbox("Customer", options)
        cid = choice.split(" — ")[0]

        cust = custs[custs.customer_id == cid].iloc[0]
        risk = risk_scores[risk_scores.customer_id == cid].iloc[0]
        cust_txns = txns[txns.customer_id == cid]
        cust_alerts = alerts[alerts.customer_id == cid]

        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Composite risk", f"{risk.total_risk_score}/100", risk.risk_rating)
        c2.metric("Open alerts", risk.alert_count)
        c3.metric("Transactions", f"{len(cust_txns):,}")
        c4.metric("Total volume", f"EUR {cust_txns.amount_eur.sum():,.0f}")

        st.markdown("---")
        left, right = st.columns([1, 1])
        with left:
            st.subheader("Customer profile")
            st.write(f"**Name:** {cust.customer_name}")
            st.write(f"**Domicile:** {cust.jurisdiction}")
            st.write(f"**Business:** {cust.business_type}")
            st.write(f"**Relationship since:** {cust.account_opened}")
            st.write(f"**PEP:** {'Yes' if cust.pep_flag else 'No'}")
            st.write(f"**Declared monthly volume:** EUR {cust.expected_monthly_volume:,.0f}")
            st.write(f"**Risk factors:** {risk.risk_factors}")

        with right:
            st.subheader("Activity timeline")
            fig = px.scatter(cust_txns, x="timestamp", y="amount_eur",
                             color="transaction_type", size="amount_eur",
                             labels={"timestamp": "", "amount_eur": "EUR",
                                     "transaction_type": ""})
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                              legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.subheader("Triggered alerts")
        for _, a in cust_alerts.sort_values("risk_score", ascending=False).iterrows():
            st.markdown(f"**{a.rule_id} · {a.rule_name}** (score {a.risk_score})")
            st.write(a.description)
            st.caption(a.evidence)
            st.markdown("")

        st.markdown("---")
        st.subheader("Draft SAR narrative")
        narrative = generate_sar_narrative(cid, custs, txns, alerts, risk_scores)
        st.code(narrative, language=None)
        st.download_button("Download SAR draft (.txt)", narrative,
                           file_name=f"SAR_{cid}.txt", mime="text/plain")


# ===== PAGE 5: RULE CATALOGUE =====
elif page == "Rule Catalogue":
    st.title("Rule Catalogue")
    st.caption("Detection rules, their regulatory basis, and current calibration.")

    for rule in RULE_CATALOGUE:
        fired = len(alerts[alerts.rule_id == rule["id"]]) if not alerts.empty else 0
        with st.expander(f"{rule['id']} · {rule['name']}  —  {fired} alert(s)", expanded=False):
            st.markdown(f"**Typology:** {rule['typology']}")
            st.markdown(f"**Regulatory basis:** {rule['basis']}")
            st.markdown(f"**Detection logic:** {rule['logic']}")
            if fired:
                sub = alerts[alerts.rule_id == rule["id"]]
                st.markdown(f"**Current performance:** {fired} alerts across "
                            f"{sub.customer_id.nunique()} customer(s), "
                            f"mean risk score {sub.risk_score.mean():.0f}.")

    st.markdown("---")
    st.subheader("Calibration note")
    st.write(
        "Rule thresholds balance detection coverage against alert volume. R004 "
        "(profile deviation) was initially calibrated at 2.5x expected volume, which "
        "produced 46 alerts across the portfolio — an alert rate too high for a team "
        "to review meaningfully. Raising the threshold to 4x and adding a EUR 250,000 "
        "materiality floor reduced it to 9 alerts while retaining the genuine outliers. "
        "This trade-off between false positives and detection coverage is the central "
        "calibration problem in transaction monitoring."
    )

    st.markdown("---")
    st.subheader("Alert distribution by rule")
    if not alerts.empty:
        by_rule = alerts.groupby(["rule_id", "rule_name"]).agg(
            alerts=("alert_id", "count"), mean_score=("risk_score", "mean")
        ).reset_index()
        fig = px.bar(by_rule, x="rule_id", y="alerts", color="mean_score",
                     color_continuous_scale="Reds", hover_data=["rule_name"],
                     labels={"alerts": "Alerts", "rule_id": "", "mean_score": "Mean score"})
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

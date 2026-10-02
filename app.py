import csv
import html
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote_plus

import requests
import streamlit as st

st.set_page_config(page_title="Hospitality Lead Hunter", page_icon="🎯", layout="wide")

MIDWEST = [
    "South Dakota", "Iowa", "Minnesota", "Nebraska", "North Dakota",
    "Wisconsin", "Illinois", "Michigan", "Indiana", "Ohio", "Missouri", "Kansas"
]

SIGNALS = {
    "Turnaround / Trouble": [
        "restaurant struggling owner",
        "restaurant turnaround",
        "bar struggling owner",
        "restaurant closing owner",
    ],
    "Management": [
        "restaurant hiring general manager",
        "bar hiring general manager",
        "hotel hiring general manager",
        "restaurant under new management",
    ],
    "Opening / Reopening": [
        "restaurant opening soon",
        "bar opening soon",
        "restaurant reopening",
        "hotel reopening",
    ],
    "Ownership / Sale": [
        "restaurant for sale owner",
        "bar for sale owner",
        "restaurant new ownership",
        "restaurant business for sale",
    ],
    "Staffing / Labor": [
        "restaurant staffing shortage",
        "restaurant reduced hours staffing",
        "restaurant hiring managers",
        "hospitality staffing problems",
    ],
    "Expansion / Growth": [
        "restaurant expanding new location",
        "hospitality group expansion",
        "brewery opening new location",
        "hotel expansion management",
    ],
}

HOT = [
    "struggling", "turnaround", "closing", "for sale", "under new management",
    "reopening", "consultant", "needs help", "reduced hours"
]
WARM = [
    "hiring", "general manager", "opening soon", "new ownership",
    "operations", "staffing", "expansion", "new location"
]
HOSPITALITY = ["restaurant", "bar", "hotel", "brewery", "cafe", "hospitality", "resort"]


def google_news(query: str):
    url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    response = requests.get(
        url,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0 HospitalityLeadHunter/1.0"},
    )
    response.raise_for_status()

    root = ET.fromstring(response.text)
    rows = []

    for item in root.findall(".//item"):
        description = item.findtext("description") or ""
        description = re.sub("<[^>]+>", " ", html.unescape(description))
        description = re.sub(r"\s+", " ", description).strip()

        rows.append({
            "title": item.findtext("title") or "",
            "url": item.findtext("link") or "",
            "date": item.findtext("pubDate") or "",
            "source": item.findtext("source") or "",
            "evidence": description,
        })

    return rows


def opportunity_score(lead):
    text = f'{lead["title"]} {lead["evidence"]}'.lower()
    score = 10
    score += 14 * sum(keyword in text for keyword in HOT)
    score += 6 * sum(keyword in text for keyword in WARM)

    if any(keyword in text for keyword in HOSPITALITY):
        score += 15

    if lead.get("market") in MIDWEST:
        score += 5

    return min(100, score)


def status_for(score):
    if score >= 70:
        return "🔥 HIGH PRIORITY"
    if score >= 50:
        return "🟠 STRONG"
    return "🔎 REVIEW"


def likely_need(lead):
    text = f'{lead["title"]} {lead["evidence"]}'.lower()

    if any(k in text for k in ["general manager", "manager", "staffing", "hiring"]):
        return "Leadership, labor structure, training, accountability"
    if any(k in text for k in ["for sale", "new ownership", "under new management"]):
        return "Operational assessment, transition systems, profitability"
    if any(k in text for k in ["opening", "reopening", "new location"]):
        return "Opening systems, SOPs, staffing, training, launch execution"
    if any(k in text for k in ["closing", "struggling", "reduced hours", "turnaround"]):
        return "Turnaround, labor, menu mix, cost controls, operating systems"
    return "Operational assessment and performance improvement"


def outreach_angle(lead):
    return (
        "Reference the public signal first, then offer a short operational conversation. "
        f"Best-fit angle: {likely_need(lead)}."
    )


def csv_bytes(leads):
    output = io.StringIO()
    fields = [
        "score", "status", "title", "market", "signal", "source",
        "date", "likely_need", "outreach_angle", "url"
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()

    for lead in leads:
        row = dict(lead)
        row["status"] = status_for(lead["score"])
        row["likely_need"] = likely_need(lead)
        row["outreach_angle"] = outreach_angle(lead)
        writer.writerow({k: row.get(k, "") for k in fields})

    return output.getvalue().encode("utf-8")


st.title("🎯 Hospitality Lead Hunter")
st.caption("Public-signal prospecting for hospitality consulting • Midwest-first • Nationwide-ready")

with st.sidebar:
    st.header("Hunt Controls")
    territory = st.radio("Territory", ["Midwest Priority", "Nationwide", "Custom"])

    if territory == "Midwest Priority":
        markets = st.multiselect(
            "States",
            MIDWEST,
            default=["South Dakota", "Iowa", "Minnesota", "Nebraska", "North Dakota", "Wisconsin"],
        )
    elif territory == "Custom":
        custom = st.text_input("City, state, region, or state")
        markets = [custom.strip()] if custom.strip() else []
    else:
        markets = ["United States"]

    selected_signals = st.multiselect(
        "Opportunity signals",
        list(SIGNALS),
        default=list(SIGNALS),
    )

    depth = st.slider("Search depth", 1, 4, 2)
    minimum = st.slider("Minimum opportunity score", 0, 100, 35)

hunt = st.button("🔥 HUNT FOR OPPORTUNITIES", type="primary", use_container_width=True)

if hunt:
    found = []
    seen = set()

    if not markets:
        st.warning("Choose at least one market.")
    else:
        with st.spinner("Scanning current public hospitality signals..."):
            for market in markets:
                for signal in selected_signals:
                    for base_query in SIGNALS[signal][:depth]:
                        try:
                            results = google_news(f'{base_query} "{market}"')
                        except Exception:
                            continue

                        for lead in results:
                            key = lead["url"] or lead["title"]
                            if key in seen:
                                continue

                            seen.add(key)
                            lead["signal"] = signal
                            lead["market"] = market
                            lead["score"] = opportunity_score(lead)

                            if lead["score"] >= minimum:
                                found.append(lead)

        st.session_state["leads"] = sorted(found, key=lambda x: x["score"], reverse=True)

leads = st.session_state.get("leads", [])

if leads:
    c1, c2, c3 = st.columns(3)
    c1.metric("Leads Found", len(leads))
    c2.metric("High Priority", sum(x["score"] >= 70 for x in leads))
    c3.metric("Strong", sum(50 <= x["score"] < 70 for x in leads))

    st.divider()

    for lead in leads[:100]:
        with st.expander(f'{status_for(lead["score"])} • {lead["score"]}/100 • {lead["title"]}'):
            st.write(f'**Market:** {lead["market"]}  |  **Signal:** {lead["signal"]}')
            st.write(f'**Source:** {lead["source"] or "Unknown"}  |  **Published:** {lead["date"] or "Unknown"}')
            st.write(f'**Likely need:** {likely_need(lead)}')
            st.write(f'**Outreach angle:** {outreach_angle(lead)}')

            if lead["evidence"]:
                st.write("**Evidence:**")
                st.write(lead["evidence"])

            if lead["url"]:
                st.link_button("OPEN EVIDENCE", lead["url"], use_container_width=True)

    st.download_button(
        "⬇️ EXPORT LEADS TO CSV",
        csv_bytes(leads),
        f'hospitality_leads_{datetime.now():%Y%m%d_%H%M}.csv',
        "text/csv",
        use_container_width=True,
    )
else:
    st.info("Choose your territory and tap HUNT FOR OPPORTUNITIES.")

st.caption(
    "Scores are prospecting signals, not proof that a business is distressed. "
    "Review the linked evidence before outreach."
)

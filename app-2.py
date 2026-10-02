import csv
import html
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests
import streamlit as st

st.set_page_config(
    page_title="Hospitality Lead Hunter",
    page_icon="🎯",
    layout="wide",
)

MIDWEST = {
    "South Dakota": "SD",
    "Iowa": "IA",
    "Minnesota": "MN",
    "Nebraska": "NE",
    "North Dakota": "ND",
    "Wisconsin": "WI",
    "Illinois": "IL",
    "Michigan": "MI",
    "Indiana": "IN",
    "Ohio": "OH",
    "Missouri": "MO",
    "Kansas": "KS",
}

SIGNALS = {
    "Help Wanted / Management Gap": [
        "local restaurant hiring general manager",
        "bar grill hiring general manager",
        "restaurant help wanted manager",
        "restaurant hiring kitchen manager",
        "restaurant hiring operations manager",
        "bar hiring manager owner",
        "restaurant staffing shortage owner",
    ],
    "Operational Stress": [
        "local restaurant reduced hours staffing",
        "bar grill reduced hours staffing",
        "restaurant struggling owner local",
        "restaurant labor costs owner local",
        "restaurant business slow owner local",
        "restaurant turnaround owner local",
    ],
    "Ownership Transition": [
        "local restaurant new ownership",
        "bar grill new ownership",
        "restaurant under new management local",
        "restaurant sold new owner local",
        "family restaurant new owner",
    ],
    "Opening / Reopening": [
        "local restaurant reopening",
        "bar grill reopening",
        "restaurant opening soon owner local",
        "family restaurant opening soon",
        "independent restaurant reopening",
    ],
    "Expansion / Growth": [
        "local restaurant opening second location",
        "independent restaurant expansion owner",
        "brewery new location owner local",
        "bar grill expansion owner",
    ],
}

HIGH_VALUE = [
    "help wanted", "hiring general manager", "hiring manager",
    "kitchen manager", "operations manager", "staffing shortage",
    "reduced hours", "struggling", "turnaround", "slow business",
    "under new management", "new ownership", "new owner", "reopening",
]

MEDIUM_VALUE = [
    "hiring", "manager", "opening soon", "expansion",
    "new location", "second location", "operations",
]

INDEPENDENT_BOOST = [
    "locally owned", "local restaurant", "family owned", "family-owned",
    "independent restaurant", "independently owned", "owner-operated",
    "bar and grill", "bar & grill", "grill and bar", "tavern", "pub",
    "neighborhood bar", "sports bar", "brewpub", "supper club",
    "mom and pop", "small business",
]

CHAIN_NAMES = [
    "outback steakhouse", "panera", "applebee", "chili's", "chilis",
    "red robin", "hardee", "burger king", "mcdonald", "wendy's",
    "cracker barrel", "denny's", "tgi friday", "hooters", "subway",
    "starbucks", "olive garden", "longhorn steakhouse", "buffalo wild wings",
    "texas roadhouse", "ihop", "perkins", "arbys", "arby's",
    "taco bell", "kfc", "pizza hut", "domino", "little caesars",
    "five guys", "jersey mike", "jimmy john", "culver's", "culvers",
    "chipotle", "qdoba", "raising cane", "sonic drive-in", "dairy queen",
]

CORPORATE_TERMS = [
    "parent company", "corporate-owned", "earnings call", "nasdaq", "nyse",
    "franchisee terminates", "portfolio", "shareholders", "quarterly earnings",
    "systemwide sales", "same-store sales",
]

EXIT_ONLY = [
    "retiring", "retirement", "time for a new adventure", "moving away",
    "closing at the end of the year", "last day", "final day",
]

INDUSTRY_SOURCES = [
    "restaurant business", "the street", "usa today", "forbes",
    "marketwatch", "finance.yahoo", "benzinga",
]

LOCAL_SOURCE_HINTS = [
    "abc", "nbc", "cbs", "fox", "radio", "daily", "tribune", "journal",
    "gazette", "register", "argus", "keloland", "kelo", "kcci", "kcrg",
    "ktiv", "kotatv", "wowt", "ketv", "kare", "wcco", "local",
]

HOSPITALITY = [
    "restaurant", "bar", "hotel", "brewery", "cafe", "coffee",
    "hospitality", "resort", "grill", "pub", "tavern",
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def google_news(query):
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    r = requests.get(
        url,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0 HospitalityLeadHunter/3.0"},
    )
    r.raise_for_status()

    root = ET.fromstring(r.text)
    rows = []

    for item in root.findall(".//item"):
        description = item.findtext("description") or ""
        description = re.sub("<[^>]+>", " ", html.unescape(description))

        rows.append({
            "title": clean(item.findtext("title")),
            "url": item.findtext("link") or "",
            "date": item.findtext("pubDate") or "",
            "source": clean(item.findtext("source")),
            "evidence": clean(description),
        })

    return rows


def age_days(date_text):
    if not date_text:
        return 9999

    try:
        dt = parsedate_to_datetime(date_text)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)

        return max(
            0,
            (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days
        )
    except Exception:
        return 9999


def location_match(text, market):
    if market == "United States":
        return True

    t = text.lower()
    state = market.lower()
    abbr = MIDWEST.get(market, "").lower()

    return state in t or (
        abbr and re.search(rf"\b{re.escape(abbr)}\b", t, re.I)
    )


def is_chain(text):
    t = text.lower()
    return any(name in t for name in CHAIN_NAMES)


def independent_signal(text):
    t = text.lower()
    return any(term in t for term in INDEPENDENT_BOOST)


def classify_fit(lead):
    text = f'{lead["title"]} {lead["evidence"]} {lead["source"]}'.lower()

    if is_chain(text):
        return "LOW FIT", "Large chain/franchise lead — harder consulting sale"

    if any(k in text for k in CORPORATE_TERMS):
        return "LOW FIT", "Corporate-level story rather than local operator opportunity"

    if any(k in text for k in EXIT_ONLY) and not any(
        k in text for k in [
            "new owner", "new ownership", "under new management", "reopening"
        ]
    ):
        return "WATCH", "Exit/closure story; successor or buyer may be the better prospect"

    if any(k in text for k in HIGH_VALUE):
        return "CONSULT", "Current operator, labor, leadership, or turnaround signal"

    if any(k in text for k in MEDIUM_VALUE):
        return "WATCH", "Potential opportunity worth verifying"

    return "LOW FIT", "Weak consulting signal"


def score_lead(lead):
    text = f'{lead["title"]} {lead["evidence"]} {lead["source"]}'.lower()
    age = lead["age_days"]

    score = 0

    # Recency
    if age <= 7:
        score += 32
    elif age <= 14:
        score += 28
    elif age <= 30:
        score += 22
    elif age <= 60:
        score += 14
    elif age <= 90:
        score += 7

    # Hospitality relevance
    if any(k in text for k in HOSPITALITY):
        score += 10

    # Strong signals
    score += min(40, 12 * sum(k in text for k in HIGH_VALUE))
    score += min(15, 5 * sum(k in text for k in MEDIUM_VALUE))

    # Independent / mom-and-pop boost
    if independent_signal(text):
        score += 18

    # Local-media boost
    if any(k in text for k in LOCAL_SOURCE_HINTS):
        score += 6

    # Geographic fit
    if lead["location_match"]:
        score += 10

    # Midwest-first
    if lead["market"] in MIDWEST:
        score += 5

    # Chain penalty
    if is_chain(text):
        score -= 45

    # Corporate-story penalty
    if any(k in text for k in CORPORATE_TERMS):
        score -= 30

    # Exit-only penalty
    if any(k in text for k in EXIT_ONLY):
        score -= 18

    # Industry publication penalty
    if any(k in text for k in INDUSTRY_SOURCES):
        score -= 8

    fit, _ = classify_fit(lead)

    if fit == "LOW FIT":
        score = min(score, 24)
    elif fit == "WATCH":
        score = min(score, 59)

    return max(0, min(100, score))


def status_for(lead):
    if lead["fit"] == "CONSULT" and lead["score"] >= 75:
        return "🔥 PRIORITY"
    if lead["fit"] == "CONSULT" and lead["score"] >= 55:
        return "🟠 CONSULT"
    if lead["fit"] == "WATCH":
        return "👀 WATCH"
    return "⚪ LOW FIT"


def likely_need(lead):
    text = f'{lead["title"]} {lead["evidence"]}'.lower()

    if any(k in text for k in [
        "general manager", "kitchen manager", "operations manager",
        "help wanted", "staffing", "hiring"
    ]):
        return "Leadership, labor structure, recruiting, training, accountability"

    if any(k in text for k in [
        "new ownership", "new owner", "under new management", "sold"
    ]):
        return "Transition systems, KPI setup, profitability, team alignment"

    if any(k in text for k in [
        "opening", "reopening", "new location", "second location"
    ]):
        return "Opening systems, SOPs, staffing, training, launch execution"

    if any(k in text for k in [
        "struggling", "reduced hours", "slow business", "turnaround"
    ]):
        return "Turnaround, labor, menu mix, cost controls, operating systems"

    return "Operational assessment and performance improvement"


def outreach_angle(lead):
    if lead["fit"] == "LOW FIT":
        return "Do not prioritize."

    if lead["fit"] == "WATCH":
        return "Verify owner/operator, decision-maker, and current status before outreach."

    return (
        "Lead with the current public signal and offer a short operator-to-operator conversation. "
        f"Best-fit angle: {likely_need(lead)}."
    )


def csv_bytes(leads):
    output = io.StringIO()

    fields = [
        "score", "fit", "status", "title", "market", "signal", "source",
        "published", "age_days", "independent_signal", "chain_signal",
        "likely_need", "outreach_angle", "url"
    ]

    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()

    for lead in leads:
        text = f'{lead["title"]} {lead["evidence"]} {lead["source"]}'

        writer.writerow({
            "score": lead["score"],
            "fit": lead["fit"],
            "status": status_for(lead),
            "title": lead["title"],
            "market": lead["market"],
            "signal": lead["signal"],
            "source": lead["source"],
            "published": lead["date"],
            "age_days": lead["age_days"],
            "independent_signal": independent_signal(text),
            "chain_signal": is_chain(text),
            "likely_need": likely_need(lead),
            "outreach_angle": outreach_angle(lead),
            "url": lead["url"],
        })

    return output.getvalue().encode("utf-8")


st.title("🎯 Hospitality Lead Hunter")
st.caption(
    "V3 • Independent operator first • Midwest-first • Chain leads deprioritized"
)

with st.sidebar:
    st.header("Hunt Controls")

    territory = st.radio(
        "Territory",
        ["Midwest Priority", "Nationwide", "Custom"],
        index=0,
    )

    if territory == "Midwest Priority":
        markets = st.multiselect(
            "States",
            list(MIDWEST),
            default=[
                "South Dakota", "Iowa", "Minnesota",
                "Nebraska", "North Dakota", "Wisconsin"
            ],
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

    max_age = st.select_slider(
        "Maximum lead age",
        options=[7, 14, 30, 60, 90],
        value=60,
    )

    minimum = st.slider(
        "Minimum opportunity score",
        0,
        100,
        45,
    )

    show_watch = st.toggle("Include Watch leads", value=True)
    show_low = st.toggle("Include Low Fit / Chains", value=False)

hunt = st.button(
    "🔥 HUNT FOR REAL OPPORTUNITIES",
    type="primary",
    use_container_width=True,
)

if hunt:
    found = []
    seen = set()

    if not markets:
        st.warning("Choose at least one market.")
    elif not selected_signals:
        st.warning("Choose at least one opportunity signal.")
    else:
        with st.spinner("Scanning local hospitality opportunity signals..."):
            for market in markets:
                for signal in selected_signals:
                    for base_query in SIGNALS[signal]:
                        query = f'{base_query} "{market}" when:{max_age}d'

                        try:
                            results = google_news(query)
                        except Exception:
                            continue

                        for lead in results:
                            key = (lead["url"] or lead["title"]).strip().lower()

                            if not key or key in seen:
                                continue

                            seen.add(key)

                            lead["signal"] = signal
                            lead["market"] = market
                            lead["age_days"] = age_days(lead["date"])

                            if lead["age_days"] > max_age:
                                continue

                            combined = f'{lead["title"]} {lead["evidence"]}'

                            lead["location_match"] = location_match(
                                combined,
                                market,
                            )

                            if (
                                market != "United States"
                                and not lead["location_match"]
                            ):
                                continue

                            lead["fit"], lead["fit_reason"] = classify_fit(lead)
                            lead["score"] = score_lead(lead)

                            if lead["score"] < minimum:
                                continue

                            if lead["fit"] == "LOW FIT" and not show_low:
                                continue

                            if lead["fit"] == "WATCH" and not show_watch:
                                continue

                            found.append(lead)

        st.session_state["leads_v3"] = sorted(
            found,
            key=lambda x: (
                x["fit"] == "CONSULT",
                independent_signal(
                    f'{x["title"]} {x["evidence"]} {x["source"]}'
                ),
                x["score"],
                -x["age_days"],
            ),
            reverse=True,
        )

leads = st.session_state.get("leads_v3", [])

if leads:
    priority = sum(
        x["fit"] == "CONSULT" and x["score"] >= 75
        for x in leads
    )

    consult = sum(x["fit"] == "CONSULT" for x in leads)
    independent = sum(
        independent_signal(
            f'{x["title"]} {x["evidence"]} {x["source"]}'
        )
        for x in leads
    )
    chains = sum(
        is_chain(
            f'{x["title"]} {x["evidence"]} {x["source"]}'
        )
        for x in leads
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Qualified", len(leads))
    c2.metric("Priority", priority)
    c3.metric("Independent Signals", independent)
    c4.metric("Chain Leads", chains)

    st.divider()

    for lead in leads[:100]:
        text = f'{lead["title"]} {lead["evidence"]} {lead["source"]}'

        independent_tag = " • 🏠 LOCAL/INDEPENDENT" if independent_signal(text) else ""
        chain_tag = " • 🏢 CHAIN" if is_chain(text) else ""

        headline = (
            f'{status_for(lead)} • {lead["score"]}/100'
            f'{independent_tag}{chain_tag} • {lead["title"]}'
        )

        with st.expander(headline):
            st.write(
                f'**Market:** {lead["market"]}  |  '
                f'**Signal:** {lead["signal"]}  |  '
                f'**Age:** {lead["age_days"]} days'
            )

            st.write(
                f'**Fit:** {lead["fit"]} — {lead["fit_reason"]}'
            )

            st.write(
                f'**Source:** {lead["source"] or "Unknown"}  |  '
                f'**Published:** {lead["date"] or "Unknown"}'
            )

            st.write(f'**Likely need:** {likely_need(lead)}')
            st.write(f'**Recommended next step:** {outreach_angle(lead)}')

            if lead["evidence"]:
                st.write("**Evidence:**")
                st.write(lead["evidence"])

            if lead["url"]:
                st.link_button(
                    "OPEN EVIDENCE",
                    lead["url"],
                    use_container_width=True,
                )

    st.download_button(
        "⬇️ EXPORT QUALIFIED LEADS TO CSV",
        csv_bytes(leads),
        f'hospitality_leads_v3_{datetime.now():%Y%m%d_%H%M}.csv',
        "text/csv",
        use_container_width=True,
    )

else:
    st.info(
        "Tap HUNT FOR REAL OPPORTUNITIES. "
        "V3 intentionally favors local independent operators and management/staffing signals."
    )

st.caption(
    "V3 deprioritizes chains and corporate stories. "
    "Scores rank public prospecting signals, not proof of business distress."
)

"""BGI Design System — Lightweight Intelligence Command Post."""

# ── Palette ──────────────────────────────────────────────────────────────────
WHITE      = "#FFFFFF"
BG_BASE    = "#F6F8FA"
BG_CARD    = "#FFFFFF"
BG_SIDEBAR = "#E9EEF3"
TEXT_MAIN  = "#17202A"
TEXT_SOFT  = "#52616F"
TEXT_MUTED = "#8391A1"
ACCENT     = "#2F6F8F"
ACCENT_DARK= "#234F66"
SAGE       = "#4E8D72"
SAGE_DARK  = "#376C56"
SLATE      = "#627386"
ROSE       = "#B85C5C"
ROSE_DARK  = "#8F3F45"
BORDER     = "#DCE3EA"
DIVIDER    = "#E8EDF2"
GOLD       = "#B48A3C"
INK        = "#111827"

# Risk colors
RED_CRIT   = "#D14343"
ORANGE_HI  = "#E07B39"
AMBER_MED  = "#D4A43A"
SLATE_LO   = "#6D7D8E"

# Entity type colors (for graph / chips)
ECOLOR = {
    "wechat": "#C47A7A", "qq": "#C47A7A", "phone": "#C47A7A", "telegram": "#C47A7A",
    "url": "#7A8EA0", "domain": "#7A8EA0", "ip": "#7A8EA0",
    "bank_card": "#8EA090", "alipay": "#8EA090",
    "tool": "#C4A35A",
    "slang": "#9A8EA0", "feature": "#8EA0A0",
}

# ── Typography ───────────────────────────────────────────────────────────────
FONT_DISPLAY = "Noto Serif SC"
FONT_BODY    = "system-ui, -apple-system, 'Segoe UI', sans-serif"
FONT_MONO    = "JetBrains Mono"

# ── CSS ──────────────────────────────────────────────────────────────────────
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Noto+Serif+SC:wght@400;500;600;700&display=swap');

/* ═══ Shell ═══ */
.stApp {{
    background: {BG_BASE};
}}
.stMainBlock {{
    padding-top: 1rem;
}}

header[data-testid="stHeader"] {{
    background: transparent !important;
    box-shadow: none !important;
    border-bottom: 1px solid {DIVIDER};
}}

#MainMenu, footer, .viewerBadge_container__r5tak {{
    display: none !important;
}}

[data-testid="collapsedControl"] {{
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    z-index: 999999 !important;
    background: {BG_SIDEBAR} !important;
    border: 1px solid {BORDER} !important;
    border-left: none !important;
    border-radius: 0 8px 8px 0 !important;
    padding: 0.5rem 0.3rem !important;
    position: fixed !important;
    left: 0 !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
    box-shadow: 2px 0 8px rgba(30,27,24,0.06) !important;
}}
[data-testid="collapsedControl"] button {{
    color: {TEXT_MAIN} !important;
    font-size: 1.1rem !important;
    font-weight: 600 !important;
    background: transparent !important;
    border: none !important;
    padding: 4px 6px !important;
    cursor: pointer !important;
}}
[data-testid="collapsedControl"]:hover {{
    background: {BG_CARD} !important;
    box-shadow: 2px 0 12px rgba(30,27,24,0.10) !important;
}}

[data-testid="stSidebar"] button[kind="header"] {{
    color: {TEXT_SOFT} !important;
    opacity: 1 !important;
}}
[data-testid="stSidebar"] button[kind="header"]:hover {{
    color: {TEXT_MAIN} !important;
    background: {BG_BASE} !important;
}}

/* ═══ Sidebar ═══ */
[data-testid="stSidebar"] {{
    background: {BG_SIDEBAR};
    border-right: 1px solid {BORDER};
}}
[data-testid="stSidebar"] .stMarkdown {{
    padding: 0 0.5rem;
}}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
    gap: 0.15rem;
}}
[data-testid="stSidebar"] .stRadio > div {{
    gap: 0.1rem;
}}
[data-testid="stSidebar"] .stRadio label {{
    padding: 0.45rem 0.75rem;
    border-radius: 6px;
    font-size: 0.84rem;
    font-weight: 450;
    color: {TEXT_SOFT};
    transition: all 0.15s;
    cursor: pointer;
}}
[data-testid="stSidebar"] .stRadio label:hover {{
    background: {BG_BASE};
    color: {TEXT_MAIN};
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
    background: {BG_CARD} !important;
    color: {TEXT_MAIN} !important;
    font-weight: 550 !important;
    border: 1px solid {BORDER};
    box-shadow: 0 1px 3px rgba(30,27,24,0.04);
}}

/* ═══ Typography ═══ */
h1, h2, h3, h4 {{
    letter-spacing: 0 !important;
    font-family: {FONT_BODY} !important;
}}
h1 {{ color: {TEXT_MAIN} !important; font-weight: 600 !important; font-size: 1.4rem !important; }}
h2 {{ color: {TEXT_MAIN} !important; font-weight: 550 !important; font-size: 1.1rem !important; }}
h3 {{ color: {TEXT_SOFT} !important; font-weight: 500 !important; font-size: 0.95rem !important; }}

.stCaption {{
    font-family: {FONT_BODY} !important;
    color: {TEXT_MUTED} !important;
    font-size: 0.8rem !important;
}}

/* ═══ Metric cards — compact ═══ */
[data-testid="stMetric"] {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 0.7rem 1rem;
    box-shadow: none;
    transition: border-color 0.15s;
}}
[data-testid="stMetric"]:hover {{
    border-color: {ACCENT};
}}
[data-testid="stMetric"] label {{
    color: {TEXT_MUTED} !important;
    font-size: 0.68rem !important;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-family: {FONT_BODY} !important;
}}
[data-testid="stMetricValue"] {{
    color: {TEXT_MAIN} !important;
    font-size: 1.6rem !important;
    font-weight: 550 !important;
    font-family: {FONT_MONO}, monospace !important;
}}

/* ═══ Tables — higher density ═══ */
[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    overflow: hidden;
}}
[data-testid="stDataFrame"] th {{
    background: {BG_SIDEBAR} !important;
    color: {TEXT_SOFT} !important;
    font-weight: 500 !important;
    font-size: 0.72rem !important;
    padding: 0.35rem 0.6rem !important;
    font-family: {FONT_BODY} !important;
    letter-spacing: 0.03em;
    text-transform: uppercase;
}}
[data-testid="stDataFrame"] td {{
    font-size: 0.8rem !important;
    padding: 0.3rem 0.6rem !important;
    border-bottom: 1px solid {DIVIDER} !important;
    font-family: {FONT_BODY} !important;
}}
[data-testid="stDataFrame"] tbody tr:hover td {{
    background: {BG_BASE} !important;
}}

/* ═══ Buttons ═══ */
.stButton > button {{
    background: {ACCENT};
    color: {WHITE};
    border: none;
    border-radius: 5px;
    padding: 0.4rem 1rem;
    font-weight: 500;
    font-size: 0.84rem;
    transition: all 0.15s;
    font-family: {FONT_BODY} !important;
}}
.stButton > button:hover {{
    background: {ACCENT_DARK};
    box-shadow: 0 2px 8px rgba(91,122,140,0.3);
}}
.stButton > button[kind="secondary"] {{
    background: transparent;
    color: {TEXT_SOFT};
    border: 1px solid {BORDER};
}}
.stButton > button[kind="secondary"]:hover {{
    background: {BG_CARD};
    color: {TEXT_MAIN};
    border-color: {ACCENT};
    box-shadow: none;
}}

/* ═══ Inputs ═══ */
.stTextInput input, .stSelectbox > div > div {{
    border-color: {BORDER} !important;
    border-radius: 5px !important;
    font-family: {FONT_BODY} !important;
    font-size: 0.85rem !important;
}}
.stTextInput input:focus {{
    border-color: {ACCENT} !important;
    box-shadow: 0 0 0 1px {ACCENT} !important;
}}
div[data-baseweb="popover"] {{
    border-color: {BORDER} !important;
    border-radius: 6px !important;
}}
div[data-baseweb="popover"] [role="option"]:hover > div {{
    background: {BG_BASE} !important;
}}
div[data-baseweb="popover"] [aria-selected="true"] > div {{
    background: {BG_SIDEBAR} !important;
}}

/* ═══ Tabs ═══ */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0;
    border-bottom: 1px solid {DIVIDER};
}}
.stTabs [data-baseweb="tab"] {{
    color: {TEXT_MUTED};
    font-weight: 500;
    font-size: 0.82rem;
    padding: 0.4rem 0.9rem;
    border-radius: 4px 4px 0 0;
    font-family: {FONT_BODY} !important;
}}
.stTabs [aria-selected="true"] {{
    color: {TEXT_MAIN};
    background: {BG_CARD};
    border: 1px solid {DIVIDER};
    border-bottom-color: {BG_CARD};
}}

/* ═══ Divider ═══ */
hr {{
    border-color: {DIVIDER} !important;
    margin: 0.8rem 0 !important;
}}

/* ═══ Badges ═══ */
.badge-critical {{
    background: {RED_CRIT}; color: white; padding: 2px 10px;
    border-radius: 10px; font-size: 0.72rem; font-weight: 500;
    display: inline-block; letter-spacing: 0.03em;
}}
.badge-high {{
    background: {ORANGE_HI}; color: white; padding: 2px 10px;
    border-radius: 10px; font-size: 0.72rem; font-weight: 500;
    display: inline-block; letter-spacing: 0.03em;
}}
.badge-medium {{
    background: {AMBER_MED}; color: white; padding: 2px 10px;
    border-radius: 10px; font-size: 0.72rem; font-weight: 500;
    display: inline-block; letter-spacing: 0.03em;
}}
.badge-normal {{
    background: {SLATE_LO}; color: white; padding: 2px 10px;
    border-radius: 10px; font-size: 0.72rem; font-weight: 500;
    display: inline-block; letter-spacing: 0.03em;
}}

/* ═══ Info callout ═══ */
[data-testid="stInfo"] {{
    background: {BG_CARD};
    border-left: 3px solid {ACCENT};
    color: {TEXT_SOFT};
    border-radius: 4px;
}}

/* ═══ Expander ═══ */
.streamlit-expanderHeader {{
    font-family: {FONT_BODY} !important;
    color: {TEXT_SOFT} !important;
    font-size: 0.82rem !important;
}}

/* ═══ Scrollbar ═══ */
::-webkit-scrollbar {{ width: 4px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 2px; }}

/* ═══ Spinner ═══ */
.stSpinner > div {{
    border-color: {ACCENT} transparent transparent transparent !important;
}}

/* ═══ Intel card — compact info block ═══ */
.intel-card {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 0.65rem 0.9rem;
    margin-bottom: 0.4rem;
    box-shadow: none;
    transition: border-color 0.15s;
}}
.intel-card:hover {{
    border-color: {ACCENT};
}}

/* ═══ Evidence highlight ═══ */
.evidence-highlight {{
    background: #FFF3E0;
    border-left: 3px solid {ORANGE_HI};
    padding: 0.5rem 0.8rem;
    margin-bottom: 0.4rem;
    border-radius: 0 4px 4px 0;
    font-size: 0.84rem;
    color: {TEXT_MAIN};
}}

/* ═══ Risk score large ═══ */
.risk-score-critical {{
    font-family: '{FONT_MONO}', monospace;
    font-size: 2.4rem;
    font-weight: 600;
    color: {RED_CRIT};
}}
.risk-score-high {{
    font-family: '{FONT_MONO}', monospace;
    font-size: 2.4rem;
    font-weight: 600;
    color: {ORANGE_HI};
}}
.risk-score-normal {{
    font-family: '{FONT_MONO}', monospace;
    font-size: 2.4rem;
    font-weight: 600;
    color: {SLATE_LO};
}}

/* ═══ Dossier card (kept for dashboard compat) ═══ */
.dossier-card {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 0.65rem 0.9rem;
    box-shadow: none;
    transition: border-color 0.15s;
}}
.dossier-card:hover {{
    border-color: {ACCENT};
}}

/* ═══ Empty state ═══ */
.empty-state {{
    text-align: center;
    padding: 2.5rem 2rem;
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT_MUTED};
}}
.empty-state .icon {{
    font-size: 1.8rem;
    margin-bottom: 0.6rem;
    opacity: 0.45;
}}
.empty-state .title {{
    font-size: 0.9rem;
    font-weight: 500;
    color: {TEXT_SOFT};
    margin-bottom: 0.25rem;
}}
.empty-state .desc {{
    font-size: 0.8rem;
}}

/* ═══ Entity chip ═══ */
.entity-chip {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.76rem;
    font-weight: 500;
    margin-right: 4px;
    margin-bottom: 4px;
    color: white;
}}
</style>
"""


def badge(p: str) -> str:
    if p == "critical": return '<span class="badge-critical">严重</span>'
    if p == "high":     return '<span class="badge-high">高危</span>'
    if p == "medium":   return '<span class="badge-medium">中危</span>'
    return '<span class="badge-normal">普通</span>'


def empty(icon: str, title: str, desc: str) -> str:
    return f'<div class="empty-state"><div class="icon">{icon}</div><div class="title">{title}</div><div class="desc">{desc}</div></div>'


def entity_chip(etype: str, value: str) -> str:
    color = ECOLOR.get(etype, SLATE)
    return f'<span class="entity-chip" style="background:{color}">{value}</span>'


def risk_score_html(score: float) -> str:
    if score >= 0.8:
        cls = "risk-score-critical"
    elif score >= 0.65:
        cls = "risk-score-high"
    else:
        cls = "risk-score-normal"
    return f'<span class="{cls}">{score:.2f}</span>'

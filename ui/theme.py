"""Morandi color system and CSS for the BGI dashboard."""

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
WHITE      = "#FFFFFF"
BG_BASE    = "#F5F2ED"
BG_CARD    = "#FAF9F6"
BG_SIDEBAR = "#ECE8E1"
TEXT_MAIN  = "#3C3A35"
TEXT_SOFT  = "#6E6B64"
TEXT_MUTED = "#928F88"
SAGE       = "#8B9D83"
SAGE_DARK  = "#6E8266"
SLATE      = "#7D8E9E"
ROSE       = "#C2A6A3"
ROSE_DARK  = "#A88480"
BORDER     = "#D6D1C9"
DIVIDER    = "#E3DFD8"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@350;450;550;650&display=swap');

* {{ font-family: 'Inter', sans-serif; }}

/* ---- Shell ---- */
.stApp {{ background: {BG_BASE}; }}
header[data-testid="stHeader"] {{ background: {BG_BASE} !important; box-shadow: none; border-bottom: 1px solid {DIVIDER}; }}
[data-testid="stToolbar"], #MainMenu, footer, .viewerBadge_container__r5tak {{ display: none !important; }}

/* ---- Sidebar ---- */
[data-testid="stSidebar"] {{
    background: {BG_SIDEBAR};
    border-right: 1px solid {BORDER};
}}
[data-testid="stSidebar"] .stButton > button {{
    background: transparent;
    color: {TEXT_SOFT};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0.55rem 0.8rem;
    font-size: 0.88rem;
    font-weight: 450;
    text-align: left;
    width: 100%;
    transition: all 0.15s;
    box-shadow: none;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: {BG_BASE};
    color: {TEXT_MAIN};
    border-color: {BORDER};
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background: {BG_CARD};
    color: {TEXT_MAIN};
    font-weight: 550;
    border-color: {BORDER};
    box-shadow: 0 1px 3px rgba(60,58,53,0.05);
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
    background: {BG_CARD};
}}

/* ---- Metric cards ---- */
[data-testid="stMetric"] {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 1.1rem 1.4rem;
    box-shadow: 0 1px 4px rgba(60,58,53,0.03);
}}
[data-testid="stMetric"] label {{
    color: {TEXT_MUTED} !important;
    font-size: 0.78rem !important;
    font-weight: 500;
    letter-spacing: 0.04em;
}}
[data-testid="stMetricValue"] {{
    color: {TEXT_MAIN} !important;
    font-size: 1.75rem !important;
    font-weight: 600 !important;
}}

/* ---- Tables ---- */
[data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; border-radius: 8px; overflow: hidden; }}
[data-testid="stDataFrame"] th {{
    background: {BG_SIDEBAR} !important;
    color: {TEXT_SOFT} !important;
    font-weight: 500 !important;
    font-size: 0.8rem !important;
    padding: 0.5rem 0.8rem !important;
}}
[data-testid="stDataFrame"] td {{
    font-size: 0.84rem !important;
    padding: 0.45rem 0.8rem !important;
    border-bottom: 1px solid {DIVIDER} !important;
}}

/* ---- Buttons (main area only) ---- */
div[data-testid="stVerticalBlock"] .stButton > button,
div[data-testid="column"] .stButton > button {{
    background: {SAGE};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 0.5rem 1.5rem;
    font-weight: 500;
    transition: all 0.15s;
}}
div[data-testid="stVerticalBlock"] .stButton > button:hover {{
    background: {SAGE_DARK};
    box-shadow: 0 2px 8px rgba(139,157,131,0.25);
}}

/* ---- Inputs ---- */
.stTextInput input {{ border-color: {BORDER}; border-radius: 8px; }}
.stTextInput input:focus {{ border-color: {SAGE} !important; box-shadow: 0 0 0 2px rgba(139,157,131,0.15); }}
[data-testid="stSelectbox"] > div > div {{ border-color: {BORDER} !important; border-radius: 8px !important; }}

/* ---- Typography ---- */
h1 {{ color: {TEXT_MAIN} !important; font-weight: 600 !important; font-size: 1.5rem !important; }}
h2 {{ color: {TEXT_SOFT} !important; font-weight: 500 !important; font-size: 1.1rem !important; }}
h3 {{ color: {TEXT_SOFT} !important; font-weight: 500 !important; font-size: 1rem !important; }}

/* ---- Misc ---- */
hr {{ border-color: {DIVIDER} !important; }}
[data-testid="stInfo"] {{ background: {BG_CARD}; border-left: 3px solid {SLATE}; color: {TEXT_SOFT}; border-radius: 4px; }}

/* ---- Priority badges ---- */
.badge-high     {{ background: {ROSE}; color: white; padding: 2px 10px; border-radius: 12px; font-size: 0.74rem; font-weight: 500; display: inline-block; }}
.badge-critical {{ background: {ROSE_DARK}; color: white; padding: 2px 10px; border-radius: 12px; font-size: 0.74rem; font-weight: 500; display: inline-block; }}
.badge-normal   {{ background: {SAGE}; color: white; padding: 2px 10px; border-radius: 12px; font-size: 0.74rem; font-weight: 500; display: inline-block; }}

/* ---- Empty state ---- */
.empty-state {{
    text-align: center; padding: 3rem 2rem;
    background: {BG_CARD}; border: 1px dashed {BORDER}; border-radius: 12px; color: {TEXT_MUTED};
}}
.empty-state .icon {{ font-size: 2.5rem; margin-bottom: 0.8rem; }}
.empty-state .title {{ font-size: 1rem; font-weight: 500; color: {TEXT_SOFT}; margin-bottom: 0.4rem; }}

/* ---- Scrollbar ---- */
::-webkit-scrollbar {{ width: 5px; }}
::-webkit-scrollbar-track {{ background: {BG_BASE}; }}
::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 3px; }}
</style>
"""


def badge(p: str) -> str:
    if p == "critical": return '<span class="badge-critical">CRITICAL</span>'
    if p == "high":     return '<span class="badge-high">HIGH</span>'
    return '<span class="badge-normal">NORMAL</span>'


def empty(icon: str, title: str, desc: str) -> str:
    return f'<div class="empty-state"><div class="icon">{icon}</div><div class="title">{title}</div><div>{desc}</div></div>'

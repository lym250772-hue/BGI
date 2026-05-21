"""BGI Design System — Editorial Intelligence Bureau aesthetic."""

# ── Palette ──────────────────────────────────────────────────────────────────
WHITE      = "#FFFFFF"
BG_BASE    = "#F8F6F2"
BG_CARD    = "#FEFDFB"
BG_SIDEBAR = "#F0EDE7"
TEXT_MAIN  = "#1F1D19"
TEXT_SOFT  = "#5C5852"
TEXT_MUTED = "#8A857D"
SAGE       = "#7D9378"
SAGE_DARK  = "#5F765B"
SLATE      = "#6D7D8E"
ROSE       = "#BEA09D"
ROSE_DARK  = "#9E7A77"
BORDER     = "#D8D2C8"
DIVIDER    = "#E8E2D7"
GOLD       = "#B8976A"
INK        = "#1E1B18"

# ── Typography ───────────────────────────────────────────────────────────────
FONT_DISPLAY = "Noto Serif SC"
FONT_BODY    = "Work Sans"
FONT_MONO    = "JetBrains Mono"

# ── CSS ──────────────────────────────────────────────────────────────────────
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Noto+Serif+SC:wght@400;500;600;700&family=Work+Sans:wght@350;450;550&display=swap');

/* ═══ Shell ═══ */
.stApp {{
    background: {BG_BASE};
}}
.stMainBlock {{
    padding-top: 1.5rem;
}}

/* Header — keep it clean, DO NOT hide the collapse/expand controls */
header[data-testid="stHeader"] {{
    background: transparent !important;
    box-shadow: none !important;
    border-bottom: 1px solid {DIVIDER};
}}

/* Only hide decorative chrome — never hide sidebar controls */
#MainMenu, footer, .viewerBadge_container__r5tak {{
    display: none !important;
}}

/* Ensure collapsed-sidebar expand button is ALWAYS visible and clickable */
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
    box-shadow: 2px 0 8px rgba(30,27,24,0.08) !important;
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
    box-shadow: 2px 0 12px rgba(30,27,24,0.12) !important;
}}

/* Also keep the sidebar collapse button (‹) visible when sidebar is open */
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

/* Sidebar content spacing */
[data-testid="stSidebar"] .stMarkdown {{
    padding: 0 0.5rem;
}}

/* Sidebar nav — radio-based for reliability */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
    gap: 0.2rem;
}}

[data-testid="stSidebar"] .stRadio > div {{
    gap: 0.15rem;
}}

[data-testid="stSidebar"] .stRadio label {{
    padding: 0.5rem 0.75rem;
    border-radius: 6px;
    font-size: 0.85rem;
    font-weight: 450;
    color: {TEXT_SOFT};
    transition: all 0.15s;
    cursor: pointer;
}}

[data-testid="stSidebar"] .stRadio label:hover {{
    background: {BG_BASE};
    color: {TEXT_MAIN};
}}

/* Active radio pill */
[data-testid="stSidebar"] .stRadio [data-baseweb="radio"] + div {{
    /* The checked state indicator is tricky with Streamlit's radio */
}}

/* Simpler: use the container styling */
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
    background: {BG_CARD} !important;
    color: {TEXT_MAIN} !important;
    font-weight: 550 !important;
    border: 1px solid {BORDER};
    box-shadow: 0 1px 3px rgba(30,27,24,0.04);
}}

/* ═══ Typography ═══ */
h1, h2, h3, h4 {{
    font-family: '{FONT_DISPLAY}', '{FONT_BODY}', serif !important;
    letter-spacing: 0 !important;
}}
h1 {{ color: {TEXT_MAIN} !important; font-weight: 600 !important; font-size: 1.55rem !important; }}
h2 {{ color: {TEXT_MAIN} !important; font-weight: 500 !important; font-size: 1.15rem !important; }}
h3 {{ color: {TEXT_SOFT} !important; font-weight: 500 !important; font-size: 1rem !important; }}

.stCaption {{
    font-family: '{FONT_BODY}', sans-serif !important;
    color: {TEXT_MUTED} !important;
    font-size: 0.82rem !important;
}}

/* ═══ Metric cards ═══ */
[data-testid="stMetric"] {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 1rem 1.2rem;
    box-shadow: 0 1px 2px rgba(30,27,24,0.03);
    transition: all 0.2s;
}}
[data-testid="stMetric"]:hover {{
    box-shadow: 0 4px 16px rgba(30,27,24,0.05);
    border-color: {GOLD};
}}
[data-testid="stMetric"] label {{
    color: {TEXT_MUTED} !important;
    font-size: 0.7rem !important;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-family: '{FONT_BODY}', sans-serif !important;
}}
[data-testid="stMetricValue"] {{
    color: {TEXT_MAIN} !important;
    font-size: 1.75rem !important;
    font-weight: 550 !important;
    font-family: '{FONT_MONO}', monospace !important;
}}

/* ═══ Tables ═══ */
[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    overflow: hidden;
}}
[data-testid="stDataFrame"] th {{
    background: {BG_SIDEBAR} !important;
    color: {TEXT_SOFT} !important;
    font-weight: 500 !important;
    font-size: 0.76rem !important;
    padding: 0.5rem 0.75rem !important;
    font-family: '{FONT_BODY}', sans-serif !important;
    letter-spacing: 0.03em;
    text-transform: uppercase;
}}
[data-testid="stDataFrame"] td {{
    font-size: 0.83rem !important;
    padding: 0.4rem 0.75rem !important;
    border-bottom: 1px solid {DIVIDER} !important;
    font-family: '{FONT_BODY}', sans-serif !important;
}}
[data-testid="stDataFrame"] tbody tr:hover td {{
    background: {BG_BASE} !important;
}}

/* ═══ Buttons ═══ */
.stButton > button {{
    background: {INK};
    color: {WHITE};
    border: none;
    border-radius: 6px;
    padding: 0.45rem 1.2rem;
    font-weight: 500;
    font-size: 0.85rem;
    transition: all 0.15s;
    font-family: '{FONT_BODY}', sans-serif !important;
}}
.stButton > button:hover {{
    background: {SAGE_DARK};
    box-shadow: 0 4px 12px rgba(95,118,91,0.25);
}}
.stButton > button[kind="secondary"] {{
    background: transparent;
    color: {TEXT_SOFT};
    border: 1px solid {BORDER};
}}
.stButton > button[kind="secondary"]:hover {{
    background: {BG_CARD};
    color: {TEXT_MAIN};
    border-color: {GOLD};
    box-shadow: none;
}}

/* ═══ Inputs ═══ */
.stTextInput input, .stSelectbox > div > div {{
    border-color: {BORDER} !important;
    border-radius: 6px !important;
    font-family: '{FONT_BODY}', sans-serif !important;
}}
.stTextInput input:focus {{
    border-color: {INK} !important;
    box-shadow: 0 0 0 1px {INK} !important;
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
    font-size: 0.84rem;
    padding: 0.45rem 1rem;
    border-radius: 4px 4px 0 0;
    font-family: '{FONT_BODY}', sans-serif !important;
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
    margin: 1rem 0 !important;
}}

/* ═══ Badges ═══ */
.badge-high {{
    background: {ROSE}; color: white; padding: 2px 10px;
    border-radius: 10px; font-size: 0.72rem; font-weight: 500;
    display: inline-block; letter-spacing: 0.03em;
}}
.badge-critical {{
    background: {ROSE_DARK}; color: white; padding: 2px 10px;
    border-radius: 10px; font-size: 0.72rem; font-weight: 500;
    display: inline-block; letter-spacing: 0.03em;
}}
.badge-normal {{
    background: {SAGE}; color: white; padding: 2px 10px;
    border-radius: 10px; font-size: 0.72rem; font-weight: 500;
    display: inline-block; letter-spacing: 0.03em;
}}

/* ═══ Info callout ═══ */
[data-testid="stInfo"] {{
    background: {BG_CARD};
    border-left: 3px solid {INK};
    color: {TEXT_SOFT};
    border-radius: 4px;
}}

/* ═══ Expander ═══ */
.streamlit-expanderHeader {{
    font-family: '{FONT_BODY}', sans-serif !important;
    color: {TEXT_SOFT} !important;
}}

/* ═══ Scrollbar ═══ */
::-webkit-scrollbar {{ width: 4px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 2px; }}

/* ═══ Spinner ═══ */
.stSpinner > div {{
    border-color: {INK} transparent transparent transparent !important;
}}

/* ═══ Dossier card utility class ═══ */
.dossier-card {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 1rem 1.2rem;
    box-shadow: 0 1px 3px rgba(30,27,24,0.03);
    transition: box-shadow 0.2s;
}}
.dossier-card:hover {{
    box-shadow: 0 4px 16px rgba(30,27,24,0.06);
}}

/* ═══ Empty state ═══ */
.empty-state {{
    text-align: center;
    padding: 3rem 2rem;
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    color: {TEXT_MUTED};
}}
.empty-state .icon {{
    font-size: 2rem;
    margin-bottom: 0.8rem;
    opacity: 0.5;
}}
.empty-state .title {{
    font-family: '{FONT_DISPLAY}', serif !important;
    font-size: 0.95rem;
    font-weight: 500;
    color: {TEXT_SOFT};
    margin-bottom: 0.3rem;
}}
.empty-state .desc {{
    font-size: 0.82rem;
}}
</style>
"""


def badge(p: str) -> str:
    if p == "critical": return '<span class="badge-critical">CRITICAL</span>'
    if p == "high":     return '<span class="badge-high">HIGH</span>'
    return '<span class="badge-normal">NORMAL</span>'


def empty(icon: str, title: str, desc: str) -> str:
    return f'<div class="empty-state"><div class="icon">{icon}</div><div class="title">{title}</div><div class="desc">{desc}</div></div>'

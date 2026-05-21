"""BGI Design System — Editorial Intelligence Bureau aesthetic.

Follows frontend-design skill workflow:
  Frame → Visual System → Compose with intention → Meaningful motion
  Direction: "Editorial" — classified intelligence dossier, institutional warmth.
"""

# ── Palette ──────────────────────────────────────────────────────────────────
WHITE      = "#FFFFFF"
BG_BASE    = "#F4F0EA"
BG_CARD    = "#FBF9F5"
BG_SIDEBAR = "#EDE8E0"
TEXT_MAIN  = "#2D2A25"
TEXT_SOFT  = "#5C5852"
TEXT_MUTED = "#8A857D"
SAGE       = "#7D9378"
SAGE_DARK  = "#5F765B"
SLATE      = "#6D7D8E"
ROSE       = "#BEA09D"
ROSE_DARK  = "#9E7A77"
BORDER     = "#D5CFC5"
DIVIDER    = "#E4DDD3"
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

* {{ font-family: '{FONT_BODY}', system-ui, sans-serif; }}

/* ═══ Entrance animation ═══ */
@keyframes fade-up {{
    from {{ opacity: 0; transform: translateY(12px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes fade-in {{
    from {{ opacity: 0; }}
    to   {{ opacity: 1; }}
}}
.stMain > div > div > div > div {{
    animation: fade-up 0.55s cubic-bezier(0.22, 0.61, 0.36, 1);
}}

/* ═══ Shell ═══ */
.stApp {{
    background: {BG_BASE};
    background-image:
        url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
}}
header[data-testid="stHeader"] {{ background: transparent !important; box-shadow: none !important; border-bottom: 1px solid {DIVIDER}; }}
[data-testid="stToolbar"], #MainMenu, footer, .viewerBadge_container__r5tak {{ display: none !important; }}

/* ═══ Sidebar ═══ */
[data-testid="stSidebar"] {{
    background: {BG_SIDEBAR};
    background-image:
        url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
    border-right: 1px solid {BORDER};
}}

[data-testid="stSidebar"] .stButton > button {{
    background: transparent; color: {TEXT_SOFT}; border: none;
    border-radius: 6px; padding: 0.5rem 0.75rem; font-size: 0.85rem;
    font-weight: 450; text-align: left; width: 100%;
    transition: all 0.2s cubic-bezier(0.4,0,0.2,1); box-shadow: none;
    display: flex; align-items: center; gap: 0.5rem;
    font-family: '{FONT_BODY}', sans-serif;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: {BG_BASE}; color: {TEXT_MAIN};
    transform: translateX(3px);
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background: {BG_CARD}; color: {TEXT_MAIN}; font-weight: 550;
    border-left: 3px solid {SAGE};
    box-shadow: 0 1px 3px rgba(45,42,37,0.04);
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
    background: {BG_CARD}; transform: none;
}}

/* ═══ Editorial headings ═══ */
h1, h2, h3, h4 {{
    font-family: '{FONT_DISPLAY}', '{FONT_BODY}', serif !important;
    letter-spacing: 0 !important;
}}
h1 {{ color: {TEXT_MAIN} !important; font-weight: 600 !important; font-size: 1.55rem !important; }}
h2 {{ color: {TEXT_MAIN} !important; font-weight: 500 !important; font-size: 1.15rem !important; }}
h3 {{ color: {TEXT_SOFT} !important; font-weight: 500 !important; font-size: 1rem !important; }}
.stCaption {{ font-family: '{FONT_BODY}', sans-serif !important; color: {TEXT_MUTED} !important; font-size: 0.82rem !important; }}

/* ═══ Metric cards — elevated for key intel ═══ */
[data-testid="stMetric"] {{
    background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 1.1rem 1.3rem;
    box-shadow: 0 1px 2px rgba(45,42,37,0.03);
    transition: all 0.25s cubic-bezier(0.4,0,0.2,1);
}}
[data-testid="stMetric"]:hover {{
    box-shadow: 0 6px 20px rgba(45,42,37,0.06);
    transform: translateY(-2px);
    border-color: {GOLD};
}}
[data-testid="stMetric"] label {{
    color: {TEXT_MUTED} !important;
    font-size: 0.72rem !important; font-weight: 500;
    letter-spacing: 0.06em; text-transform: uppercase;
    font-family: '{FONT_BODY}', sans-serif !important;
}}
[data-testid="stMetricValue"] {{
    color: {TEXT_MAIN} !important;
    font-size: 1.8rem !important; font-weight: 550 !important;
    font-family: '{FONT_MONO}', monospace !important;
    letter-spacing: -0.02em;
}}

/* Critical metric — rose accent */
.critical-metric [data-testid="stMetric"] {{ border-left: 3px solid {ROSE}; }}

/* ═══ Asymmetric dossier card ═══ */
.dossier-card {{
    background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 1.2rem 1.4rem; position: relative; overflow: hidden;
    box-shadow: 0 1px 3px rgba(45,42,37,0.03);
    transition: box-shadow 0.25s;
}}
.dossier-card:hover {{ box-shadow: 0 6px 18px rgba(45,42,37,0.05); }}
.dossier-card::before {{
    content: ''; position: absolute; top: 0; left: 0;
    width: 100%; height: 2px;
    background: linear-gradient(90deg, {GOLD}, transparent);
    opacity: 0; transition: opacity 0.3s;
}}
.dossier-card:hover::before {{ opacity: 1; }}

/* ═══ Horizontal rule — gold accent ═══ */
hr {{ border: none; border-top: 1px solid {DIVIDER}; margin: 1.2rem 0; }}
.hr-accent {{ border: none; height: 1px; background: linear-gradient(90deg, {GOLD}, transparent); margin: 1rem 0; }}

/* ═══ Tables ═══ */
[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER}; border-radius: 6px; overflow: hidden;
}}
[data-testid="stDataFrame"] th {{
    background: {BG_SIDEBAR} !important; color: {TEXT_SOFT} !important;
    font-weight: 500 !important; font-size: 0.78rem !important;
    padding: 0.5rem 0.75rem !important;
    font-family: '{FONT_BODY}', sans-serif !important;
    letter-spacing: 0.03em; text-transform: uppercase;
}}
[data-testid="stDataFrame"] td {{
    font-size: 0.83rem !important; padding: 0.4rem 0.75rem !important;
    border-bottom: 1px solid {DIVIDER} !important;
    font-family: '{FONT_BODY}', sans-serif !important;
}}
[data-testid="stDataFrame"] tbody tr:hover td {{
    background: {BG_BASE} !important;
    transition: background 0.15s;
}}

/* ═══ Buttons ═══ */
div[data-testid="stVerticalBlock"] .stButton > button,
div[data-testid="column"] .stButton > button {{
    background: {INK}; color: {WHITE}; border: none; border-radius: 6px;
    padding: 0.5rem 1.4rem; font-weight: 500; font-size: 0.85rem;
    transition: all 0.2s;
    font-family: '{FONT_BODY}', sans-serif !important;
}}
div[data-testid="stVerticalBlock"] .stButton > button:hover {{
    background: {SAGE_DARK};
    box-shadow: 0 4px 14px rgba(95,118,91,0.3);
    transform: translateY(-1px);
}}

/* ═══ Inputs ═══ */
.stTextInput input, .stSelectbox > div > div {{
    border-color: {BORDER} !important; border-radius: 6px !important;
    font-family: '{FONT_BODY}', sans-serif !important;
}}
.stTextInput input:focus {{
    border-color: {INK} !important;
    box-shadow: 0 0 0 1px {INK} !important;
}}
div[data-baseweb="popover"] {{
    border-color: {BORDER} !important; border-radius: 6px !important;
}}
div[data-baseweb="popover"] [role="option"]:hover > div {{
    background: {BG_BASE} !important;
}}
div[data-baseweb="popover"] [aria-selected="true"] > div {{
    background: {BG_SIDEBAR} !important;
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

/* ═══ Empty state ═══ */
.empty-state {{
    text-align: center; padding: 2.5rem 2rem;
    background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 6px;
    color: {TEXT_MUTED};
}}
.empty-state .icon {{ font-size: 2rem; margin-bottom: 0.8rem; opacity: 0.6; }}
.empty-state .title {{
    font-family: '{FONT_DISPLAY}', serif !important;
    font-size: 0.95rem; font-weight: 500; color: {TEXT_SOFT}; margin-bottom: 0.3rem;
}}
.empty-state .desc {{
    font-size: 0.82rem;
}}

/* ═══ Info / callout ═══ */
[data-testid="stInfo"] {{
    background: {BG_CARD}; border-left: 2px solid {INK};
    color: {TEXT_SOFT}; border-radius: 4px;
}}

/* ═══ Tabs ═══ */
.stTabs [data-baseweb="tab-list"] {{ gap: 0; border-bottom: 1px solid {DIVIDER}; }}
.stTabs [data-baseweb="tab"] {{
    color: {TEXT_MUTED}; font-weight: 500; font-size: 0.84rem;
    padding: 0.45rem 1rem; border-radius: 4px 4px 0 0;
    font-family: '{FONT_BODY}', sans-serif !important;
}}
.stTabs [aria-selected="true"] {{
    color: {TEXT_MAIN}; background: {BG_CARD};
    border: 1px solid {DIVIDER}; border-bottom-color: {BG_CARD};
}}

/* ═══ Scrollbar ═══ */
::-webkit-scrollbar {{ width: 4px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 2px; }}

/* ═══ Selectbox ═══ */
[data-testid="stSelectbox"] {{ font-family: '{FONT_BODY}', sans-serif !important; }}

/* ═══ Spinner ═══ */
.stSpinner > div {{ border-color: {INK} transparent transparent transparent !important; }}
</style>
"""


def badge(p: str) -> str:
    if p == "critical": return '<span class="badge-critical">CRITICAL</span>'
    if p == "high":     return '<span class="badge-high">HIGH</span>'
    return '<span class="badge-normal">NORMAL</span>'


def empty(icon: str, title: str, desc: str) -> str:
    return f'<div class="empty-state"><div class="icon">{icon}</div><div class="title">{title}</div><div class="desc">{desc}</div></div>'


def dossier(title: str, body: str) -> str:
    """A distinguished card with gold top-bar reveal on hover."""
    return f'<div class="dossier-card"><div style="font-family:\'{FONT_DISPLAY}\',serif;font-size:0.9rem;font-weight:500;color:{TEXT_MAIN};margin-bottom:0.5rem">{title}</div><div style="font-size:0.82rem;color:{TEXT_SOFT}">{body}</div></div>'


def hr_accent() -> str:
    return f'<div class="hr-accent"></div>'

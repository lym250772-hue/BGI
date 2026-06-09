"""Streamlit design system for the BGI analyst console."""

BG = "#F4F6F8"
PANEL = "#FFFFFF"
INK = "#18202A"
TEXT = "#263442"
MUTED = "#6F7F8F"
LINE = "#D8E0E8"
SOFT = "#EEF2F5"
ACCENT = "#176B87"
ACCENT_DARK = "#0E4E63"
GREEN = "#26735D"
AMBER = "#B88418"
RED = "#B83A3A"
BLUE = "#365C8D"
PURPLE = "#6A5C8D"

RISK_COLORS = {
    "critical": RED,
    "high": "#D06A2A",
    "medium": AMBER,
    "normal": BLUE,
    "low": GREEN,
}

STATUS_COLORS = {
    "RAW_COLLECTED": AMBER,
    "CLEANED": BLUE,
    "ANALYZING": PURPLE,
    "ANALYZED": GREEN,
    "FAILED": RED,
    "DISCARDED": MUTED,
    "pending": AMBER,
    "running": PURPLE,
    "success": GREEN,
    "failed": RED,
}


def badge(text: str, color: str = ACCENT) -> str:
    return (
        f"<span class='bagi-badge' style='--badge-color:{color}'>{text}</span>"
    )


def status_dot(ok: bool, label: str) -> str:
    color = GREEN if ok else RED
    return (
        f"<span class='status-pill' style='--status-color:{color}'>"
        f"<span></span>{label}</span>"
    )


CSS = f"""
<style>
:root {{
  --bagi-bg: {BG};
  --bagi-panel: {PANEL};
  --bagi-ink: {INK};
  --bagi-text: {TEXT};
  --bagi-muted: {MUTED};
  --bagi-line: {LINE};
  --bagi-soft: {SOFT};
  --bagi-accent: {ACCENT};
  --bagi-accent-dark: {ACCENT_DARK};
}}

.stApp {{
  background:
    linear-gradient(90deg, rgba(24,32,42,0.025) 1px, transparent 1px) 0 0 / 28px 28px,
    linear-gradient(0deg, rgba(24,32,42,0.018) 1px, transparent 1px) 0 0 / 28px 28px,
    var(--bagi-bg);
  color: var(--bagi-text);
}}

header[data-testid="stHeader"] {{
  background: rgba(244,246,248,0.92) !important;
  border-bottom: 1px solid var(--bagi-line);
}}

#MainMenu,
footer,
.viewerBadge_container__r5tak,
.stDeployButton,
[data-testid="stDeployButton"],
[data-testid="stAppDeployButton"],
[data-testid="stStatusWidget"],
[data-testid="stDecoration"] {{
  display: none !important;
  visibility: hidden !important;
  height: 0 !important;
}}

[data-testid="stToolbar"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
button[title="Open sidebar"],
button[title="Close sidebar"],
button[aria-label="Open sidebar"],
button[aria-label="Close sidebar"] {{
  display: flex !important;
  visibility: visible !important;
  opacity: 1 !important;
}}

[data-testid="stSidebarCollapsedControl"] {{
  position: fixed !important;
  left: 0.72rem !important;
  top: 0.72rem !important;
  z-index: 9999 !important;
}}

[data-testid="stSidebar"] {{
  background: #121820;
  border-right: 1px solid #25313E;
}}

[data-testid="stSidebar"] * {{
  color: #D7E0E8;
}}

[data-testid="stSidebar"] .stRadio label {{
  border-radius: 6px;
  padding: 0.52rem 0.72rem;
  color: #B9C4CE !important;
  font-size: 0.88rem;
}}

[data-testid="stSidebar"] .stRadio label:hover {{
  background: #1B2530;
  color: #FFFFFF !important;
}}

[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: #E6EEF4 !important;
  border: 1px solid #B9CAD8;
}}

[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) * {{
  color: #111820 !important;
  font-weight: 650 !important;
}}

.sidebar-footer {{
  position: fixed !important;
  left: 1rem !important;
  right: auto !important;
  top: auto !important;
  bottom: 0.45rem !important;
  width: 15.2rem !important;
  max-width: 15.2rem !important;
  z-index: 20;
  pointer-events: none;
}}

.block-container {{
  padding-top: 1.2rem !important;
  max-width: 1500px;
}}

h1, h2, h3, h4, p, div, span, label {{
  letter-spacing: 0 !important;
}}

h1 {{
  font-size: 1.55rem !important;
  font-weight: 760 !important;
  color: var(--bagi-ink) !important;
  margin-bottom: 0.2rem !important;
}}

h2 {{
  font-size: 1.15rem !important;
  font-weight: 700 !important;
  color: var(--bagi-ink) !important;
}}

h3 {{
  font-size: 0.98rem !important;
  font-weight: 700 !important;
  color: var(--bagi-text) !important;
}}

.page-kicker {{
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 9px;
  border: 1px solid var(--bagi-line);
  border-radius: 999px;
  background: rgba(255,255,255,0.72);
  color: var(--bagi-muted);
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
}}

.bagi-panel {{
  background: var(--bagi-panel);
  border: 1px solid var(--bagi-line);
  border-radius: 8px;
  padding: 1rem;
  box-shadow: 0 8px 28px rgba(24,32,42,0.045);
}}

.bagi-panel-tight {{
  background: var(--bagi-panel);
  border: 1px solid var(--bagi-line);
  border-radius: 8px;
  padding: 0.75rem 0.85rem;
}}

.section-title {{
  color: var(--bagi-ink);
  font-size: 0.9rem;
  font-weight: 760;
  margin-bottom: 0.45rem;
}}

.section-note {{
  color: var(--bagi-muted);
  font-size: 0.78rem;
  line-height: 1.55;
}}

.bagi-badge {{
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 2px 8px;
  border: 1px solid color-mix(in srgb, var(--badge-color), white 62%);
  border-radius: 999px;
  background: color-mix(in srgb, var(--badge-color), white 88%);
  color: var(--badge-color);
  font-size: 0.72rem;
  font-weight: 720;
  white-space: nowrap;
}}

.status-pill {{
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 24px;
  padding: 2px 9px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--status-color), white 90%);
  color: var(--status-color);
  font-size: 0.75rem;
  font-weight: 760;
}}

.status-pill span {{
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--status-color);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--status-color), white 78%);
}}

.intel-card {{
  border-left: 3px solid var(--bagi-accent);
  padding: 0.72rem 0.82rem;
  background: #FFFFFF;
  border-radius: 0 8px 8px 0;
  border-top: 1px solid var(--bagi-line);
  border-right: 1px solid var(--bagi-line);
  border-bottom: 1px solid var(--bagi-line);
}}

.mono {{
  font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
}}

[data-testid="stMetric"] {{
  background: var(--bagi-panel);
  border: 1px solid var(--bagi-line);
  border-radius: 8px;
  padding: 0.78rem 0.9rem;
}}

[data-testid="stMetric"] label {{
  color: var(--bagi-muted) !important;
  font-size: 0.72rem !important;
  font-weight: 720;
}}

[data-testid="stMetricValue"] {{
  color: var(--bagi-ink) !important;
  font-size: 1.45rem !important;
  font-weight: 780 !important;
}}

.stButton > button {{
  border-radius: 6px !important;
  border: 1px solid var(--bagi-accent) !important;
  background: var(--bagi-accent) !important;
  color: white !important;
  min-height: 36px;
  font-weight: 720 !important;
}}

.stButton > button:hover {{
  background: var(--bagi-accent-dark) !important;
  border-color: var(--bagi-accent-dark) !important;
}}

.stButton > button[kind="secondary"] {{
  background: #FFFFFF !important;
  color: var(--bagi-text) !important;
  border-color: var(--bagi-line) !important;
}}

.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {{
  border-radius: 6px !important;
}}

[data-testid="stDataFrame"] {{
  border: 1px solid var(--bagi-line);
  border-radius: 8px;
  overflow: hidden;
}}

.stTabs [data-baseweb="tab-list"] {{
  gap: 4px;
  border-bottom: 1px solid var(--bagi-line);
}}

.stTabs [data-baseweb="tab"] {{
  border-radius: 6px 6px 0 0;
  color: var(--bagi-muted);
  font-weight: 720;
}}

.stTabs [aria-selected="true"] {{
  background: white;
  color: var(--bagi-ink) !important;
}}

/*
  Streamlit 的侧边栏展开按钮挂在顶部工具栏附近。
  不能隐藏整个 stToolbar，否则侧边栏收起后就没有入口再展开。
  这里只隐藏部署入口，保留侧边栏折叠/展开控件。
*/
div[data-testid="stAppDeployButton"],
div[data-testid="stAppDeployButton"] * {{
  display: none !important;
  visibility: hidden !important;
  opacity: 0 !important;
  width: 0 !important;
  min-width: 0 !important;
  height: 0 !important;
  min-height: 0 !important;
  padding: 0 !important;
  margin: 0 !important;
  pointer-events: none !important;
}}
</style>
"""

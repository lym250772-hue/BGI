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
    "SCREENED": AMBER,
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

/* ── Page background ───────────────────────────────────────────────────── */

.stApp {{
  background: var(--bagi-bg);
  color: var(--bagi-text);
}}

header[data-testid="stHeader"] {{
  background: rgba(244,246,248,0.96) !important;
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--bagi-line);
}}

/* ── Hide Streamlit chrome ─────────────────────────────────────────────── */

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

/* ── Sidebar ───────────────────────────────────────────────────────────── */

[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #0F1923 0%, #131E2A 100%);
  border-right: 1px solid #1D2A38;
}}

[data-testid="stSidebar"] * {{
  color: #C8D4E0;
}}

[data-testid="stSidebar"] .stRadio label {{
  border-radius: 8px;
  padding: 0.56rem 0.8rem;
  color: #8899AE !important;
  font-size: 0.88rem;
  font-weight: 500;
  transition: all 0.15s ease;
}}

[data-testid="stSidebar"] .stRadio label:hover {{
  background: rgba(23,107,135,0.09);
  color: #DFE8F2 !important;
}}

[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: #FFFFFF !important;
  border: 1px solid #C4D2E0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}}

[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) * {{
  color: #0F1923 !important;
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

/* ── Main content area ─────────────────────────────────────────────────── */

.block-container {{
  padding-top: 1.2rem !important;
  max-width: 1520px;
}}

/* ── Typography ────────────────────────────────────────────────────────── */

h1, h2, h3, h4, p, div, span, label {{
  letter-spacing: 0 !important;
}}

h1 {{
  font-size: 1.55rem !important;
  font-weight: 760 !important;
  color: var(--bagi-ink) !important;
  margin-bottom: 0.15rem !important;
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
  height: 26px;
  padding: 0 10px;
  border: 1px solid rgba(23,107,135,0.22);
  border-radius: 999px;
  background: rgba(23,107,135,0.06);
  color: {ACCENT};
  font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}}

/* ── Panels & cards ────────────────────────────────────────────────────── */

.bagi-panel {{
  background: var(--bagi-panel);
  border: 1px solid var(--bagi-line);
  border-radius: 10px;
  padding: 1.1rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.03);
}}

.bagi-panel-tight {{
  background: var(--bagi-panel);
  border: 1px solid var(--bagi-line);
  border-radius: 10px;
  padding: 0.78rem 0.9rem;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
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

/* ── Badges ────────────────────────────────────────────────────────────── */

.bagi-badge {{
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 10px;
  border: 1px solid color-mix(in srgb, var(--badge-color), white 58%);
  border-radius: 999px;
  background: color-mix(in srgb, var(--badge-color), white 86%);
  color: var(--badge-color);
  font-size: 0.72rem;
  font-weight: 720;
  white-space: nowrap;
  box-shadow: 0 0 0 1px rgba(255,255,255,0.5);
}}

.status-pill {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 26px;
  padding: 2px 12px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--status-color), white 88%);
  border: 1px solid color-mix(in srgb, var(--status-color), white 68%);
  color: var(--status-color);
  font-size: 0.75rem;
  font-weight: 760;
}}

.status-pill span {{
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--status-color);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--status-color), white 74%);
}}

/* ── Intel card ────────────────────────────────────────────────────────── */

.intel-card {{
  border-left: 4px solid var(--bagi-accent);
  padding: 0.78rem 0.9rem;
  background: var(--bagi-panel);
  border-radius: 0 10px 10px 0;
  border-top: 1px solid var(--bagi-line);
  border-right: 1px solid var(--bagi-line);
  border-bottom: 1px solid var(--bagi-line);
  box-shadow: 0 2px 8px rgba(0,0,0,0.035);
}}

/* ── Monospace ─────────────────────────────────────────────────────────── */

.mono {{
  font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", Consolas, monospace;
}}

/* ── Metrics ───────────────────────────────────────────────────────────── */

[data-testid="stMetric"] {{
  background: var(--bagi-panel);
  border: 1px solid var(--bagi-line);
  border-radius: 10px;
  padding: 0.85rem 0.95rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}}

[data-testid="stMetric"]:hover {{
  border-color: rgba(23,107,135,0.2);
  box-shadow: 0 2px 8px rgba(23,107,135,0.06);
}}

[data-testid="stMetric"] label {{
  color: var(--bagi-muted) !important;
  font-size: 0.7rem !important;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}}

[data-testid="stMetricValue"] {{
  color: var(--bagi-ink) !important;
  font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
  font-size: 1.55rem !important;
  font-weight: 700 !important;
}}

/* ── Buttons ───────────────────────────────────────────────────────────── */

.stButton > button {{
  border-radius: 8px !important;
  border: 1px solid var(--bagi-accent) !important;
  background: var(--bagi-accent) !important;
  color: #FFFFFF !important;
  min-height: 38px;
  font-weight: 700 !important;
  font-size: 0.85rem;
  transition: all 0.18s ease;
  box-shadow: 0 1px 2px rgba(23,107,135,0.18);
}}

.stButton > button:hover {{
  background: {ACCENT_DARK} !important;
  border-color: {ACCENT_DARK} !important;
  box-shadow: 0 4px 14px rgba(23,107,135,0.22);
}}

.stButton > button[kind="secondary"] {{
  background: var(--bagi-panel) !important;
  color: var(--bagi-text) !important;
  border-color: var(--bagi-line) !important;
  box-shadow: none;
}}

.stButton > button[kind="secondary"]:hover {{
  background: {SOFT} !important;
  border-color: #C0CDD8 !important;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}}

.stButton > button:disabled {{
  opacity: 0.45;
  box-shadow: none;
}}

/* ── Inputs ────────────────────────────────────────────────────────────── */

.stTextInput input,
.stTextArea textarea,
.stSelectbox div[data-baseweb="select"] {{
  border-radius: 8px !important;
  border-color: var(--bagi-line) !important;
}}

.stTextInput input:focus,
.stTextArea textarea:focus {{
  border-color: var(--bagi-accent) !important;
  box-shadow: 0 0 0 3px rgba(23,107,135,0.1) !important;
}}

/* ── DataFrames ────────────────────────────────────────────────────────── */

[data-testid="stDataFrame"] {{
  border: 1px solid var(--bagi-line);
  border-radius: 10px;
  overflow: hidden;
}}

/* ── Tabs ──────────────────────────────────────────────────────────────── */

.stTabs [data-baseweb="tab-list"] {{
  gap: 4px;
  border-bottom: 1px solid var(--bagi-line);
}}

.stTabs [data-baseweb="tab"] {{
  border-radius: 8px 8px 0 0;
  color: var(--bagi-muted);
  font-weight: 700;
  font-size: 0.85rem;
}}

.stTabs [aria-selected="true"] {{
  background: var(--bagi-panel);
  color: var(--bagi-accent) !important;
}}

/* ── Expander ──────────────────────────────────────────────────────────── */

[data-testid="stExpander"] {{
  border: 1px solid var(--bagi-line) !important;
  border-radius: 10px !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}}

/* ── Dividers ──────────────────────────────────────────────────────────── */

hr {{
  border-color: var(--bagi-line) !important;
  margin: 1.2rem 0 !important;
}}

/* ── Number input ──────────────────────────────────────────────────────── */

[data-testid="stNumberInput"] button {{
  border-color: var(--bagi-line) !important;
  color: var(--bagi-text) !important;
  border-radius: 6px !important;
}}

/* ── Deploy button (hide) ──────────────────────────────────────────────── */

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

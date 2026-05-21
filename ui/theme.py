"""Morandi color scheme and CSS theme for the BGI dashboard."""

MORANDI = {
    "bg_primary": "#F5F1EC",
    "bg_card": "#FDFBF9",
    "bg_sidebar": "#EBE6DE",
    "text_primary": "#3D3929",
    "text_secondary": "#6B6760",
    "text_muted": "#8E8A83",
    "accent_sage": "#8B9D83",
    "accent_blue": "#7E8FA6",
    "accent_rose": "#C4A8A3",
    "border": "#D8D3CB",
    "divider": "#E5E0D9",
    "white": "#FFFFFF",
    "highlight_high": "#C4A8A3",
    "highlight_critical": "#B87A6E",
    "highlight_normal": "#8B9D83",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #3D3929;
}

/* ---- Remove white header bar ---- */
header[data-testid="stHeader"] {
    background: #F5F1EC !important;
    box-shadow: none !important;
    border-bottom: 1px solid #E5E0D9;
}
[data-testid="stToolbar"] { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
.viewerBadge_container__r5tak { display: none; }

/* ---- Main background ---- */
.stApp { background-color: #F5F1EC; }

/* ---- Sidebar ---- */
[data-testid="stSidebar"] {
    background-color: #EBE6DE;
    border-right: 1px solid #D8D3CB;
}

/* ---- Sidebar nav buttons — styled as clean nav items ---- */
[data-testid="stSidebar"] .stButton {
    margin-bottom: 2px;
}
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    color: #6B6760 !important;
    border: 1px solid transparent !important;
    border-radius: 8px !important;
    padding: 0.65rem 0.9rem !important;
    font-size: 0.88rem !important;
    font-weight: 450 !important;
    text-align: left !important;
    display: flex !important;
    align-items: center !important;
    gap: 0.6rem !important;
    width: 100% !important;
    transition: all 0.18s ease !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #F5F1EC !important;
    color: #3D3929 !important;
    border-color: #D8D3CB !important;
}
/* Active nav button */
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: #FDFBF9 !important;
    color: #3D3929 !important;
    font-weight: 550 !important;
    border-color: #D8D3CB !important;
    box-shadow: 0 1px 4px rgba(61, 57, 41, 0.06) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
    background: #FDFBF9 !important;
}

/* ---- Sidebar brand area ---- */
.sidebar-brand {
    padding: 0.4rem 0 0.8rem 0;
    display: flex;
    align-items: center;
    gap: 10px;
}
.sidebar-brand .brand-icon {
    width: 34px; height: 34px;
    background: #8B9D83; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    color: white; font-weight: 700; font-size: 1rem;
}

/* ---- Sidebar footer (version + time, bottom-left) ---- */
.sidebar-footer {
    margin-top: 1.5rem;
    padding: 0.8rem 0.2rem;
    border-top: 1px solid #D8D3CB;
    font-size: 0.72rem;
    color: #8E8A83;
}

/* ---- Cards (metric containers) ---- */
[data-testid="stMetric"] {
    background: #FDFBF9;
    border: 1px solid #D8D3CB;
    border-radius: 10px;
    padding: 1.2rem 1.5rem;
    box-shadow: 0 2px 8px rgba(61, 57, 41, 0.04);
    transition: box-shadow 0.2s;
}
[data-testid="stMetric"]:hover {
    box-shadow: 0 4px 16px rgba(61, 57, 41, 0.08);
}
[data-testid="stMetric"] label {
    color: #8E8A83 !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
[data-testid="stMetricValue"] {
    color: #3D3929 !important;
    font-size: 1.8rem !important;
    font-weight: 600 !important;
}

/* ---- DataFrames ---- */
[data-testid="stDataFrame"] {
    border: 1px solid #D8D3CB;
    border-radius: 8px;
    overflow: hidden;
}
[data-testid="stDataFrame"] th {
    background-color: #EBE6DE !important;
    color: #6B6760 !important;
    font-weight: 500 !important;
    font-size: 0.82rem !important;
    padding: 0.6rem 0.8rem !important;
}
[data-testid="stDataFrame"] td {
    font-size: 0.85rem !important;
    padding: 0.5rem 0.8rem !important;
    border-bottom: 1px solid #E5E0D9 !important;
}

/* ---- General buttons ---- */
div[data-testid="column"] .stButton > button,
div[data-testid="stVerticalBlock"] .stButton > button {
    background-color: #8B9D83 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 0.5rem 1.5rem !important;
    font-weight: 500 !important;
}
div[data-testid="column"] .stButton > button:hover {
    background-color: #7A8C72 !important;
    box-shadow: 0 2px 8px rgba(139, 157, 131, 0.3);
}

/* ---- Inputs ---- */
.stTextInput input {
    border-color: #D8D3CB !important;
    border-radius: 8px !important;
}
.stTextInput input:focus {
    border-color: #8B9D83 !important;
    box-shadow: 0 0 0 2px rgba(139, 157, 131, 0.2) !important;
}

/* ---- Tabs ---- */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 2px solid #E5E0D9;
}
.stTabs [data-baseweb="tab"] {
    color: #8E8A83;
    font-weight: 500;
    padding: 0.5rem 1.2rem;
    border-radius: 8px 8px 0 0;
}
.stTabs [aria-selected="true"] {
    color: #6B6760;
    background-color: #FDFBF9;
    border: 1px solid #E5E0D9;
    border-bottom-color: #FDFBF9;
}

/* ---- Headers ---- */
h1 { color: #3D3929 !important; font-weight: 600 !important; font-size: 1.6rem !important; letter-spacing: -0.02em; }
h2 { color: #6B6760 !important; font-weight: 500 !important; font-size: 1.15rem !important; }
h3 { color: #6B6760 !important; font-weight: 500 !important; font-size: 1rem !important; }

/* ---- Info boxes ---- */
[data-testid="stInfo"] {
    background-color: #FDFBF9;
    border-left: 3px solid #7E8FA6;
    color: #6B6760;
    border-radius: 4px;
}

hr { border-color: #E5E0D9 !important; }

/* ---- Priority badges ---- */
.priority-high     { background: #C4A8A3; color: white; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 500; }
.priority-critical { background: #B87A6E; color: white; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 500; }
.priority-normal   { background: #8B9D83; color: white; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 500; }

/* ---- Empty state ---- */
.empty-state {
    text-align: center;
    padding: 3rem 2rem;
    background: #FDFBF9;
    border: 1px dashed #D8D3CB;
    border-radius: 12px;
    color: #8E8A83;
}
.empty-state .icon { font-size: 2.5rem; margin-bottom: 1rem; }
.empty-state .title { font-size: 1.05rem; font-weight: 500; color: #6B6760; margin-bottom: 0.5rem; }

/* ---- Scrollbar ---- */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #F5F1EC; }
::-webkit-scrollbar-thumb { background: #D8D3CB; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #B8B3AB; }
</style>
"""

NAV_ITEMS = [
    {"id": "dashboard",    "icon": u"\U0001F4CA", "label": "仪表盘"},
    {"id": "intel_list",   "icon": u"\U0001F4CB", "label": "情报列表"},
    {"id": "entities",     "icon": u"\U0001F517", "label": "实体库"},
    {"id": "graph",        "icon": u"\U0001F578", "label": "知识图谱"},
    {"id": "cheat_scripts","icon": u"\U0001F4DD", "label": "作弊剧本"},
    {"id": "slang_dict",   "icon": u"\U0001F4D6", "label": "黑话词典"},
]


def inject_theme():
    import streamlit as st
    st.markdown(CSS, unsafe_allow_html=True)


def render_sidebar():
    """Render Morandi sidebar with styled button navigation. No JS hacks."""
    import streamlit as st
    from datetime import datetime

    # Brand logo
    st.sidebar.markdown(
        """<div class="sidebar-brand">
        <div class="brand-icon">B</div>
        <div>
        <div style="font-weight:600;color:#3D3929;font-size:1rem;line-height:1.2">BGI</div>
        <div style="font-size:0.68rem;color:#8E8A83;line-height:1.2">Intel Analysis</div>
        </div></div>""",
        unsafe_allow_html=True,
    )

    st.sidebar.markdown('<div style="height:0.6rem"></div>', unsafe_allow_html=True)

    # Nav buttons — native Streamlit, no JS
    active = st.session_state.get("nav_page", "dashboard")
    for item in NAV_ITEMS:
        is_active = active == item["id"]
        btn_type = "primary" if is_active else "secondary"
        if st.sidebar.button(
            f"  {item['icon']}  {item['label']}",
            key=f"navbtn_{item['id']}",
            type=btn_type,
            use_container_width=True,
        ):
            st.session_state.nav_page = item["id"]
            st.rerun()

    # Version footer
    st.sidebar.markdown(
        f"""<div class="sidebar-footer">
        BGI v0.2 · {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>""",
        unsafe_allow_html=True,
    )

    return active


def priority_badge(priority: str) -> str:
    if priority == "critical":
        return '<span class="priority-critical">CRITICAL</span>'
    if priority == "high":
        return '<span class="priority-high">HIGH</span>'
    return '<span class="priority-normal">NORMAL</span>'


def empty_state(icon: str, title: str, description: str) -> str:
    return f"""<div class="empty-state">
        <div class="icon">{icon}</div>
        <div class="title">{title}</div>
        <div>{description}</div>
    </div>"""

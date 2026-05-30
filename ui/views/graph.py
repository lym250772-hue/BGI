"""Relationship Expansion — entity-centric 1-2 hop graph investigation tool."""

import os
import tempfile
import streamlit as st
from pathlib import Path

import ui.theme as T

ENTITY_TYPES = [
    "wechat", "qq", "telegram", "phone", "url", "domain",
    "ip", "tool", "bank_card", "alipay", "slang", "crypto_wallet",
]


def _check_neo4j():
    try:
        from storage.neo4j_store import neo4j
        with neo4j.driver.session() as s:
            s.run("RETURN 1")
        return True
    except Exception:
        return False


def _query_expansion(entity_type: str, entity_value: str, limit: int = 30):
    """Query Neo4j for 1-2 hop expansion from a given entity."""
    from storage.neo4j_store import neo4j
    nodes, edges = [], []
    node_ids = set()

    with neo4j.driver.session() as sess:
        result = sess.run(
            """
            MATCH (center {value: $val, type: $etype})-[r1]-(n1)
            WHERE type(r1) IN ['MENTIONS', 'PROMOTES', 'USES_CONTACT', 'CO_OCCURS', 'EXTRACTED_FROM',
                               'USES_ACCOUNT', 'PROMOTES_LINK', 'PROMOTES_TOOL', 'USES_SLANG']
            OPTIONAL MATCH (n1)-[r2]-(n2)
            WHERE type(r2) IN ['MENTIONS', 'PROMOTES', 'USES_CONTACT', 'CO_OCCURS', 'EXTRACTED_FROM',
                               'USES_ACCOUNT', 'PROMOTES_LINK', 'PROMOTES_TOOL', 'USES_SLANG']
              AND n2.value <> $val
            RETURN center, r1, n1, r2, n2,
                   labels(center) AS cl, labels(n1) AS l1, labels(n2) AS l2,
                   type(r1) AS rt1, type(r2) AS rt2
            LIMIT $limit
            """,
            val=entity_value, etype=entity_type, limit=limit,
        )

        for rec in result:
            center = rec["center"]
            n1 = rec["n1"]
            r1 = rec["r1"]
            n2 = rec.get("n2")
            r2 = rec.get("r2")
            cl = rec.get("cl", [])
            l1 = rec.get("l1", [])

            # Center node
            cid = center.get("value", "")
            if cid not in node_ids:
                node_ids.add(cid)
                nodes.append({
                    "id": cid,
                    "label": cid[:30],
                    "group": _node_group(cl),
                    "center": True,
                    "title": f"{_node_label(cl)}: {cid}",
                })

            # n1 node
            n1id = n1.get("value", str(n1.get("raw_id", "")))
            n1_label = (n1.get("text") or n1.get("content_preview") or n1.get("value", ""))[:30]
            if n1id not in node_ids:
                node_ids.add(n1id)
                g1 = _node_group(l1)
                nodes.append({
                    "id": n1id,
                    "label": n1_label,
                    "group": g1,
                    "center": False,
                    "title": f"{_node_label(l1)}: {n1_label}",
                })

            edges.append({
                "from": cid, "to": n1id,
                "label": rec.get("rt1", "MENTIONS"),
                "rel_type": rec.get("rt1", "MENTIONS"),
            })

            # n2 node (2nd hop)
            if n2 is not None:
                l2 = rec.get("l2", [])
                n2id = n2.get("value", str(n2.get("raw_id", "")))
                n2_label = (n2.get("text") or n2.get("content_preview") or n2.get("value", ""))[:25]
                if n2id not in node_ids:
                    node_ids.add(n2id)
                    g2 = _node_group(l2)
                    nodes.append({
                        "id": n2id,
                        "label": n2_label,
                        "group": g2,
                        "center": False,
                        "title": f"{_node_label(l2)}: {n2_label}",
                    })

                if r2 is not None:
                    edges.append({
                        "from": n1id, "to": n2id,
                        "label": rec.get("rt2", "MENTIONS"),
                        "rel_type": rec.get("rt2", "MENTIONS"),
                    })

    return nodes, edges


def _node_group(labels: list) -> str:
    ls = [l for l in labels if l not in ("Entity",)]
    if "Intel" in ls: return "intel"
    if "Account" in ls: return "account"
    if "Contact" in ls: return "contact"
    if "Link" in ls: return "link"
    if "Tool" in ls: return "tool"
    if "Slang" in ls: return "slang"
    if "Wallet" in ls: return "wallet"
    return "intel"


def _node_label(labels: list) -> str:
    ls = [l for l in labels if l not in ("Entity",)]
    return ls[0] if ls else "Entity"


def _build_summary(nodes: list, edges: list) -> dict:
    groups = {}
    for n in nodes:
        g = n.get("group", "intel")
        groups[g] = groups.get(g, 0) + 1

    edge_types = {}
    for e in edges:
        rt = e.get("rel_type", "?")
        edge_types[rt] = edge_types.get(rt, 0) + 1

    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "groups": groups,
        "edge_types": edge_types,
    }


def _render_graph(nodes: list, edges: list):
    from pyvis.network import Network

    net = Network(height="420px", width="100%", bgcolor=T.BG_CARD, font_color=T.TEXT_MAIN)
    net.repulsion(node_distance=140, spring_length=140)

    colors = {
        "intel": "#8EA898", "account": "#C47A7A",
        "contact": "#9A8EA0", "link": "#7A8EA0",
        "tool": "#C4A35A", "slang": "#B08A6A", "wallet": "#D4A35A",
    }
    shapes = {
        "intel": "square", "account": "dot", "contact": "dot",
        "link": "dot", "tool": "diamond", "slang": "triangle", "wallet": "dot",
    }

    for n in nodes:
        g = n.get("group", "intel")
        size = 28 if n.get("center") else 14
        border = "#D14343" if n.get("center") else T.BORDER
        net.add_node(
            n["id"], label=n.get("label", ""),
            color={"background": colors.get(g, T.SLATE), "border": border},
            shape=shapes.get(g, "dot"),
            size=size,
            title=n.get("title", ""),
            borderWidth=3 if n.get("center") else 1,
        )

    edge_colors = {
        "MENTIONS": T.TEXT_MUTED,
        "PROMOTES": T.ORANGE_HI,
        "CO_OCCURS": "#5B8A6A",
        "USES_CONTACT": "#9A8EA0",
        "EXTRACTED_FROM": T.BORDER,
        "USES_ACCOUNT": "#C47A7A",
        "PROMOTES_LINK": "#7A8EA0",
        "PROMOTES_TOOL": "#C4A35A",
        "USES_SLANG": "#B08A6A",
    }
    edge_widths = {
        "MENTIONS": 1, "PROMOTES": 2, "CO_OCCURS": 3,
        "USES_CONTACT": 1.5, "EXTRACTED_FROM": 0.8,
        "USES_ACCOUNT": 1.5, "PROMOTES_LINK": 1.5,
        "PROMOTES_TOOL": 1.5, "USES_SLANG": 1.2,
    }

    for e in edges:
        rt = e.get("rel_type", "MENTIONS")
        net.add_edge(
            e["from"], e["to"],
            color=edge_colors.get(rt, T.BORDER),
            width=edge_widths.get(rt, 1),
            title=rt,
            dashes=(rt == "USES_CONTACT"),
        )

    fd, path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        net.save_graph(path)
        html_str = Path(path).read_text(encoding="utf-8")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    st.components.v1.html(html_str, height=440, scrolling=True)


def _render_legend():
    st.markdown(
        f"""<div style="display:flex;flex-wrap:wrap;gap:1rem;font-size:0.72rem;color:{T.TEXT_MUTED};margin-top:0.3rem">
        <span>● Account(红)</span><span>■ Intel(绿灰)</span><span>◆ Tool(金)</span>
        <span>● Link(蓝灰)</span><span>● Contact(紫灰)</span>
        <span style="color:{T.ORANGE_HI}">— PROMOTES</span>
        <span style="color:#5B8A6A">— CO-OCCURS</span>
        </div>""",
        unsafe_allow_html=True,
    )


def _query_evidence(entity_type: str, entity_value: str) -> list:
    """Find intel records that mention this entity."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute(
                """SELECT e.raw_id, e.entity_type, e.entity_value, e.context,
                          o.content_raw, o.source_platform, o.collect_time
                   FROM dwd_entity e
                   JOIN ods_raw_intel o ON e.raw_id = o.id
                   WHERE e.entity_type = %s AND e.entity_value = %s
                   ORDER BY e.id DESC LIMIT 20""",
                (entity_type, entity_value),
            )
            return c.fetchall()
    except Exception:
        return []


def show():
    st.markdown("## 关系扩线")
    st.caption("以实体为中心，展开1-2跳关系网络，发现关联情报与团伙线索")

    neo4j_up = _check_neo4j()
    if not neo4j_up:
        st.markdown(
            f"""<div style="background:{T.BG_CARD};border:1px solid {T.BORDER};border-radius:8px;
            padding:2rem;text-align:center">
            <div style="font-size:2rem;margin-bottom:0.8rem;opacity:0.6">&#9888;&#65039;</div>
            <div style="font-size:0.9rem;font-weight:500;color:{T.TEXT_SOFT};margin-bottom:0.3rem">Neo4j 未连接</div>
            <div style="font-size:0.82rem;color:{T.TEXT_MUTED};margin-bottom:1rem">
            确认 Neo4j 已启动：bolt://localhost:7687</div>
            <code style="font-size:0.75rem;background:{T.BG_SIDEBAR};padding:4px 10px;border-radius:4px">
            cd docker && docker compose up -d neo4j</code></div>""",
            unsafe_allow_html=True,
        )
        return

    # Input bar
    c_type, c_val, c_btn = st.columns([1, 2, 0.7])
    with c_type:
        etype = st.selectbox("实体类型", ENTITY_TYPES, label_visibility="collapsed", key="graph_etype")
    with c_val:
        evalue = st.text_input("实体值", placeholder="输入实体值，如 douyin_pro888", label_visibility="collapsed", key="graph_evalue")
    with c_btn:
        go = st.button("开始扩线", type="primary", width="stretch", key="graph_go")

    if not go and not st.session_state.get("graph_has_result"):
        st.markdown(
            T.empty("🕸", "输入实体开始扩线", "选择一个实体类型，输入值，系统将展开1-2跳关系网络"),
            unsafe_allow_html=True,
        )
        return

    if not evalue:
        st.warning("请输入实体值")
        return

    # Query
    if go:
        with st.spinner(f"扩线中: {etype}:{evalue}"):
            try:
                nodes, edges = _query_expansion(etype, evalue)
                st.session_state.graph_nodes = nodes
                st.session_state.graph_edges = edges
                st.session_state.graph_summary = _build_summary(nodes, edges)
                st.session_state.graph_evidence = _query_evidence(etype, evalue)
                st.session_state.graph_has_result = True
            except Exception as exc:
                st.error(f"扩线失败: {exc}")
                return

    nodes = st.session_state.get("graph_nodes", [])
    edges = st.session_state.get("graph_edges", [])
    summary = st.session_state.get("graph_summary", {})
    evidence_rows = st.session_state.get("graph_evidence", [])

    if not nodes:
        st.markdown(
            T.empty("🔍", "未找到关联关系", f"实体 {etype}:{evalue} 在图中暂无关联"),
            unsafe_allow_html=True,
        )
        return

    st.divider()

    # Graph + Summary
    left, right = st.columns([2, 1])

    with left:
        st.markdown(f"**关系图** — `{evalue}` 为中心")
        try:
            _render_graph(nodes, edges)
        except ImportError:
            st.warning("pyvis 未安装")
        except Exception as exc:
            st.error(f"渲染失败: {exc}")
        _render_legend()

    with right:
        st.markdown("**关系摘要**")
        groups = summary.get("groups", {})
        edge_types = summary.get("edge_types", {})
        gang = edge_types.get("CO_OCCURS", 0) > 0

        border_color = T.RED_CRIT if gang else T.SLATE_LO
        title_color = T.RED_CRIT if gang else T.TEXT_MAIN
        st.markdown(
            f"""<div class="intel-card" style="border-left:3px solid {border_color}">
            <div style="font-weight:600;font-size:0.88rem;margin-bottom:0.3rem;
            color:{title_color}">
            {'命中历史团伙' if gang else '未发现团伙关联'}</div>""",
            unsafe_allow_html=True,
        )

        group_labels = {
            "intel": "关联情报", "account": "关联账号", "contact": "联系方式",
            "link": "链接", "tool": "工具", "slang": "黑话", "wallet": "钱包",
        }
        for g, label in group_labels.items():
            cnt = groups.get(g, 0)
            if cnt:
                st.markdown(
                    f'<div style="font-size:0.8rem;padding:0.15rem 0">{label}: <strong>{cnt}</strong></div>',
                    unsafe_allow_html=True,
                )
        st.markdown("</div>", unsafe_allow_html=True)

        # Edge type breakdown
        if edge_types:
            st.markdown("**关系类型**")
            for rt, cnt in sorted(edge_types.items(), key=lambda x: -x[1]):
                st.markdown(
                    f'<div style="font-size:0.78rem;padding:0.1rem 0">{rt}: {cnt} 条</div>',
                    unsafe_allow_html=True,
                )

    # Evidence table below
    if evidence_rows:
        st.divider()
        st.markdown("**证据列表** — 提到该实体的情报记录")
        import pandas as pd
        df = pd.DataFrame([{
            "情报ID": r.get("raw_id", ""),
            "平台": r.get("source_platform", ""),
            "原文摘要": (r.get("content_raw") or "")[:80],
            "上下文": (r.get("context") or "")[:60],
            "时间": str(r.get("collect_time", ""))[:19] if r.get("collect_time") else "",
        } for r in evidence_rows])
        st.dataframe(df, width="stretch", hide_index=True)

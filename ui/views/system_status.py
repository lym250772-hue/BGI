from __future__ import annotations

import pandas as pd
import streamlit as st

from config.settings import settings
from ui import data
from ui.components import page_header


def show():
    page_header(
        "System Status",
        "系统状态",
        "实时检查 MySQL、Neo4j、Milvus、Doris。这里不做缓存，看到的就是当前连接状态。",
    )

    if st.button("重新检测连接", type="primary"):
        st.rerun()

    rows = data.service_status()
    st.dataframe(
        pd.DataFrame([
            {
                "组件": r["name"],
                "用途": r["role"],
                "地址": r["endpoint"],
                "状态": "已连接" if r["ok"] else "未连接",
                "说明": r["detail"],
            }
            for r in rows
        ]),
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("### 当前配置")
    cfg = [
        {"配置项": "MySQL", "值": f"{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"},
        {"配置项": "Neo4j", "值": settings.neo4j_uri},
        {"配置项": "Milvus", "值": f"{settings.milvus_host}:{settings.milvus_port}"},
        {"配置项": "Doris 启用", "值": str(settings.doris_enabled)},
        {"配置项": "Doris", "值": f"{settings.doris_host}:{settings.doris_port}/{settings.doris_database}"},
        {"配置项": "LLM Provider", "值": settings.llm_provider},
        {"配置项": "LLM Model", "值": settings.llm_model},
    ]
    st.dataframe(pd.DataFrame(cfg), hide_index=True, use_container_width=True)

    st.markdown("### 排查提示")
    st.markdown(
        """
        - Doris 容器启动但前端未连接：优先确认 `.env` 中 `BGI_DORIS_ENABLED=true`，然后重启 Streamlit。
        - Milvus 容器启动但前端未连接：优先确认 `slang_embeddings` 与 `intel_embeddings` 两个集合存在。
        - MySQL 未连接：研判工作台不可用，因为原始情报、任务队列和结果表都在 MySQL。
        - Neo4j 未连接：主流水线仍可跑，但关系扩线不会产出。
        """
    )

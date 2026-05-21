"""FastAPI REST API for BGI Intelligence Analysis Agent."""
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

app = FastAPI(title="BGI Intelligence API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class StatsResponse(BaseModel):
    today_total: int = 0
    high_priority: int = 0
    risk_distribution: dict = {}
    entities_total: int = 0


class IntelItem(BaseModel):
    id: int
    source_platform: str
    content: str = ""
    content_type: str = "text"
    priority: str = "normal"
    status: str = "pending"
    collected_at: Optional[datetime] = None
    intent_label: Optional[str] = None
    sub_label: Optional[str] = None
    confidence: Optional[float] = None


class EntityItem(BaseModel):
    id: int
    entity_type: str
    entity_value: str
    extraction_method: str
    first_seen: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/stats", response_model=StatsResponse)
def get_stats():
    """Get dashboard statistics."""
    try:
        from storage.mysql_store import mysql
        stats = mysql.daily_stats()
        # Count entities
        with mysql.cursor() as c:
            c.execute("SELECT COUNT(*) as cnt FROM entities")
            ent_cnt = c.fetchone()["cnt"]
        stats["entities_total"] = ent_cnt
        return StatsResponse(**stats)
    except Exception:
        return StatsResponse()


@app.get("/api/intel")
def list_intel(
    status: str = Query(default="analyzed"),
    platform: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    intent: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0),
):
    """List intelligence items with optional filters."""
    try:
        from storage.mysql_store import mysql
        rows = mysql.list_raw(status=status, platform=platform, priority=priority,
                              limit=limit, offset=offset)
        # Attach analysis results
        for row in rows:
            with mysql.cursor() as c:
                c.execute("SELECT * FROM analysis_results WHERE raw_data_id=%s ORDER BY analyzed_at DESC LIMIT 1",
                          (row["id"],))
                ar = c.fetchone()
                if ar:
                    row["intent_label"] = ar["intent_label"]
                    row["sub_label"] = ar["sub_label"]
                    row["confidence"] = ar["confidence"]
        return {"total": len(rows), "items": rows}
    except Exception as exc:
        return {"total": 0, "items": [], "error": str(exc)}


@app.get("/api/entities")
def list_entities(
    entity_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
):
    """List extracted entities."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            if entity_type:
                c.execute("SELECT * FROM entities WHERE entity_type=%s ORDER BY first_seen DESC LIMIT %s OFFSET %s",
                          (entity_type, limit, offset))
            else:
                c.execute("SELECT * FROM entities ORDER BY first_seen DESC LIMIT %s OFFSET %s", (limit, offset))
            return {"total": len(c.fetchall()), "items": c.fetchall()}
    except Exception as exc:
        return {"total": 0, "items": [], "error": str(exc)}


@app.get("/api/entities/{entity_id}/graph")
def entity_graph(entity_id: int):
    """Get the Neo4j subgraph around an entity."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT * FROM entities WHERE id=%s", (entity_id,))
            ent = c.fetchone()
        if not ent:
            return {"error": "Entity not found"}
        from storage.neo4j_store import neo4j
        results = neo4j.find_entity_neighborhood(ent["entity_type"], ent["entity_value"])
        return {"entity": ent, "neighborhood": results}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/slang")
def list_slang(status: str = Query(default="active")):
    """List slang dictionary entries."""
    try:
        from storage.mysql_store import mysql
        rows = mysql.list_slang(status=status)
        return {"total": len(rows), "items": rows}
    except Exception as exc:
        return {"total": 0, "items": [], "error": str(exc)}


@app.get("/api/cheat-scripts")
def list_cheat_scripts():
    """List generated cheat scripts."""
    try:
        from storage.mysql_store import mysql
        with mysql.cursor() as c:
            c.execute("SELECT * FROM cheat_scripts ORDER BY created_at DESC LIMIT 50")
            return {"items": c.fetchall()}
    except Exception as exc:
        return {"items": [], "error": str(exc)}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

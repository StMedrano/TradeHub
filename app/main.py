from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.routes import router
from app.config import settings
from app.db import SessionLocal, init_db
from app.persistence.models import AuditEvent, TradeProposal, UnderlyingPause

app = FastAPI(title=settings.app_name)
app.include_router(router)

@app.on_event("startup")
def startup() -> None:
    init_db()

@app.get("/", response_class=HTMLResponse)
def dashboard():
    db = SessionLocal()
    try:
        pending = db.scalars(
            select(TradeProposal)
            .where(TradeProposal.status == "pending_approval")
            .order_by(TradeProposal.created_at.desc())
            .limit(20)
        ).all()
        events = db.scalars(
            select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(30)
        ).all()
        pauses = db.scalars(
            select(UnderlyingPause)
            .where(UnderlyingPause.acknowledged.is_(False))
            .order_by(UnderlyingPause.created_at.desc())
        ).all()
    finally:
        db.close()

    cards = "".join(
        f"""<div class="card approval" data-id="{p.id}">
        <div><b>{p.underlying}</b> · {p.strategy}</div>
        <div>{p.contracts} contract(s) · known max loss ${p.known_max_loss:,.2f}</div>
        <div class="muted">{p.created_at}</div>
        <button onclick="tradeAction('{p.id}','approve')">Approve</button>
        <button class="danger" onclick="tradeAction('{p.id}','reject')">Reject</button>
        </div>"""
        for p in pending
    ) or '<div class="card muted">No approvals waiting.</div>'

    pause_cards = "".join(
        f"""<div class="card dangerbox">
        <div><b>{p.symbol}</b> paused</div>
        <div>{p.reason}</div>
        <button onclick="ackPause('{p.symbol}')">Acknowledge</button>
        </div>"""
        for p in pauses
    ) or '<div class="card muted">No assignment/expiration pauses.</div>'

    rows = "".join(
        f"<tr><td>{e.created_at}</td><td>{e.event_type}</td>"
        f"<td>{e.underlying or ''}</td><td>{e.message}</td></tr>"
        for e in events
    )

    badge = "DRY RUN" if settings.trading_mode.value == "dry_run" else "LIVE"

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TradeHub</title>
<style>
body{{font-family:system-ui;background:#0b1020;color:#e7eaf0;margin:0}}
header{{padding:20px 28px;border-bottom:1px solid #25304a;display:flex;justify-content:space-between}}
main{{padding:24px;max-width:1200px;margin:auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}}
.card{{background:#141b2d;border:1px solid #26324e;border-radius:14px;padding:16px;margin:8px 0}}
.badge{{padding:7px 12px;border-radius:999px;background:#233252;font-weight:700}}
.muted{{color:#9da8bf;font-size:.9rem}}
button{{margin-top:12px;margin-right:8px;padding:9px 13px;border:0;border-radius:9px;cursor:pointer}}
.danger{{background:#7c2f3b;color:white}}
.dangerbox{{border-color:#7c2f3b}}
table{{width:100%;border-collapse:collapse;background:#141b2d}}
td,th{{padding:10px;border-bottom:1px solid #26324e;text-align:left}}
</style>
</head>
<body>
<header>
<div><b>TradeHub</b><div class="muted">Robinhood Agentic only · Phase {settings.phase}</div></div>
<div class="badge">{badge}</div>
</header>
<main>
<div class="grid">
<div class="card"><b>Per-trade risk</b><div>{settings.max_trade_loss_pct:.1%} equity</div></div>
<div class="card"><b>Portfolio cap</b><div>{settings.max_portfolio_loss_pct:.1%} equity</div></div>
<div class="card"><b>Daily breaker</b><div>{settings.daily_loss_breaker_pct:.1%} realized loss</div></div>
<div class="card"><b>Concurrent positions</b><div>{settings.max_concurrent_positions}</div></div>
<div class="card"><b>Robinhood MCP</b><div>{"Enabled" if settings.robinhood_mcp_enabled else "Disabled"}</div></div>
</div>

<h2>Approvals <span class="badge">{len(pending)}</span></h2>
{cards}

<h2>Assignment / expiration holds <span class="badge">{len(pauses)}</span></h2>
{pause_cards}

<h2>Audit log</h2>
<table>
<thead><tr><th>Time</th><th>Event</th><th>Symbol</th><th>Message</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</main>

<script>
let previousApprovalCount = {len(pending)};

async function ensureNotifications(){{
  if ("Notification" in window && Notification.permission === "default"){{
    await Notification.requestPermission();
  }}
}}

async function pollApprovals(){{
  try {{
    const r = await fetch("/api/approvals");
    const data = await r.json();
    if (data.length > previousApprovalCount && Notification.permission === "granted") {{
      new Notification("TradeHub approval required", {{
        body: data.length + " trade proposal(s) are waiting."
      }});
    }}
    previousApprovalCount = data.length;
  }} catch (_) {{}}
}}

async function tradeAction(id, verb){{
  const actor = prompt("Your name / operator ID");
  if (!actor) return;
  const note = prompt("Optional note") || "";
  const r = await fetch("/api/approvals/" + id + "/" + verb, {{
    method:"POST",
    headers:{{"Content-Type":"application/json"}},
    body:JSON.stringify({{actor:actor,note:note}})
  }});
  if (!r.ok) alert(await r.text());
  location.reload();
}}

async function ackPause(symbol){{
  const actor = prompt("Your name / operator ID");
  if (!actor) return;
  const r = await fetch("/api/pauses/" + symbol + "/acknowledge", {{
    method:"POST",
    headers:{{"Content-Type":"application/json"}},
    body:JSON.stringify({{actor:actor}})
  }});
  if (!r.ok) alert(await r.text());
  location.reload();
}}

ensureNotifications();
setInterval(pollApprovals, 10000);
</script>
</body>
</html>"""

@app.get("/ready")
def ready():
    return {"ready": True}

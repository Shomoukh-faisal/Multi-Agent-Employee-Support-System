"""Streamlit GUI for the AI Support Employee — professional edition.

Colour theme matched to the project logo (deep blue → royal blue → cyan,
with teal accents). Talks to the FastAPI backend over HTTP and shows rich
response metadata (intent, agent, tool, action, escalation).

Course : AI 483 — Agentic AI and AI Automation, University of Prince Mugrin
Team   : Shomookh Albehani · Wejdan Bardisi · Sadeen Hajjar · Joodi Mulla
Sup.   : Dr. Syed Bukhari

Run from the project root:  streamlit run gui/streamlit_app.py
"""

import html
import os

import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "logo.png")

# --------------------------------------------------------------------------- #
# Project identity
# --------------------------------------------------------------------------- #
TEAM = [
    ("SA", "Shomookh Albehani"),
    ("WB", "Wejdan Bardisi"),
    ("SH", "Sadeen Hajjar"),
    ("JM", "Joodi Mulla"),
]
SUPERVISOR = ("SB", "Dr. Syed Bukhari")
COURSE = "AI 483 · Agentic AI &amp; AI Automation"
UNIVERSITY = "University of Prince Mugrin"

# Inline header mark — recoloured to the logo's blue → cyan palette.
LOGO_SVG = """
<svg width="58" height="58" viewBox="0 0 58 58" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#1D4ED8"/><stop offset="1" stop-color="#06B6D4"/>
  </linearGradient></defs>
  <rect x="2" y="2" width="54" height="54" rx="16" fill="#ffffff"/>
  <rect x="18" y="22" width="22" height="18" rx="6" fill="url(#lg)"/>
  <circle cx="29" cy="13" r="3" fill="url(#lg)"/>
  <rect x="27.5" y="15" width="3" height="7" rx="1.5" fill="url(#lg)"/>
  <circle cx="24.5" cy="29" r="2.6" fill="#22D3EE"/>
  <circle cx="33.5" cy="29" r="2.6" fill="#22D3EE"/>
  <path d="M24 34 q5 5 10 0" stroke="#ffffff" stroke-width="2.4" fill="none" stroke-linecap="round"/>
  <rect x="11" y="26" width="6" height="11" rx="3" fill="url(#lg)"/>
  <rect x="41" y="26" width="6" height="11" rx="3" fill="url(#lg)"/>
</svg>
"""

EXAMPLE_PROMPTS = [
    ("📦", "Where is my order ORD-1002?"),
    ("🛍️", "Tell me about product P-101."),
    ("⚠️", "I want to complain about order ORD-1003. It is late."),
    ("🔁", "I already complained about ORD-1003 and nobody helped me."),
    ("❓", "Where is my order?"),
    ("🙋", "I want to speak to a human."),
]

# Colour per detected intent (badge in the details panel) — tuned to the theme.
INTENT_COLORS = {
    "order_tracking": ("#1D4ED8", "#DBEAFE"),   # blue
    "product_info": ("#0E7490", "#CFFAFE"),     # cyan
    "complaint": ("#B45309", "#FEF3C7"),        # amber
    "escalation": ("#B91C1C", "#FEE2E2"),       # red
    "clarification": ("#0F766E", "#CCFBF1"),    # teal
    "unknown": ("#475569", "#E2E8F0"),          # gray
}

st.set_page_config(
    page_title="AI Support Employee",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
# Styling  (theme: #0B2A6B navy · #1D4ED8 blue · #06B6D4 cyan · #14B8A6 teal)
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
      html, body, [class*="css"] { font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif; }
      .block-container { padding-top: 1.2rem; padding-bottom: 5rem; }

      /* ----- gradient header banner ----- */
      .app-header {
        position: relative; overflow: hidden;
        background: linear-gradient(135deg, #0B2A6B 0%, #1D4ED8 52%, #06B6D4 100%);
        border-radius: 20px; padding: 20px 26px; color: #fff;
        box-shadow: 0 14px 40px rgba(13,72,184,.30); margin-bottom: 18px;
      }
      .app-header::after {
        content:""; position:absolute; top:-60px; right:-40px; width:220px; height:220px;
        background: radial-gradient(circle, rgba(255,255,255,.20), transparent 70%);
      }
      .head-flex { display:flex; align-items:center; gap:16px; position:relative; z-index:1; }
      .head-logo { filter: drop-shadow(0 6px 14px rgba(0,0,0,.25)); flex:0 0 auto; }
      .head-text h1 { margin:0; font-size:1.55rem; font-weight:700; letter-spacing:-.02em; }
      .head-text p  { margin:3px 0 0; opacity:.92; font-size:.92rem; }
      .head-course { margin-top:3px; font-size:.74rem; opacity:.82; font-weight:500; letter-spacing:.02em;}
      .header-pills { margin-top:12px; display:flex; gap:8px; flex-wrap:wrap; position:relative; z-index:1; }
      .pill {
        background: rgba(255,255,255,.18); border:1px solid rgba(255,255,255,.32);
        padding:4px 12px; border-radius:999px; font-size:.78rem; font-weight:600;
      }
      .pill .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }
      .dot-on  { background:#34D399; box-shadow:0 0 0 3px rgba(52,211,153,.3); }
      .dot-off { background:#F87171; box-shadow:0 0 0 3px rgba(248,113,113,.3); }

      /* ----- chat bubbles ----- */
      .msg-row { display:flex; margin:10px 0; align-items:flex-end; gap:10px; animation:fade .25s ease; }
      @keyframes fade { from {opacity:0; transform:translateY(6px);} to {opacity:1; transform:none;} }
      .msg-row.user { justify-content:flex-end; }
      .avatar {
        width:34px; height:34px; border-radius:50%; flex:0 0 34px;
        display:flex; align-items:center; justify-content:center; font-size:18px; background:#E0F2FE;
      }
      .bubble {
        max-width:78%; padding:11px 15px; border-radius:16px; font-size:.95rem;
        line-height:1.45; box-shadow:0 1px 2px rgba(0,0,0,.06); word-wrap:break-word;
      }
      .user-bubble { background:linear-gradient(135deg,#1D4ED8,#06B6D4); color:#fff; border-bottom-right-radius:5px; }
      .bot-bubble  { background:#fff; color:#0F172A; border:1px solid #E2E8F0; border-bottom-left-radius:5px; }

      .empty-state { text-align:center; color:#94A3B8; padding:48px 16px; border:1px dashed #CBD5E1;
        border-radius:16px; background:#F8FAFC; }
      .empty-state .big { font-size:42px; margin-bottom:8px; }

      /* ----- detail cards ----- */
      .detail-card { background:#fff; border:1px solid #E2E8F0; border-radius:14px; padding:14px 16px;
        margin-bottom:12px; box-shadow:0 1px 2px rgba(0,0,0,.04); transition:box-shadow .2s ease; }
      .detail-card:hover { box-shadow:0 6px 18px rgba(13,72,184,.12); }
      .detail-card .label { font-size:.72rem; text-transform:uppercase; letter-spacing:.05em;
        color:#94A3B8; font-weight:700; margin-bottom:6px; }
      .kv { display:flex; justify-content:space-between; padding:5px 0; font-size:.9rem; border-bottom:1px solid #F1F5F9; }
      .kv:last-child { border-bottom:none; }
      .kv .k { color:#64748B; }  .kv .v { color:#0F172A; font-weight:600; text-align:right; }
      .badge { display:inline-block; padding:5px 12px; border-radius:999px; font-size:.82rem; font-weight:700; }
      .status-good { background:#CCFBF1; color:#0F766E; border:1px solid #5EEAD4; }
      .status-esc  { background:#FEE2E2; color:#B91C1C; border:1px solid #FCA5A5; }
      .reason { font-size:.85rem; color:#7F1D1D; margin-top:8px; line-height:1.4; }

      /* ----- sidebar buttons ----- */
      section[data-testid="stSidebar"] .stButton button {
        text-align:left; border-radius:10px; border:1px solid #E2E8F0; background:#fff;
        font-size:.85rem; transition:all .15s ease;
      }
      section[data-testid="stSidebar"] .stButton button:hover {
        border-color:#38BDF8; background:#EFF8FF; transform:translateX(2px);
      }

      /* ----- team card ----- */
      .team-card { background:linear-gradient(160deg,#EFF6FF,#FFFFFF); border:1px solid #BFDBFE;
        border-radius:14px; padding:14px 14px 10px; }
      .team-title { font-size:.7rem; text-transform:uppercase; letter-spacing:.06em; color:#1D4ED8;
        font-weight:800; margin-bottom:10px; }
      .member { display:flex; align-items:center; gap:9px; padding:4px 0; }
      .ini { width:27px; height:27px; border-radius:50%; flex:0 0 27px; color:#fff; font-size:.66rem;
        font-weight:700; display:flex; align-items:center; justify-content:center;
        background:linear-gradient(135deg,#1D4ED8,#06B6D4); }
      .ini.sup { background:linear-gradient(135deg,#0D9488,#06B6D4); }
      .nm { font-size:.85rem; color:#0F172A; font-weight:500; }
      .sup-block { margin-top:9px; padding-top:9px; border-top:1px dashed #BFDBFE; }
      .sup-role { font-size:.66rem; color:#94A3B8; font-weight:700; text-transform:uppercase;
        letter-spacing:.05em; margin-bottom:4px; }

      /* ----- system-activity panel ----- */
      .sa-section { font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; color:#94A3B8;
        font-weight:700; margin:0 0 8px; }
      .step { display:flex; align-items:center; gap:8px; font-size:.83rem; padding:3px 0; color:#64748B; }
      .step .ic { width:18px; height:18px; border-radius:50%; background:#DBEAFE; color:#1D4ED8;
        font-size:11px; display:flex; align-items:center; justify-content:center; flex:0 0 18px; }
      .step.active { color:#0F172A; font-weight:600; }
      .step.active .ic { background:linear-gradient(135deg,#1D4ED8,#06B6D4); color:#fff; }
      .chip { display:inline-block; background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
        padding:3px 10px; border-radius:999px; font-size:.78rem; font-weight:600; margin:4px 4px 0 0; }
      .conf-wrap { height:8px; background:#E2E8F0; border-radius:999px; overflow:hidden; margin-top:6px; }
      .conf-bar { height:100%; background:linear-gradient(90deg,#1D4ED8,#06B6D4); border-radius:999px; }
      .data-table { width:100%; font-size:.82rem; border-collapse:collapse; margin-top:4px; }
      .data-table td { padding:4px 0; border-bottom:1px solid #F1F5F9; }
      .data-table td.k { color:#64748B; }
      .data-table td.v { color:#0F172A; font-weight:600; text-align:right; word-break:break-word; padding-left:10px; }

      /* ----- footer ----- */
      .footer { text-align:center; color:#94A3B8; font-size:.78rem; margin-top:26px;
        padding-top:14px; border-top:1px solid #E2E8F0; }
      .footer b { color:#1D4ED8; }

      #MainMenu, footer { visibility:hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_meta" not in st.session_state:
    st.session_state.last_meta = None
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None


# --------------------------------------------------------------------------- #
# Backend helpers
# --------------------------------------------------------------------------- #
def backend_info():
    try:
        r = requests.get(f"{API_BASE_URL}/", timeout=3)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        return None
    return None


def send_message(customer_id: str, message: str):
    st.session_state.messages.append({"role": "user", "content": message})
    try:
        resp = requests.post(
            f"{API_BASE_URL}/support/chat",
            json={"customer_id": customer_id, "message": message},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        st.session_state.messages.append(
            {"role": "assistant", "content": f"⚠️ Could not reach the backend: {exc}"}
        )
        st.session_state.last_meta = None
        return
    st.session_state.messages.append({"role": "assistant", "content": data.get("message", "")})
    st.session_state.last_meta = data


def render_bubble(role: str, content: str):
    safe = html.escape(content).replace("\n", "<br>")
    if role == "user":
        st.markdown(
            f'<div class="msg-row user"><div class="bubble user-bubble">{safe}</div>'
            f'<div class="avatar">🧑</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="msg-row bot"><div class="avatar">🤖</div>'
            f'<div class="bubble bot-bubble">{safe}</div></div>',
            unsafe_allow_html=True,
        )


def show_logo():
    """Render the real project logo in the sidebar, if the file is present."""
    if os.path.exists(LOGO_PATH):
        try:
            st.image(LOGO_PATH, use_container_width=True)
        except TypeError:  # older Streamlit
            st.image(LOGO_PATH, use_column_width=True)


PIPELINE_LABELS = {
    "load_memory": "Load conversation memory",
    "query_handler": "Classify intent & entities",
    "route_request": "Route to specialized agent",
    "support_resolution": "Support resolution agent",
    "complaint_handler": "Complaint handler agent",
    "escalation_agent": "Escalation agent",
    "clarification": "Clarification",
    "final_decision": "Build structured response",
    "update_memory": "Save interaction to memory",
}


def pipeline_html(pipeline, active_agent):
    rows = []
    for step in pipeline:
        label = PIPELINE_LABELS.get(step, step)
        active = " active" if step == active_agent else ""
        rows.append(f'<div class="step{active}"><span class="ic">✓</span>{html.escape(label)}</div>')
    return "".join(rows)


def entities_html(entities):
    nice = {
        "order_id": "Order", "product_id": "Product", "product_name": "Name",
        "complaint_issue": "Issue", "urgency": "Urgency", "wants_human": "Wants human",
    }
    chips = []
    for key, label in nice.items():
        val = (entities or {}).get(key)
        if val in (None, "", False):
            continue
        text = str(val)
        if len(text) > 42:
            text = text[:42] + "…"
        chips.append(f'<span class="chip">{label}: {html.escape(text)}</span>')
    return "".join(chips) or '<span style="color:#94A3B8;font-size:.82rem;">none extracted</span>'


def data_table_html(data):
    rows = []
    for key, val in (data or {}).items():
        if key == "found":
            continue
        if isinstance(val, dict):
            for kk, vv in val.items():
                if not isinstance(vv, (dict, list)):
                    rows.append((f"{key}.{kk}", vv))
        elif isinstance(val, list):
            rows.append((key, f"{len(val)} item(s)"))
        else:
            rows.append((key, val))
    rows = rows[:10]
    if not rows:
        return '<span style="color:#94A3B8;font-size:.82rem;">no data returned</span>'
    cells = "".join(
        f'<tr><td class="k">{html.escape(str(k))}</td>'
        f'<td class="v">{html.escape(str(v))}</td></tr>'
        for k, v in rows
    )
    return f'<table class="data-table">{cells}</table>'


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
info = backend_info()

with st.sidebar:
    show_logo()
    st.header("⚙️ Settings")
    customer_id = st.text_input("Customer ID", value="CUST-01", help="e.g. CUST-01, CUST-02, CUST-03")

    st.divider()
    st.caption("BACKEND")
    if info:
        st.success("Connected")
        st.caption(f"Model: `{info.get('model', '—')}`")
        st.caption(f"Mode: **{'Gemini' if info.get('gemini_enabled') else 'Rule-based fallback'}**")
    else:
        st.error("Offline")
        st.caption(f"Start the API, expected at `{API_BASE_URL}`")

    st.divider()
    st.caption("💡 EXAMPLE PROMPTS")
    for i, (icon, prompt) in enumerate(EXAMPLE_PROMPTS):
        if st.button(f"{icon}  {prompt}", key=f"ex_{i}", use_container_width=True):
            st.session_state.pending_prompt = prompt

    st.divider()
    if st.button("🗑️  Clear conversation", use_container_width=True, type="primary"):
        st.session_state.messages = []
        st.session_state.last_meta = None
        try:
            requests.delete(f"{API_BASE_URL}/memory/{customer_id}", timeout=5)
        except requests.RequestException:
            pass
        st.rerun()

    st.divider()
    members_html = "".join(
        f'<div class="member"><div class="ini">{ini}</div><div class="nm">{html.escape(name)}</div></div>'
        for ini, name in TEAM
    )
    st.markdown(
        f"""
        <div class="team-card">
          <div class="team-title">👥 Project Team</div>
          {members_html}
          <div class="sup-block">
            <div class="sup-role">🎓 Supervised by</div>
            <div class="member"><div class="ini sup">{SUPERVISOR[0]}</div>
              <div class="nm">{html.escape(SUPERVISOR[1])}</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Header banner
# --------------------------------------------------------------------------- #
status_dot = "dot-on" if info else "dot-off"
status_text = "Online" if info else "Offline"
mode_pill = ""
if info:
    mode_pill = f'<span class="pill">🧠 {"Gemini" if info.get("gemini_enabled") else "Fallback mode"}</span>'

st.markdown(
    f"""
    <div class="app-header">
      <div class="head-flex">
        <div class="head-logo">{LOGO_SVG}</div>
        <div class="head-text">
          <h1>Agentic AI Support</h1>
          <p>Virtual support employee — order tracking, product info, complaints &amp; smart escalation.</p>
          <div class="head-course">{COURSE} · {UNIVERSITY}</div>
        </div>
      </div>
      <div class="header-pills">
        <span class="pill"><span class="dot {status_dot}"></span>{status_text}</span>
        <span class="pill">👤 {html.escape(customer_id or "—")}</span>
        {mode_pill}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Main layout
# --------------------------------------------------------------------------- #
chat_col, detail_col = st.columns([2, 1], gap="large")

with chat_col:
    st.subheader("💬 Conversation")
    if st.session_state.messages:
        for msg in st.session_state.messages:
            render_bubble(msg["role"], msg["content"])
    else:
        st.markdown(
            '<div class="empty-state"><div class="big">💬</div>'
            "<b>Start a conversation</b><br>"
            "Type a message below or tap an example prompt in the sidebar.</div>",
            unsafe_allow_html=True,
        )

    if st.session_state.pending_prompt:
        queued = st.session_state.pending_prompt
        st.session_state.pending_prompt = None
        send_message(customer_id, queued)
        st.rerun()

    user_input = st.chat_input("Type your message…")
    if user_input:
        send_message(customer_id, user_input)
        st.rerun()

with detail_col:
    st.subheader("🧭 System Activity")
    meta = st.session_state.last_meta
    if not meta:
        st.markdown(
            '<div class="empty-state" style="padding:26px 14px;">'
            '<div class="big">🔍</div><b>No activity yet</b><br>'
            "Send a message and this panel will show the full pipeline: "
            "intent, confidence, the agent &amp; tool used, the data retrieved, "
            "and the final decision.</div>",
            unsafe_allow_html=True,
        )
    else:
        intent = meta.get("intent", "unknown")
        fg, bg = INTENT_COLORS.get(intent, INTENT_COLORS["unknown"])
        conf = float(meta.get("confidence", 0.0))
        conf_pct = round(conf * 100)

        # 1) Agentic pipeline that executed
        st.markdown(
            f'<div class="detail-card"><div class="sa-section">⚙️ Agentic pipeline executed</div>'
            f'{pipeline_html(meta.get("pipeline", []), meta.get("agent"))}</div>',
            unsafe_allow_html=True,
        )

        # 2) Understanding: intent + confidence + agent + action + entities
        st.markdown(
            f"""
            <div class="detail-card">
              <div class="sa-section">🧠 Understanding</div>
              <span class="badge" style="background:{bg};color:{fg};">{html.escape(intent)}</span>
              <div style="font-size:.78rem;color:#64748B;margin-top:10px;">Confidence
                <b style="color:#0F172A;">{conf_pct}%</b></div>
              <div class="conf-wrap"><div class="conf-bar" style="width:{conf_pct}%;"></div></div>
              <div class="kv" style="margin-top:12px;"><span class="k">Agent</span>
                <span class="v">{html.escape(str(meta.get('agent','—')))}</span></div>
              <div class="kv"><span class="k">Action</span>
                <span class="v">{html.escape(str(meta.get('action','—')))}</span></div>
              <div class="sa-section" style="margin:12px 0 4px;">Extracted entities</div>
              {entities_html(meta.get('entities', {}))}
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 3) Tool + the real data it retrieved (proves CSV access)
        st.markdown(
            f"""
            <div class="detail-card">
              <div class="sa-section">🔧 Tool &amp; retrieved data</div>
              <div class="kv"><span class="k">Tool used</span>
                <span class="v">{html.escape(str(meta.get('tool_used') or '—'))}</span></div>
              {data_table_html(meta.get('data', {}))}
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 4) Decision + memory
        if meta.get("escalated"):
            decision = (
                '<span class="badge status-esc">🚨 Escalated to human</span>'
                f'<div class="reason">{html.escape(meta.get("escalation_reason") or "")}</div>'
            )
        else:
            decision = '<span class="badge status-good">✅ Resolved automatically</span>'
        st.markdown(
            f"""
            <div class="detail-card">
              <div class="sa-section">🧩 Decision</div>
              {decision}
              <div class="kv" style="margin-top:12px;"><span class="k">Memory updated</span>
                <span class="v">{'✅ yes' if meta.get('memory_updated') else '— no'}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("📦 Raw structured response (JSON)"):
            st.json(meta)

# --------------------------------------------------------------------------- #
# Footer
# --------------------------------------------------------------------------- #
st.markdown(
    f"""
    <div class="footer">
      {COURSE} · {UNIVERSITY}<br>
      Developed by <b>Shomookh Albehani</b>, <b>Wejdan Bardisi</b>,
      <b>Sadeen Hajjar</b> &amp; <b>Joodi Mulla</b> · Supervised by <b>Dr. Syed Bukhari</b>
    </div>
    """,
    unsafe_allow_html=True,
)

"""AI Infrastructure Risk Browser: Red Flags chat + supporting views (Dash).

Run:  python app.py   ->  http://127.0.0.1:8050
"""
import sys
import uuid
from pathlib import Path

import dash
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR / "engine"))
sys.path.insert(0, str(APP_DIR / "agent"))
sys.path.insert(0, str(APP_DIR / "views"))

import map_view  # noqa: E402
import red_flags as rf  # noqa: E402
from analyst import ask  # noqa: E402
from entities import META  # noqa: E402

# Palette: warm paper, navy, steel, rust, taupe, mustard (editorial diligence-deck style)
PAPER, BEIGE, RULE = "#f8f7f4", "#ece8de", "#ddd8ce"
INK, INK_2, MUTED = "#1c1917", "#44403c", "#78716c"
NAVY, STEEL, RUST, TAUPE, MUSTARD = "#14202a", "#2f5568", "#7f3822", "#7a6a5a", "#eed394"
CONF_COLOR = {"High": STEEL, "Medium": "#b08a2e", "Low": RUST}
LENS_COLOR = {"Project delay": NAVY, "State policy": RUST, "Counterparty": TAUPE}
LENS_BLURB = {"Project delay": "Own sites: concentration, moratoria, permits, schedule",
              "State policy": "Bills, tariffs and ordinances where the company builds",
              "Counterparty": "Concentration, soft commitments, second-order and circular links"}

COMPANIES = sorted(set(rf.site_links.entity) | set(META), key=str.lower)
SESSIONS: dict[str, dict] = {}  # server-side chat state: {session_id: {"history": [...], "company": str}}

SUGGESTIONS = [
    "I'm considering CoreWeave. Where are the red flags?",
    "What if Texas freezes new construction for 24 months?",
    "Who does OpenAI depend on, and how concentrated is it?",
    "Compare Crusoe's policy exposure to its counterparty risk.",
]

app = dash.Dash(__name__, title="Data Centers Decoded", suppress_callback_exceptions=True)
server = app.server


# ---------- components ----------
def conf_tag(label, score):
    return html.Span(f"{label} · {score}", className=f"conf conf-{label.lower()}")


def stat(value, label, sub=None):
    return html.Div(className="stat", children=[
        html.Div(label, className="stat-label"), html.Div(value, className="stat-value"),
        html.Div(sub, className="stat-sub") if sub else None])


METRIC_HELP = {
    "Likelihood": "How likely the bad outcome is; driven by policy status (enacted > in rulemaking > in committee).",
    "Severity": "Share of the company's pipeline or deal book at stake.",
    "Confidence": "Evidence quality, reduced for each counterparty hop. Low = weak evidence, not low risk.",
    "At stake": "MW or commitment-weighted dollars exposed.",
}


def metric(label, value, cls=""):
    return html.Div(className=f"m {cls}", title=METRIC_HELP[label],
                    children=[html.Div(label, className="m-label"), html.Div(value, className="m-value")])


def flag_row(f):
    return html.Details(className="frow", children=[
        html.Summary(className="frow-grid", children=[
            html.Div(f"{f['rank']:02d}", className="c-rank"),
            html.Div(className="c-main", children=[
                html.Div(f["title"], className="c-title"),
                html.Div([html.Span(className="swatch", style={"background": LENS_COLOR.get(f["lens"], MUTED)}),
                          f"{f['lens']} · {f['kind']}"], className="c-lens"),
            ]),
            html.Div(className="c-metrics", children=[
                metric("Likelihood", f"{f['likelihood']:.0%}"),
                metric("Severity", f"{f['severity']:.0%}"),
                metric("Confidence", conf_tag(f["confidence_label"], f["confidence"])),
                metric("At stake", f["at_stake"] or "n/a", "m-stake"),
            ]),
        ]),
        html.Div(className="frow-body", children=[
            html.P(f["detail"]),
            html.Div([html.Span("Confidence basis", className="mini"), "; ".join(f["confidence_reasons"])],
                     className="basis"),
            html.Div([html.Span("Evidence", className="mini"), ", ".join(map(str, f["evidence"]))], className="basis"),
        ]),
    ])


_OFFSETS = [(0, 0), (-1, 0), (0, 1), (-1, 1), (-2, 0), (-2, 1), (0, 2), (-1, 2), (-2, 2), (-3, 0)]


def _spread(flags, step=0.065):
    """Fan out flags that land on (nearly) the same spot so every numbered marker stays readable.
    Markers keep their true value in the hover; only the drawn position is nudged."""
    placed, pos = [], {}
    for f in flags:
        x0, y0 = f["likelihood"], f["severity"]
        for dx, dy in _OFFSETS:
            x = x0 + dx * step if x0 > 0.5 else x0 - dx * step  # fan toward the plot's interior
            y = y0 + dy * step
            if all(abs(x - px) >= step * 0.9 or abs(y - py) >= step * 0.9 for px, py in placed):
                break
        placed.append((x, y))
        pos[f["rank"]] = (x, y)
    return pos


def risk_matrix(flags):
    fig = go.Figure()
    pos = _spread(flags)
    for lab, col in CONF_COLOR.items():
        fs = [f for f in flags if f["confidence_label"] == lab]
        if not fs:
            continue
        fig.add_trace(go.Scatter(
            x=[pos[f["rank"]][0] for f in fs], y=[pos[f["rank"]][1] for f in fs], mode="markers+text",
            text=[str(f["rank"]) for f in fs], textposition="middle center",
            textfont={"color": "#ffffff", "size": 10, "family": "Inter"},
            marker={"size": 22, "color": col, "line": {"color": BEIGE, "width": 1.5}},
            name=f"{lab} confidence",
            hovertext=[f"#{f['rank']} {f['title']}<br>Likelihood {f['likelihood']:.0%} · Severity {f['severity']:.0%}"
                       f" · Confidence {f['confidence']}" for f in fs],
            hoverinfo="text"))
    fig.add_shape(type="rect", x0=0.5, x1=1.02, y0=0.3, y1=1.02, line_width=0, fillcolor="rgba(238,211,148,0.45)",
                  layer="below")
    fig.add_annotation(x=1.0, y=1.0, text="Watch zone", showarrow=False, xanchor="right", yanchor="top",
                       font={"size": 10, "color": INK_2, "family": "Inter"})
    axis = {"range": [0, 1.02], "gridcolor": RULE, "tickformat": ".0%", "zeroline": False, "linecolor": INK_2,
            "tickfont": {"size": 10}}
    fig.update_layout(
        height=320, margin={"l": 48, "r": 12, "t": 8, "b": 40}, paper_bgcolor=BEIGE, plot_bgcolor=BEIGE,
        font={"color": INK_2, "family": "Inter", "size": 11},
        legend={"orientation": "h", "y": -0.22, "x": 0, "font": {"size": 10}},
        xaxis=axis | {"title": {"text": "Likelihood", "font": {"size": 11}}},
        yaxis=axis | {"title": {"text": "Severity", "font": {"size": 11}}})
    return fig


def headline(r):
    """Action title in the deck's style: the conclusion, not the topic."""
    if not r["flags"]:
        return f"{r['company']}: no material red flags in the current data"
    t = r["flags"][0]["title"]
    t = t[0].lower() + t[1:] if t[1:2].islower() else t  # keep acronyms/state codes ("TX: SB 6") intact
    return f"{r['company']}'s biggest exposure: {t}"


def report(r, scenario=None):
    if not r or "error" in r:
        return html.Div(className="empty", children=[
            html.Div("Red flags", className="eyebrow"),
            html.H1("Pick a company to see where its risk exposures lie", className="title"),
            html.P("Every exposure is ranked by risk (severity × likelihood), with a separate confidence score that "
                   "says how much the evidence supports it.", className="lede"),
            html.Div(className="lens-tabs", children=[
                html.Div([html.Div(k, className="lens-tab", style={"background": c}),
                          html.Div(LENS_BLURB[k], className="lens-blurb")]) for k, c in LENS_COLOR.items()])])
    flags = r["flags"]
    counts = {k: sum(f["lens"] == k for f in flags) for k in LENS_COLOR}
    kids = [
        html.Div(f"{r['group']} · {r['ticker'] or 'Private'}", className="eyebrow"),
        html.H1(headline(r), className="title"),
        html.Div(className="stats", children=[
            stat(f"{r['pipeline_mw']:,}", "Pipeline", "MW planned or under construction"),
            stat(str(r["pipeline_sites"]), "Sites", "in development"),
            stat(f"${r['deal_book_usd_weighted'] / 1e9:,.1f}B", "Deal book", "commitment-weighted"),
            stat(str(len(flags)), "Top red flags", f"of {r.get('flags_found', len(flags))} found, ranked by risk"),
        ]),
        html.Div(className="lens-tabs", children=[
            html.Div([html.Div([k, html.Span(counts[k], className="lens-n")], className="lens-tab",
                               style={"background": c}),
                      html.Div(LENS_BLURB[k], className="lens-blurb")]) for k, c in LENS_COLOR.items()]),
    ]
    if scenario and "error" not in scenario:
        kids.append(scenario_box(scenario))
    kids += [
        html.Div(className="two-col", children=[
            html.Div(className="panel", children=[
                html.Div("Risk matrix", className="panel-title"),
                html.Div("Each flag by likelihood and severity; color is confidence", className="panel-sub"),
                dcc.Graph(figure=risk_matrix(flags), config={"displayModeBar": False})]),
            html.Div(className="panel how", children=[
                html.Div("How to read this", className="panel-title"),
                html.Dl([html.Dt("Severity"), html.Dd("Share of the company's pipeline or deal book at stake."),
                         html.Dt("Likelihood"), html.Dd("Driven by policy status: enacted > in rulemaking > "
                                                         "introduced > news only."),
                         html.Dt("Confidence"), html.Dd("Evidence quality, reduced for each counterparty hop. "
                                                         "Low confidence means weak evidence, not low risk.")])]),
        ]),
        html.Div(className="table-head", children=[html.Div("Top red flags, ranked by risk (severity × likelihood)")]),
        html.Div([flag_row(f) for f in flags], className="ftable"),
        html.Div("Select a row for detail, the basis for its confidence score, and the source IDs.", className="note"),
    ]
    return kids


def scenario_box(s):
    return html.Div(className="scenario", children=[
        html.Div("Hypothetical scenario", className="eyebrow light"),
        html.H2(f"{', '.join(s['states'])} construction freeze for {s['months']} months", className="sc-title"),
        html.Div(className="stats light", children=[
            stat(f"{s['mw_delayed']:,} MW", "Delayed", f"{s['pct_pipeline_delayed']:.0%} of pipeline"),
            stat(f"${s['deferred_revenue_usd'] / 1e9:,.1f}B", "Deferred revenue", "extrapolated"),
            stat(f"${s['deal_usd_exposed'] / 1e9:,.1f}B", "Deal value exposed", "via counterparties"),
            html.Div(className="stat", children=[html.Div("Confidence", className="stat-label"),
                                                 conf_tag(s["confidence_label"], s["confidence"])]),
        ]),
        html.Ul([html.Li(f"{p['counterparty']} · {p['deal_id']} {p['category'].lower()} · "
                         f"${p['usd_exposed'] / 1e9:,.2f}B · {p['how']}") for p in s["deal_paths"][:4]],
                className="paths"),
        html.Div(f"Assumption: {s['assumption']}.", className="sc-note"),
    ])


def bubble(role, text, meta=None):
    kids = [dcc.Markdown(text, className="md")]
    if meta:
        kids.append(html.Div(meta, className="bubble-meta"))
    return html.Div(kids, className=f"bubble {role}")


# ---------- layout ----------
app.layout = html.Div(className="app", children=[
    dcc.Store(id="sid"),
    html.Header(className="top", children=[
        html.Div(className="top-left", children=[
            html.Span("Data Centers Decoded", className="brand"),
            dcc.Tabs(id="view", value="flags", className="nav", parent_className="nav-wrap", children=[
                dcc.Tab(label="Red flags", value="flags", className="nav-tab", selected_className="nav-tab--on"),
                dcc.Tab(label="Projects & policy map", value="map", className="nav-tab",
                        selected_className="nav-tab--on")]),
        ]),
        html.Div(id="flags-picker", children=dcc.Dropdown(id="company", options=COMPANIES,
                                                          placeholder="Select a company", className="co-dd",
                                                          clearable=True)),
    ]),
    html.Div(id="map-section", style={"display": "none"}, children=map_view.layout()),
    html.Main(id="flags-section", className="grid", children=[
        html.Section(className="chat-col", children=[
            html.Div("Analyst", className="eyebrow"),
            html.Div(id="chat-log", className="chat-log", children=[bubble("bot", (
                "Name a company you are evaluating and I will rank its red flags across **project delay**, "
                "**state policy** and **counterparty** risk, each with a confidence score. Then test a scenario, "
                "for example: *what if Georgia pauses new data centers for a year?*"))]),
            html.Div(className="chips", children=[
                html.Button(s, id={"type": "chip", "i": i}, className="chip", n_clicks=0)
                for i, s in enumerate(SUGGESTIONS)]),
            dcc.Loading(type="dot", color=STEEL, children=html.Div(id="busy")),
            html.Div(className="composer", children=[
                dcc.Textarea(id="q", placeholder="Ask about a company or a scenario", className="q",
                             title="Question for the red-flags analyst"),
                html.Button("Send", id="send", className="send", n_clicks=0)]),
            html.Div("Figures come only from the risk engine; answers citing unsupported numbers are withheld. "
                     "Not investment advice.", className="fine"),
        ]),
        html.Section(id="report", className="report-col", children=report(None)),
    ]),
])


# ---------- callbacks ----------
map_view.register(app)


@app.callback(Output("flags-section", "style"), Output("map-section", "style"), Output("flags-picker", "style"),
              Input("view", "value"))
def switch_view(view):  # both views stay mounted, so chat history survives switching
    on, off = {}, {"display": "none"}
    return (on, off, on) if view == "flags" else (off, on, off)


@app.callback(Output("sid", "data"), Input("sid", "data"))
def init_session(sid):
    return sid or str(uuid.uuid4())


@app.callback(Output("q", "value", allow_duplicate=True), Input({"type": "chip", "i": ALL}, "n_clicks"),
              prevent_initial_call=True)
def use_chip(_):
    if not ctx.triggered_id or not any(_):
        return dash.no_update
    return SUGGESTIONS[ctx.triggered_id["i"]]


@app.callback(
    Output("chat-log", "children"), Output("report", "children"), Output("q", "value"), Output("busy", "children"),
    Output("company", "value"),
    Input("send", "n_clicks"), Input("company", "value"),
    State("q", "value"), State("chat-log", "children"), State("sid", "data"),
    prevent_initial_call=True)
def on_turn(_, company, q, log, sid):
    sess = SESSIONS.setdefault(sid or "anon", {"history": None, "company": None})
    if ctx.triggered_id == "company":
        if not company:
            return dash.no_update, report(None), dash.no_update, "", dash.no_update
        if company == sess["company"]:  # echo from a chat turn syncing the dropdown; keep the scenario view
            return (dash.no_update,) * 5
        sess["company"] = company  # deterministic: no LLM call needed to show the report
        return dash.no_update, report(rf.red_flags(company)), dash.no_update, "", dash.no_update
    if not q or not q.strip():
        return dash.no_update, dash.no_update, dash.no_update, "", dash.no_update
    out = ask(q.strip()[:1000], history=sess["history"], last_company=sess["company"])
    sess["history"], sess["company"] = out["history"], out["company"] or sess["company"]
    lg = out["log"]
    meta = (f"{lg['status']} · {lg['seconds']}s · tools: {', '.join(t for t in lg['tools'] if not t.startswith('[')) or 'none'}"
            + (f" · tokens in {lg['input_tokens']:,} / out {lg['output_tokens']:,}" if lg["input_tokens"] else "")
            + (f" · grounding retries: {len(lg['grounding_failures'])}" if lg["grounding_failures"] else ""))
    log = (log or []) + [bubble("user", q.strip()), bubble("bot", out["answer"], meta)]
    flags = out["flags"] or (rf.red_flags(sess["company"]) if sess["company"] else None)
    return log, report(flags, out["scenario"]), "", "", sess["company"]


app.clientside_callback(  # keep the newest message in view
    "function(c){const el=document.getElementById('chat-log'); if(el){setTimeout(()=>el.scrollTop=el.scrollHeight,50);} return '';}",
    Output("busy", "title"), Input("chat-log", "children"))


if __name__ == "__main__":
    # use_reloader=False so one edit never spawns a second server (AGENTS.md)
    app.run(debug=False, use_reloader=False, port=8050)

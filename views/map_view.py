"""Map view: projects by status, local moratoria, and state policy pressure, filterable by company.

Policy pressure index (per state) = sum over restrictive policy items of likelihood x effect weight
(delay 1.0, cost 0.5, compliance 0.25) + active/proposed moratoria x likelihood. Favorable items
(fast-track, incentives) are counted separately and never raise the index.
"""
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update

import red_flags as rf
from build import STATES

PAPER, BEIGE, RULE, INK, INK_2, MUTED = "#f8f7f4", "#ece8de", "#ddd8ce", "#1c1917", "#44403c", "#78716c"
NAVY, STEEL, RUST, TAUPE, MUSTARD = "#14202a", "#2f5568", "#7f3822", "#7a6a5a", "#eed394"
STATUS_COLOR = {"Operating": "#a8a29e", "Under Construction": STEEL, "Planned": RUST}
EFFECT_WEIGHT = {"delay": 1.0, "cost": 0.5, "compliance": 0.25, "other": 0.25}
EFFECT_COLOR = {"delay": RUST, "cost": "#b08a2e", "compliance": TAUPE, "favorable": STEEL, "other": MUTED}
STATE_NAME = {v: k for k, v in STATES.items()}
ALL = "All companies"

SITES = rf.sites.dropna(subset=["latitude", "longitude"]).copy()
LINKS = rf.site_links
POL = rf.POLICIES.copy()
MOR = rf.MORATORIA.copy()
POL["bucket"] = POL.effect.where(~POL.favorable, "favorable")
COMPANIES = [ALL] + sorted(set(LINKS.entity), key=str.lower)
HIGH_PRESSURE = 20.0  # roughly the top quartile of states with the full tracker export
CATEGORIES = sorted(POL.category.unique())


def pressure_index(categories=None):
    p = POL[(POL.state != "US") & ~POL.favorable]
    if categories:
        p = p[p.category.isin(categories)]
    score = (p.likelihood * p.effect.map(EFFECT_WEIGHT).fillna(0.25)).groupby(p.state).sum()
    if not categories or "Moratorium" in categories:
        m = MOR[MOR.status.isin(["Active", "Proposed"])]
        score = score.add(m.groupby("state").likelihood.sum(), fill_value=0)
    return score.round(2)


def filtered_sites(company, statuses):
    s = SITES[SITES.status.isin(statuses or [])]
    if company and company != ALL:
        s = s[s.id.isin(LINKS[LINKS.entity == company].site_id)]
    return s


def make_map(company, statuses, layers, categories, selected_state):
    layers = layers or []
    fig = go.Figure()
    if "pressure" in layers:
        idx = pressure_index(categories)
        fig.add_trace(go.Choropleth(
            locations=idx.index, z=idx.values, locationmode="USA-states", name="Policy pressure",
            colorscale=[[0, "#f3efe6"], [0.35, "#e7d3bf"], [0.7, "#c98f71"], [1, "#9b4a2e"]],
            marker_line_color="#ffffff", marker_line_width=0.8, zmin=0,
            colorbar={"title": {"text": "Policy<br>pressure", "font": {"size": 10}}, "thickness": 10, "len": 0.45,
                      "x": 1.0, "y": 0.25, "tickfont": {"size": 9}, "outlinewidth": 0},
            hovertemplate="<b>%{location}</b><br>Policy pressure %{z}<extra></extra>"))
    if selected_state:
        fig.add_trace(go.Choropleth(locations=[selected_state], z=[1], locationmode="USA-states", showscale=False,
                                    colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
                                    marker_line_color=NAVY, marker_line_width=2.5, hoverinfo="skip"))
    if "projects" in layers:
        s = filtered_sites(company, statuses)
        for st in ["Operating", "Under Construction", "Planned"]:
            d = s[s.status == st]
            if d.empty:
                continue
            fig.add_trace(go.Scattergeo(
                lon=d.longitude, lat=d.latitude, mode="markers", name=st,
                marker={"size": (d.mw.clip(lower=5) ** 0.5 * (0.5 if company in (None, ALL) else 0.9)).clip(upper=26) + 3,
                        "color": STATUS_COLOR[st], "opacity": 0.7 if st != "Operating" else 0.4,
                        "line": {"width": 0.5, "color": "#ffffff"}},
                customdata=d[["state", "project_name", "developer", "mw", "status", "county"]].fillna("").values,
                hovertemplate="<b>%{customdata[1]}</b><br>%{customdata[2]}<br>%{customdata[5]}, %{customdata[0]}"
                              "<br>%{customdata[4]} · %{customdata[3]:,.0f} MW<extra></extra>"))
    if "moratoria" in layers:
        m = MOR[MOR.status.isin(["Active", "Proposed", "Failed", "Expired"])]
        fig.add_trace(go.Scattergeo(
            lon=m.lon, lat=m.lat, mode="markers", name="Local moratorium",
            marker={"symbol": "x-thin", "size": 6,
                    "line": {"width": 1.6, "color": m.status.map({"Active": NAVY, "Proposed": STEEL}).fillna("#b8b1a8")}},
            customdata=m[["state", "jurisdiction", "status", "scope", "summary"]].values,
            hovertemplate="<b>%{customdata[1]}, %{customdata[0]}</b><br>%{customdata[2]} moratorium · "
                          "%{customdata[3]}<br>%{customdata[4]}<extra></extra>"))
    fig.update_geos(scope="usa", projection_type="albers usa", bgcolor=PAPER, showland=True, landcolor="#f3efe6",
                    showlakes=False, subunitcolor="#ffffff", subunitwidth=0.8, showcountries=False, showframe=False)
    fig.update_layout(height=560, margin={"l": 0, "r": 0, "t": 0, "b": 0}, paper_bgcolor=PAPER,
                      font={"family": "Inter", "color": INK_2, "size": 11}, uirevision="map",
                      hoverlabel={"bgcolor": NAVY, "bordercolor": NAVY, "font": {"color": "#ffffff", "family": "Inter", "size": 11}},
                      legend={"orientation": "h", "y": 0.02, "x": 0.01, "bgcolor": "rgba(248,247,244,.85)",
                              "font": {"size": 10}, "itemsizing": "constant"})
    return fig


def timeline():
    """Policy proliferation: cumulative count of state/local policy actions, by effect."""
    p = POL[POL.state != "US"][["date", "bucket"]].rename(columns={"date": "d"})
    m = MOR[["start", "status"]].rename(columns={"start": "d"}).assign(bucket="delay")[["d", "bucket"]]
    ev = pd.concat([p, m]).dropna()
    ev["d"] = pd.to_datetime(ev.d, errors="coerce")
    ev = ev.dropna().sort_values("d")
    fig = go.Figure()
    order = ["favorable", "compliance", "cost", "delay"]
    labels = {"delay": "Restricts or delays build", "cost": "Raises cost (tariffs, fees)",
              "compliance": "Disclosure/compliance", "favorable": "Supportive"}
    for b in order:
        e = ev[ev.bucket == b]
        if e.empty:
            continue
        cum = e.groupby("d").size().cumsum()
        fig.add_trace(go.Scatter(x=cum.index, y=cum.values, mode="lines", line={"shape": "hv", "width": 2,
                                                                                 "color": EFFECT_COLOR[b]},
                                 name=labels[b], hovertemplate="%{x|%b %Y}: %{y} cumulative<extra></extra>"))
    fig.update_layout(height=230, margin={"l": 36, "r": 10, "t": 6, "b": 28}, paper_bgcolor=BEIGE, plot_bgcolor=BEIGE,
                      font={"family": "Inter", "color": INK_2, "size": 10},
                      legend={"orientation": "h", "y": -0.22, "x": 0, "font": {"size": 10}},
                      xaxis={"gridcolor": RULE, "linecolor": INK_2}, yaxis={"gridcolor": RULE, "zeroline": False})
    return fig


def stat(value, label, sub=None):
    return html.Div(className="stat", children=[html.Div(label, className="stat-label"),
                                                html.Div(value, className="stat-value"),
                                                html.Div(sub, className="stat-sub") if sub else None])


def summary(company, statuses):
    s = filtered_sites(company, statuses)
    pipe = s[s.status.isin(["Planned", "Under Construction"])]
    idx = pressure_index()
    by_state = pipe.groupby("state").mw.sum().sort_values(ascending=False).head(8)
    tot = pipe.mw.sum()
    rows = [html.Div(className="srow head", children=[html.Div("State"), html.Div("Pipeline MW"), html.Div("Share"),
                                                     html.Div("Policy pressure", className="hl")])]
    for st, mw in by_state.items():
        rows.append(html.Div(className="srow", children=[
            html.Div(STATE_NAME.get(st, st)), html.Div(f"{mw:,.0f}"), html.Div(f"{mw / tot:.0%}" if tot else "n/a"),
            html.Div(f"{idx.get(st, 0):.1f}", className="hl")]))
    exposed = pipe[pipe.state.isin(idx[idx >= HIGH_PRESSURE].index)].mw.sum()
    return [
        html.Div(company if company != ALL else "All tracked companies", className="eyebrow"),
        html.Div(className="stats two", children=[
            stat(f"{len(s):,}", "Projects shown", ", ".join(statuses or []) or "none"),
            stat(f"{tot:,.0f}", "Pipeline MW", "planned + under construction"),
            stat(f"{exposed / tot:.0%}" if tot else "n/a", "In high-pressure states",
                 f"pressure index {HIGH_PRESSURE:.0f}+ (top quartile)"),
            stat(f"{pipe.state.nunique()}", "States", "with pipeline"),
        ]),
        html.Div("Where the pipeline sits", className="panel-title mt"),
        html.Div(rows, className="stable"),
    ]


def state_detail(state, company):
    if not state:
        return html.Div("Click a state or project on the map to see its policy record.", className="note")
    p = POL[POL.state == state].sort_values("date", ascending=False)
    m = MOR[MOR.state == state]
    s = filtered_sites(company, ["Planned", "Under Construction"])
    s = s[s.state == state]
    devs = s.groupby(s.developer.fillna("Undisclosed")).mw.sum().sort_values(ascending=False).head(5)
    items = [html.Li([html.Span(className="swatch", style={"background": EFFECT_COLOR[r.bucket]}),
                      html.B(r.title), f" · {r.status} · {r.date}", html.Div(r.summary, className="li-sub")])
             for r in p.itertuples()]
    m = m.assign(_o=m.status.map({"Active": 0, "Proposed": 1}).fillna(2)).sort_values(["_o", "start"],
                                                                               ascending=[True, False])
    items += [html.Li([html.Span(className="swatch x"), html.B(f"{r.jurisdiction} moratorium"),
                       f" · {r.status} · {r.start}", html.Div(r.summary, className="li-sub")]) for r in m.head(40).itertuples()]
    if len(m) > 40:
        items.append(html.Li(f"+ {len(m) - 40} more moratoria in {state}", className="li-sub"))
    return [
        html.Div("Selected state", className="eyebrow"),
        html.H3(STATE_NAME.get(state, state), className="st-title"),
        html.Div(f"{s.mw.sum():,.0f} MW in development here"
                 + (f" for {company}" if company != ALL else "") + f" · policy pressure {pressure_index().get(state, 0):.1f}",
                 className="st-sub"),
        html.Div("Site developers here" + (f" ({company} as developer or tenant)" if company != ALL else ""),
                 className="mini-h") if len(devs) else None,
        html.Div(", ".join(f"{d} ({mw:,.0f} MW)" for d, mw in devs.items()), className="li-sub") if len(devs) else None,
        html.Div(f"Policy record ({len(items)})", className="mini-h"),
        html.Ul(items, className="plist") if items else html.Div("No policy items on file.", className="note"),
    ]


def layout():
    return html.Div(className="map-view", children=[
        html.Div(className="map-head", children=[
            html.Div([html.Div("Siting × policy", className="eyebrow"),
                      html.H1("Where projects are being built, and where policy is pushing back", className="title")]),
        ]),
        html.Div(className="controls", children=[
            html.Div([html.Label("Company", htmlFor="map-company", className="ctl-label"),
                      dcc.Dropdown(id="map-company", options=COMPANIES, value=ALL, clearable=False,
                                   className="ctl-dd")]),
            html.Div([html.Label("Project status", className="ctl-label"),
                      dcc.Checklist(id="map-status", options=list(STATUS_COLOR), inline=True,
                                    value=["Under Construction", "Planned"], className="ctl-check")]),
            html.Div([html.Label("Layers", className="ctl-label"),
                      dcc.Checklist(id="map-layers", inline=True, className="ctl-check",
                                    options=[{"label": "Projects", "value": "projects"},
                                             {"label": "Moratoria", "value": "moratoria"},
                                             {"label": "Policy pressure", "value": "pressure"}],
                                    value=["projects", "moratoria", "pressure"])]),
            html.Div([html.Label("Policy types in pressure index", htmlFor="map-cats", className="ctl-label"),
                      dcc.Dropdown(id="map-cats", options=CATEGORIES, multi=True, placeholder="All restrictive types",
                                   className="ctl-dd wide")]),
        ]),
        html.Div(className="map-grid", children=[
            html.Div(className="map-main", children=[
                dcc.Loading(type="dot", color=STEEL,
                            children=dcc.Graph(id="map-graph", config={"displayModeBar": False, "scrollZoom": False})),
                html.Div(className="panel", children=[
                    html.Div("Policy proliferation", className="panel-title"),
                    html.Div("Cumulative state and local actions on file, by effect on data-center development",
                             className="panel-sub"),
                    dcc.Graph(figure=timeline(), config={"displayModeBar": False})]),
            ]),
            html.Div(className="map-side", children=[
                html.Div(id="map-summary"),
                html.Div(id="map-state", className="state-box"),
                html.Div("Policy records: Crux Data Center Tracker export (882 moratoria, 60 state/federal items) plus reviewed Policy Scout results. "
                         "Pressure index = likelihood-weighted restrictive items; see methodology.", className="fine"),
            ]),
        ]),
        dcc.Store(id="map-sel-state"),
    ])


def register(app):
    @app.callback(Output("map-graph", "figure"), Output("map-summary", "children"),
                  Input("map-company", "value"), Input("map-status", "value"), Input("map-layers", "value"),
                  Input("map-cats", "value"), Input("map-sel-state", "data"))
    def _update(company, statuses, layers, cats, sel):
        return make_map(company, statuses, layers, cats, sel), summary(company, statuses)

    @app.callback(Output("map-sel-state", "data"), Input("map-graph", "clickData"), State("map-sel-state", "data"),
                  prevent_initial_call=True)
    def _click(click, current):
        if not click:
            return no_update
        pt = click["points"][0]
        st = pt.get("location") or (pt.get("customdata") or [None])[0]
        return None if st == current else st  # clicking the same state again clears it

    @app.callback(Output("map-state", "children"), Input("map-sel-state", "data"), Input("map-company", "value"))
    def _detail(state, company):
        return state_detail(state, company)

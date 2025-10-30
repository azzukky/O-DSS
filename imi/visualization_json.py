#!/usr/bin/env python3
# live_ul_metrics.py
# Tail a growing JSON array, plot UL metrics with all original features

import time, json, queue, threading, os
from pathlib import Path
from typing import List, Dict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# -------------------------- CONFIG --------------------------
FILE_PATH = "/tmp/enb_odss_log.json"   # <-- change if needed
TIME_WINDOW_S = 60
REFRESH_MS    = 250
Y_BIT_MAX     = 30
Y_BLR_MAX     = 100

# Smoothing
BITRATE_WIN       = 30
BLER_WIN          = 20
USE_EMA_FOR_BITRATE = True

# Zero handling
ZERO_IS_MISSING        = True
BITRATE_ZERO_THRESHOLD = 0.5   # Mbps
FFILL_S                = 1.0    # seconds

st.set_page_config(page_title="UL Metrics Live", layout="wide")

# -------------------------- SESSION STATE --------------------------
if "q" not in st.session_state:
    st.session_state.q = queue.Queue()
if "series" not in st.session_state:
    st.session_state.series: Dict[str, Dict[str, List[float]]] = {}
if "count" not in st.session_state:
    st.session_state.count = 0

# -------------------------- HELPERS --------------------------
def to_mbps(x: float) -> float:
    if x is None: return 0.0
    try: x = float(x)
    except: return 0.0
    return x / 1_000_000.0 if x >= 1e6 else x

def to_percent(x: float) -> float:
    if x is None: return 0.0
    try: x = float(x)
    except: return 0.0
    return x if x > 1.0 else x * 100.0

def extract_ul_from_record(obj) -> List[dict]:
    out = []
    if obj.get("type") != "metrics":
        return out
    ts = float(obj.get("timestamp", time.time()))
    for cell in obj.get("cell_list", []):
        cc = cell.get("cell_container", {}) or {}
        for ue in cc.get("ue_list", []):
            uc = ue.get("ue_container", {}) or {}
            rnti = uc.get("ue_rnti", "unknown")
            bitrate = to_mbps(uc.get("ul_bitrate", 0.0))
            bler = to_percent(uc.get("ul_bler", 0.0))
            mcs = float(uc.get("ul_mcs", 0.0) or 0.0)
            out.append({
                "timestamp": ts,
                "ue_id": str(rnti),
                "ul_bitrate_mbps": bitrate,
                "ul_bler_percent": bler,
                "ul_mcs": mcs,
            })
            print(f"  → UE {rnti}: {bitrate:.2f} Mbps | BLER {bler:.1f}% | MCS {mcs}")
    return out

# -------------------------- TAILER --------------------------
# -------------------------- TAILER (FIXED) --------------------------
def tail_file_forever():
    path = Path(FILE_PATH)
    if not path.exists():
        st.error(f"File not found: {FILE_PATH}")
        return

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(0, os.SEEK_END)
        buffer = ""

        while True:
            line = f.readline()
            if line:
                buffer += line
            else:
                time.sleep(0.1)
                # Detect file rotation
                try:
                    cur_ino = os.fstat(f.fileno()).st_ino
                    cur_pos = f.tell()
                    st = os.stat(path)
                    if st.st_ino != cur_ino or cur_pos > st.st_size:
                        f.close()
                        f = open(path, "r", encoding="utf-8", errors="ignore")
                        f.seek(0, os.SEEK_END)
                        buffer = ""
                except FileNotFoundError:
                    time.sleep(0.5)
                continue

            # Look for potential top-level objects: must start with {"type":"metrics"
            start_idx = buffer.find('{"type":"metrics"')
            while start_idx != -1:
                # Find the matching closing brace for this object
                brace_count = 0
                end_idx = start_idx
                while end_idx < len(buffer):
                    if buffer[end_idx] == '{':
                        brace_count += 1
                    elif buffer[end_idx] == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            break
                    end_idx += 1

                if brace_count != 0:
                    # Not complete yet
                    break

                candidate = buffer[start_idx:end_idx+1]
                candidate = candidate.rstrip(',').strip()  # remove trailing comma

                try:
                    obj = json.loads(candidate)
                    ts = obj.get("timestamp")
                    print(f"PARSED: {ts} | UE: {obj.get('cell_list', [{}])[0].get('cell_container', {}).get('ue_list', [{}])[0].get('ue_container', {}).get('ue_rnti')}")
                    
                    for sample in extract_ul_from_record(obj):
                        sample["timestamp"] = time.time()
                        st.session_state.q.put(sample)
                    
                    # Remove processed object
                    buffer = buffer[end_idx+1:]
                except json.JSONDecodeError as e:
                    print(f"JSON error: {e} | candidate: {candidate[:200]}...")
                    buffer = buffer[end_idx+1:]  # skip bad part
                    break

                # Look for next object
                start_idx = buffer.find('{"type":"metrics"')

            # If no more objects, keep buffer for next read
# start background tailer
if "tail_started" not in st.session_state:
    st.session_state.tail_started = True
    threading.Thread(target=tail_file_forever, daemon=True).start()

# -------------------------- UI --------------------------
st.title("O-DSS Uplink Metrics — Live Tail")

c1, c2, c3 = st.columns(3)
bit_ph  = c1.empty()
bler_ph = c2.empty()
mcs_ph  = c3.empty()
dbg = st.empty()

# ---- drain queue ----
while True:
    try:
        s = st.session_state.q.get_nowait()
        ue = s["ue_id"]
        if ue not in st.session_state.series:
            st.session_state.series[ue] = {"t": [], "bitrate": [], "bler": [], "mcs": []}
        ser = st.session_state.series[ue]
        ser["t"].append(s["timestamp"])
        ser["bitrate"].append(s["ul_bitrate_mbps"])
        ser["bler"].append(s["ul_bler_percent"])
        ser["mcs"].append(s["ul_mcs"])
        st.session_state.count += 1
    except queue.Empty:
        break

# ---- figure factory ----
def mk_fig(title, ytitle, yrange):
    fig = go.Figure()
    fig.update_layout(
        title=title, xaxis_title="Time (s)", yaxis_title=ytitle,
        yaxis_range=yrange, margin=dict(l=40,r=10,t=40,b=40),
        legend=dict(orientation="h", y=-0.2)
    )
    return fig

bit_fig  = mk_fig("UL Throughput", "Mbps", (0, Y_BIT_MAX))
bler_fig = mk_fig("UL BLER", "%", (0, Y_BLR_MAX))
mcs_fig  = mk_fig("UL MCS", "Index", (0, 28))

now = time.time()

for ue, s in st.session_state.series.items():
    if not s["t"]: continue

    # ---- trim old data ----
    cutoff = now - TIME_WINDOW_S
    first = next((i for i, t in enumerate(s["t"]) if t >= cutoff), len(s["t"]))
    for k in ["t","bitrate","bler","mcs"]:
        s[k] = s[k][first:]
    if not s["t"]: continue

    t_rel = np.array(s["t"]) - s["t"][0]

    # ---- BITRATE (zero → NaN → ffill → EMA/SMA) ----
    vals = pd.Series(s["bitrate"])
    dt = np.median(np.diff(s["t"])) if len(s["t"]) >= 2 else 0.25
    dt = max(dt, 1e-3)

    if ZERO_IS_MISSING:
        vals = vals.mask(vals <= BITRATE_ZERO_THRESHOLD, np.nan)
        max_gap = max(1, int(FFILL_S / dt))
        vals = vals.ffill(limit=max_gap)

    if USE_EMA_FOR_BITRATE:
        y_bit = vals.ewm(span=BITRATE_WIN, adjust=False, min_periods=1).mean()
    else:
        y_bit = vals.rolling(window=BITRATE_WIN, min_periods=1).mean()

    bit_fig.add_trace(go.Scatter(x=t_rel, y=y_bit, mode="lines",
                                 name=f"UE {ue}", line=dict(width=3)))

    # ---- BLER (SMA) ----
    y_bler = pd.Series(s["bler"]).rolling(window=BLER_WIN, min_periods=1).mean()
    bler_fig.add_trace(go.Scatter(x=t_rel, y=y_bler, mode="lines",
                                  name=f"UE {ue}", line=dict(width=3)))

    # ---- MCS (raw) ----
    mcs_fig.add_trace(go.Scatter(x=t_rel, y=s["mcs"], mode="lines",
                                 name=f"UE {ue}", line=dict(width=2)))

# lock X-axis
for fig in [bit_fig, bler_fig, mcs_fig]:
    fig.update_layout(xaxis_range=[0, TIME_WINDOW_S])
bit_fig.update_yaxes(fixedrange=True)

# render
bit_ph.plotly_chart(bit_fig,  use_container_width=True)
bler_ph.plotly_chart(bler_fig, use_container_width=True)
mcs_ph.plotly_chart(mcs_fig,  use_container_width=True)

# debug line
dbg.write(
    f"Samples: {st.session_state.count} | UEs: {list(st.session_state.series.keys())} | "
    f"Window: {TIME_WINDOW_S}s | Refresh: {REFRESH_MS}ms | "
    f"BitMA: {'EMA' if USE_EMA_FOR_BITRATE else 'SMA'}{BITRATE_WIN} | BLER_MA: {BLER_WIN} | "
    f"Zero→NaN ≤{BITRATE_ZERO_THRESHOLD}Mbps | FFill≤{FFILL_S}s"
)

st_autorefresh(interval=REFRESH_MS, key="refresh")
#!/usr/bin/env python3
# ul_live.py — Live UL metrics from Redis/SyncStorage only

import time, queue, threading
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import json
from ricsdl.syncstorage import SyncStorage
from PIL import Image

# ───────────────────────── Config ─────────────────────────
st.set_page_config(page_title="UL Metrics Replay (Bitrate / BLER / MCS)", layout="wide")

# UI / plotting settings
TIME_WINDOW_S     = 40     # visible chart window (seconds)
REFRESH_MS        = 1000   # UI refresh cadence (ms)
Y_BIT_MAX         = 40     # fixed Y range for bitrate (Mbps)
Y_BLR_MAX         = 100    # BLER axis in percent

# Moving-average windows (in SAMPLES)
BITRATE_WIN       = 30     # MA window for bitrate
BLER_WIN          = 20     # MA window for BLER
MCS_WIN           = 3      # MA window for MCS

# Redis/SDL polling
SDL_NAMESPACE      = "Kpms"
SDL_KEY_PATTERN    = "kpm_*"
POLL_INTERVAL_S    = 1.0    # how often to poll SDL
NUM_SAMPLES_TO_USE = 1      # read last N kpm_* keys per poll

# KPM field names (per your IMI schema)
KPM_BITRATE_FIELD  = "rx_bitrate"           # typically bps
KPM_BLER_FIELD     = "rx_block_error_rate"  # fraction or percent
KPM_MCS_FIELD      = "ul_mcs"
KPM_UE_ID_FIELD    = "ue_rnti"

# Logo path
LOGO_PATH = "nextglogo.png"

# ───────────────────── Helpers / Normalizers ─────────────────────
def to_mbps(x: float) -> float:
    if x is None: return 0.0
    try: x = float(x)
    except Exception: return 0.0
    return x / 1_000_000.0 if x >= 1e6 else x

def to_percent(x: float) -> float:
    if x is None: return 0.0
    try: x = float(x)
    except Exception: return 0.0
    return x if x > 1.0 else x * 100.0

def load_logo_on_white(path: str, bg=(255, 255, 255)):
    """
    Load logo and composite onto a white background to ensure the
    white card shows even on dark themes.
    """
    try:
        img = Image.open(path).convert("RGBA")
        bg_img = Image.new("RGBA", img.size, bg + (255,))
        bg_img.paste(img, (0, 0), img)
        return bg_img.convert("RGB")
    except Exception:
        return None

# ───────────────────── Producer (Redis only) ─────────────────────
def producer_from_redis(q: queue.Queue):
    """Continuously pull latest KPMs from SDL and push UL metrics."""
    sdl = SyncStorage()
    while True:
        try:
            keys = sdl.find_keys(SDL_NAMESPACE, SDL_KEY_PATTERN)
            if keys:
                sorted_keys = sorted(keys, key=lambda x: int(x.split('_')[1]))[-NUM_SAMPLES_TO_USE:]
                kv = sdl.get(SDL_NAMESPACE, set(sorted_keys))
                now_ts = time.time()

                for _, value_bytes in kv.items():
                    if not value_bytes:
                        continue
                    rec = json.loads(value_bytes.decode("utf-8"))
                    for idx, ue in enumerate(rec.get("ue_metrics", [])):
                        bitrate_bps = ue.get(KPM_BITRATE_FIELD, 0.0)
                        bler_raw    = ue.get(KPM_BLER_FIELD, 0.0)
                        mcs         = ue.get(KPM_MCS_FIELD, 0.0)
                        ue_id       = str(ue.get(KPM_UE_ID_FIELD, idx))
                        if not any([bitrate_bps, bler_raw, mcs]):
                            continue
                        q.put({
                            "timestamp": now_ts,
                            "ue_id": ue_id,
                            "ul_bitrate_mbps": to_mbps(bitrate_bps),
                            "ul_bler_percent": to_percent(bler_raw),
                            "ul_mcs": float(mcs) or 0.0,
                        })
        except Exception:
            time.sleep(0.5)

        time.sleep(POLL_INTERVAL_S)

# ───────────────────── Session state ─────────────────────────────
if "q" not in st.session_state:
    st.session_state.q = queue.Queue()

# series[ue] = {"t": [], "bitrate": [], "bler": [], "mcs": []}
if "series" not in st.session_state:
    st.session_state.series: Dict[str, Dict[str, List[float]]] = {}

if "count" not in st.session_state:
    st.session_state.count = 0

# start background producer once
if "bg_started" not in st.session_state:
    st.session_state.bg_started = True
    threading.Thread(target=producer_from_redis, args=(st.session_state.q,), daemon=True).start()

# ─────────────── Header: Title (left) + Logo (right) ─────────────
# header with title (left) + logo (right)
hdr_left, hdr_right = st.columns([0.65, 0.35])
with hdr_left:
    st.title("Open Dynamic Spectrum Sharing (O-DSS) Framework")
with hdr_right:
    logo_img = load_logo_on_white(LOGO_PATH)
    if logo_img is None:
        st.warning(f"Logo not found or failed to load: {LOGO_PATH}")
    else:
        # OLD (causes warning):
        # st.image(logo_img, use_column_width=True)

        # NEW:
        st.image(logo_img, use_container_width=True)   # fills the right column
        # (Optional) If you prefer a fixed size instead of filling the column:
        # st.image(logo_img, width=520)


st.write("")  # small spacer below header

# ───────────────────── UI / Plots ───────────────────────────────
# desired order: Bitrate (L) → BLER (M) → MCS (R)
c1, c2, c3 = st.columns(3)
bit_ph, bler_ph, mcs_ph = c1.empty(), c2.empty(), c3.empty()
dbg = st.empty()

# Drain queue → append into per-UE lists
while True:
    try:
        s = st.session_state.q.get_nowait()
        ue = s["ue_id"]
        if ue not in st.session_state.series:
            st.session_state.series[ue] = {"t": [], "bitrate": [], "bler": [], "mcs": []}
        series = st.session_state.series[ue]
        series["t"].append(s["timestamp"])
        series["bitrate"].append(s["ul_bitrate_mbps"])
        series["bler"].append(s["ul_bler_percent"])
        series["mcs"].append(s["ul_mcs"])
        st.session_state.count += 1
    except queue.Empty:
        break

# helper: figure factory
def mk_fig(title: str, ytitle: str, y_range: Tuple[float, float] | Tuple[float, None]):
    fig = go.Figure()
    fig.update_layout(
        title=title,
        xaxis_title="Time (s)",
        yaxis_title=ytitle,
        yaxis_range=y_range,
        margin=dict(l=40, r=10, t=40, b=40),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig

bit_fig  = mk_fig("Throughput (UL)", "Mbps", (0, Y_BIT_MAX))
bler_fig = mk_fig("BLER (UL)", "Percent", (0, Y_BLR_MAX))
mcs_fig  = mk_fig("MCS (UL)", "MCS Index", (0, 28))

# Build traces per UE
now = time.time()
for ue, s in st.session_state.series.items():
    if not s["t"]:
        continue

    # trim lists to TIME_WINDOW_S (left side)
    cutoff = now - TIME_WINDOW_S
    first = 0
    ts = s["t"]
    while first < len(ts) and ts[first] < cutoff:
        first += 1
    if first > 0:
        s["t"]       = s["t"][first:]
        s["bitrate"] = s["bitrate"][first:]
        s["bler"]    = s["bler"][first:]
        s["mcs"]     = s["mcs"][first:]

    if not s["t"]:
        continue

    # relative time axis
    t0 = s["t"][0]
    rel_t = np.asarray(s["t"], dtype=float) - float(t0)

    # ---- Smoothed Bitrate (MA-30) ----
    y_ma_bit = pd.Series(s["bitrate"]).rolling(window=BITRATE_WIN, min_periods=1).mean().to_numpy()
    bit_fig.add_trace(go.Scatter(x=rel_t, y=y_ma_bit, mode="lines",
                                 name=f"UE {ue} MA{BITRATE_WIN}", line=dict(width=3)))

    # ---- Smoothed BLER (MA-20) ----
    y_ma_bler = pd.Series(s["bler"]).rolling(window=BLER_WIN, min_periods=1).mean().to_numpy()
    bler_fig.add_trace(go.Scatter(x=rel_t, y=y_ma_bler, mode="lines",
                                  name=f"UE {ue} MA{BLER_WIN}", line=dict(width=3)))

    # ---- Smoothed MCS (MA-3) ----
    y_ma_mcs = pd.Series(s["mcs"]).rolling(window=MCS_WIN, min_periods=1).mean().to_numpy()
    mcs_fig.add_trace(go.Scatter(x=rel_t, y=y_ma_mcs, mode="lines",
                                 name=f"UE {ue} MA{MCS_WIN}", line=dict(width=2)))

# lock X window & bitrate Y range
bit_fig.update_layout(xaxis_range=[0, TIME_WINDOW_S], yaxis=dict(range=[0, Y_BIT_MAX], fixedrange=True))
bler_fig.update_layout(xaxis_range=[0, TIME_WINDOW_S])
mcs_fig.update_layout(xaxis_range=[0, TIME_WINDOW_S])

# render
bit_ph.plotly_chart(bit_fig,  use_container_width=True)
bler_ph.plotly_chart(bler_fig, use_container_width=True)
mcs_ph.plotly_chart(mcs_fig,  use_container_width=True)

# dbg.write(
#     f"samples_total={st.session_state.count} | UEs={list(st.session_state.series.keys())} | "
#     f"window={TIME_WINDOW_S}s | refresh={REFRESH_MS}ms | "
#     f"MA(bit)={BITRATE_WIN} MA(bler)={BLER_WIN} MA(mcs)={MCS_WIN}"
# )

# periodic refresh
st_autorefresh(interval=REFRESH_MS, key="ul-live-refresh")

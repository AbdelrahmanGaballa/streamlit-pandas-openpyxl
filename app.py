import streamlit as st
import pandas as pd
import base64
import re
from io import BytesIO
from datetime import date

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(page_title="DFU-VA | Payslip Analysis", layout="wide")

# -----------------------------
# Helpers
# -----------------------------
def img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def safe_lower(x) -> str:
    return str(x).strip().lower()

def parse_duration_to_hours(val) -> float:
    """Converts strings like '42 hours 35 min.' or '9 min. 44 s.' to hours float."""
    if pd.isna(val):
        return 0.0
    s = str(val).strip().lower()
    if s in ("-", "na", "n/a", ""):
        return 0.0

    hours = mins = secs = 0
    h = re.search(r"(\d+)\s*hour", s)
    m = re.search(r"(\d+)\s*min", s)
    sec = re.search(r"(\d+)\s*s", s)

    if h: hours = int(h.group(1))
    if m: mins = int(m.group(1))
    if sec: secs = int(sec.group(1))

    return float(hours + mins / 60.0 + secs / 3600.0)

def pick_sheet(xlsx, preferred_name: str):
    try:
        xl = pd.ExcelFile(xlsx)
        return preferred_name if preferred_name in xl.sheet_names else xl.sheet_names[0]
    except Exception:
        return 0

# -----------------------------
# Branding / CSS
# -----------------------------
DFU_RED = "#E30613"
BG = "#FAFAFB"
CARD = "#FFFFFF"
TEXT = "#111827"
MUTED = "#6B7280"
BORDER = "rgba(17,24,39,0.08)"

try:
    LOGO_B64 = img_to_base64("logo.png")
except Exception:
    LOGO_B64 = None

st.markdown(f"""
<style>
/* App background */
.stApp {{
  background: {BG};
}}

/* Hide Streamlit default header spacing */
.block-container {{
  padding-top: 1.1rem;
  max-width: 1180px;
}}

/* Remove extra top padding */
header[data-testid="stHeader"] {{
  background: transparent;
}}

/* Sidebar styling */
section[data-testid="stSidebar"] {{
  background: #ffffff;
  border-right: 1px solid {BORDER};
}}

/* Buttons */
.stDownloadButton button, .stButton button {{
  border-radius: 12px !important;
  border: 1px solid {BORDER} !important;
  padding: 0.55rem 0.9rem !important;
  font-weight: 700 !important;
}}
.stDownloadButton button {{
  background: {DFU_RED} !important;
  color: white !important;
  border: none !important;
}}
.stDownloadButton button:hover {{
  filter: brightness(0.95);
}}

/* Inputs */
div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {{
  border-radius: 12px !important;
}}

/* Card */
.card {{
  background: {CARD};
  border: 1px solid {BORDER};
  border-radius: 18px;
  padding: 16px 16px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.05);
}}
.card-title {{
  font-size: 14px;
  font-weight: 800;
  color: {TEXT};
  margin: 0 0 10px 0;
}}
.small {{
  color: {MUTED};
  font-size: 12px;
}}

/* Top bar */
.topbar {{
  background: linear-gradient(90deg, rgba(227,6,19,0.12), rgba(227,6,19,0.04));
  border: 1px solid {BORDER};
  border-radius: 20px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}}
.brand {{
  display:flex;
  align-items:center;
  gap: 12px;
}}
.brand h1 {{
  font-size: 22px;
  margin: 0;
  color: {TEXT};
  font-weight: 900;
}}
.brand p {{
  margin: 0;
  color: {MUTED};
  font-size: 12px;
}}
.badge {{
  background: {DFU_RED};
  color: white;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
}}
hr {{
  border: none;
  border-top: 1px solid {BORDER};
  margin: 14px 0;
}}
</style>
""", unsafe_allow_html=True)

# -----------------------------
# Top bar
# -----------------------------
logo_html = f'<img src="data:image/png;base64,{LOGO_B64}" style="height:38px;width:auto;" />' if LOGO_B64 else ""
st.markdown(f"""
<div class="topbar">
  <div class="brand">
    {logo_html}
    <div>
      <h1>Payslip Analysis Report</h1>
      <p>Upload two files → choose agent + dates → export report</p>
    </div>
  </div>
  <div class="badge">DFU • Red/White Theme</div>
</div>
""", unsafe_allow_html=True)

# -----------------------------
# Sidebar controls (cleaner layout)
# -----------------------------
st.sidebar.markdown("### Upload Files")
payslip_file = st.sidebar.file_uploader("Payslip Draft (Excel)", type=["xlsx", "xls"], key="payslip")
leads_file = st.sidebar.file_uploader("Leads Bank (Excel)", type=["xlsx", "xls"], key="leads")

st.sidebar.markdown("### Rules")
cutoff_hour = st.sidebar.number_input("Cutoff hour (Cairo)", min_value=0, max_value=23, value=7)
leads_target_per_day = st.sidebar.number_input("Lead target / day", min_value=0, max_value=50, value=2)

with st.sidebar.expander("Optional payroll inputs"):
    hours_target_per_day = st.number_input("Hours target / day", min_value=0.0, max_value=24.0, value=8.0, step=0.5)
    hourly_rate = st.number_input("Hourly rate", min_value=0.0, max_value=1000.0, value=0.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.caption("Tip: If timestamps are before 7AM, they count as the previous day (timezone rule).")

if not payslip_file or not leads_file:
    st.info("Upload **Payslip Draft** and **Leads Bank** from the sidebar to start.")
    st.stop()

# -----------------------------
# Load data
# -----------------------------
payslip_sheet = pick_sheet(payslip_file, "Trial 1")
leads_sheet = pick_sheet(leads_file, "Leads Bank")

pay = pd.read_excel(payslip_file, sheet_name=payslip_sheet)
leads = pd.read_excel(leads_file, sheet_name=leads_sheet)

# Validate minimal columns
if "Name" not in pay.columns or "Day/date" not in pay.columns:
    st.error("Payslip file must contain columns: **Name**, **Day/date**")
    st.stop()

required_leads_cols = ["Timestamp", "Agent Name", "Lead Result", "Lead Status"]
missing = [c for c in required_leads_cols if c not in leads.columns]
if missing:
    st.error(f"Leads file is missing: {', '.join(missing)}")
    st.stop()

# Prepare payslip daily rows
pay_daily = pay[pay["Day/date"] != "-"].copy()
pay_daily["work_date"] = pd.to_datetime(pay_daily["Day/date"], errors="coerce").dt.date

min_d = pay_daily["work_date"].min()
max_d = pay_daily["work_date"].max()
if pd.isna(min_d) or pd.isna(max_d):
    min_d, max_d = date.today(), date.today()

# -----------------------------
# Agent + date controls (main page)
# -----------------------------
controls = st.container()
with controls:
    cA, cB = st.columns([1, 1])
    agents_pay = sorted(pay_daily["Name"].dropna().astype(str).str.strip().unique().tolist())
    agent_name = cA.selectbox("Agent Name", agents_pay)

    date_range = cB.date_input(
        "Date Range",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max_d,
    )

start_date, end_date = date_range
if start_date > end_date:
    st.error("Start date must be before end date.")
    st.stop()

# Match agent to leads agent (simple)
lead_agents = sorted(leads["Agent Name"].dropna().astype(str).unique().tolist())
first2 = " ".join(str(agent_name).split()[:2]).strip().lower()
auto_matches = [a for a in lead_agents if safe_lower(a).startswith(first2)]
default_lead_agent = auto_matches[0] if auto_matches else (lead_agents[0] if lead_agents else "")

lead_agent_choice = st.selectbox(
    "Leads Bank Agent Name (match)",
    options=lead_agents,
    index=lead_agents.index(default_lead_agent) if default_lead_agent in lead_agents else 0,
)

st.markdown("<hr/>", unsafe_allow_html=True)

# -----------------------------
# Compute hours
# -----------------------------
pay_f = pay_daily[
    (pay_daily["Name"].astype(str).str.strip() == str(agent_name).strip())
    & (pay_daily["work_date"] >= start_date)
    & (pay_daily["work_date"] <= end_date)
].copy()

working_days = int(pay_f["work_date"].nunique())

logged_hours = float(pay_f["Logged Time"].apply(parse_duration_to_hours).sum()) if "Logged Time" in pay_f.columns else 0.0
payable_hours = float(pay_f["Payable (t)"].apply(parse_duration_to_hours).sum()) if "Payable (t)" in pay_f.columns else logged_hours
unpayable_hours = float(pay_f["Unpayable (t)"].apply(parse_duration_to_hours).sum()) if "Unpayable (t)" in pay_f.columns else 0.0

agent_id = str(pay_f["User ID"].dropna().iloc[0]) if "User ID" in pay_f.columns and len(pay_f["User ID"].dropna()) else ""
login_id = str(pay_f["Login ID"].dropna().iloc[0]) if "Login ID" in pay_f.columns and len(pay_f["Login ID"].dropna()) else ""

# -----------------------------
# Compute leads with cutoff rule
# business day = Timestamp - cutoff_hour
# payable lead = Qualified + Pushed to Client
# -----------------------------
leads_ts = pd.to_datetime(leads["Timestamp"], errors="coerce")
leads2 = leads[leads_ts.notna()].copy()
shifted = pd.to_datetime(leads_ts[leads_ts.notna()]) - pd.Timedelta(hours=cutoff_hour)
leads2["work_date"] = shifted.dt.date

leads_f = leads2[
    (leads2["Agent Name"].astype(str) == str(lead_agent_choice))
    & (leads2["work_date"] >= start_date)
    & (leads2["work_date"] <= end_date)
].copy()

qualified_leads = int((leads_f["Lead Result"].apply(safe_lower) == "qualified").sum())
disqualified_leads = int((leads_f["Lead Result"].apply(safe_lower) == "disqualified").sum())
callbacks = int((leads_f["Lead Result"].apply(safe_lower) == "call back").sum())

above_market = int((leads_f["Case"].apply(safe_lower) == "above market value").sum()) if "Case" in leads_f.columns else 0

payable_leads = int((
    (leads_f["Lead Result"].apply(safe_lower) == "qualified")
    & (leads_f["Lead Status"].apply(safe_lower) == "pushed to client")
).sum())

leads_target = working_days * int(leads_target_per_day)
target_met = (payable_leads >= leads_target)

hours_target = working_days * float(hours_target_per_day)
total_pay = payable_hours * float(hourly_rate) if hourly_rate and hourly_rate > 0 else None

# -----------------------------
# UI: Cards + Metrics
# -----------------------------
top_metrics = st.columns(4)
top_metrics[0].metric("Working Days", working_days)
top_metrics[1].metric("Payable Leads", payable_leads)
top_metrics[2].metric("Lead Target", leads_target)
top_metrics[3].metric("Target Met?", "YES ✅" if target_met else "NO ❌")

grid1 = st.columns(2)
with grid1[0]:
    st.markdown('<div class="card"><p class="card-title">Lead Summary</p>', unsafe_allow_html=True)
    lead_summary = pd.DataFrame({
        "Metric": ["Qualified Leads", "Disqualified Leads", "Call Backs", "Above Market Value", "Payable Leads (Qualified + Pushed)"],
        "Value": [qualified_leads, disqualified_leads, callbacks, above_market, payable_leads]
    })
    st.dataframe(lead_summary, use_container_width=True, hide_index=True)
    st.markdown('<p class="small">Rule: Payable Lead = Qualified + Pushed to Client. Cutoff: before '
                f'{cutoff_hour}:00 counts as previous day.</p></div>', unsafe_allow_html=True)

with grid1[1]:
    st.markdown('<div class="card"><p class="card-title">Hours Summary</p>', unsafe_allow_html=True)
    hcols = st.columns(3)
    hcols[0].metric("Payable Hours", f"{payable_hours:.2f}")
    hcols[1].metric("Logged Hours", f"{logged_hours:.2f}")
    hcols[2].metric("Unpayable Hours", f"{unpayable_hours:.2f}")
    st.markdown(f'<p class="small">Hours Target (optional): {hours_target:.2f} • '
                f'Hourly Rate: {"-" if not hourly_rate else f"{hourly_rate:.2f}"}</p></div>', unsafe_allow_html=True)

st.markdown("<hr/>", unsafe_allow_html=True)

st.markdown('<div class="card"><p class="card-title">Agent Payroll Snapshot</p>', unsafe_allow_html=True)
snapshot = pd.DataFrame({
    "Field": [
        "Agent ID", "Agent Name", "Login ID",
        "Date Range", "Working Days",
        "Leads Target (2/day)", "Leads Achieved (Payable)", "Target Met?",
        "Hours Target", "Hours Achieved (Payable)", "Unpayable Hours",
        "Hourly Rate", "Grand Total"
    ],
    "Value": [
        agent_id, agent_name, login_id,
        f"{start_date} → {end_date}", working_days,
        leads_target, payable_leads, "YES ✅" if target_met else "NO ❌",
        f"{hours_target:.2f}", f"{payable_hours:.2f}", f"{unpayable_hours:.2f}",
        "-" if not hourly_rate else f"{hourly_rate:.2f}",
        "-" if total_pay is None else f"{total_pay:.2f}"
    ]
})
st.dataframe(snapshot, use_container_width=True, hide_index=True)
st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------
# Tabs for details + export
# -----------------------------
tab1, tab2, tab3 = st.tabs(["Details (optional)", "Leads Rows", "Download"])

with tab1:
    st.markdown('<div class="card"><p class="card-title">Payslip Rows (selected agent/date range)</p>', unsafe_allow_html=True)
    st.dataframe(pay_f, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="card"><p class="card-title">Lead Rows (selected agent/date range)</p>', unsafe_allow_html=True)
    st.dataframe(leads_f, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="card"><p class="card-title">Download Report</p>', unsafe_allow_html=True)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        meta = pd.DataFrame({
            "Key": ["Start Date", "End Date", "Cutoff Hour", "Payslip Sheet", "Leads Sheet", "Payslip Agent", "Leads Agent"],
            "Value": [str(start_date), str(end_date), str(cutoff_hour), str(payslip_sheet), str(leads_sheet), str(agent_name), str(lead_agent_choice)]
        })
        meta.to_excel(writer, index=False, sheet_name="Report", startrow=0)
        lead_summary.to_excel(writer, index=False, sheet_name="Report", startrow=10)
        snapshot.to_excel(writer, index=False, sheet_name="Report", startrow=20)
        pay_f.to_excel(writer, index=False, sheet_name="Payslip Rows")
        leads_f.to_excel(writer, index=False, sheet_name="Lead Rows")

    output.seek(0)
    st.download_button(
        "Download Excel Report",
        data=output,
        file_name="Payslip_Analysis_Report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.markdown('<p class="small">This export includes the summary + detailed rows for auditing.</p></div>', unsafe_allow_html=True)

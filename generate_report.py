import pandas as pd

LEADS_PATH = "Leads Bank.xlsx"
PAYSLIP_PATH = "Payslip Draft.xlsx"
OUTPUT_PATH = "Payslip_Report.xlsx"

def norm(s: str) -> str:
    return str(s).strip().lower()

def load_qualified_pushed_leads(leads_path: str) -> pd.DataFrame:
    df = pd.read_excel(leads_path, sheet_name="Leads Bank")

    # Drop the empty columns like " ", "  2", ...
    drop_cols = [c for c in df.columns if str(c).strip() == "" or str(c).strip().isdigit()]
    df = df.drop(columns=drop_cols, errors="ignore")

    # Filter: Qualified + Pushed to Client
    df = df[
        (df["Lead Result"].astype(str).str.strip().str.lower() == "qualified")
        & (df["Lead Status"].astype(str).str.strip().str.lower() == "pushed to client")
    ].copy()

    # Apply your cutoff rule:
    # Anything before 07:00 counts as previous day -> subtract 7 hours then take date
    df["business_date"] = (pd.to_datetime(df["Timestamp"]) - pd.Timedelta(hours=7)).dt.date

    # Map agent name to a short name like "Rana Mohsen", "Mariam Mohamed"
    df["short_name"] = df["Agent Name"].astype(str).apply(lambda x: " ".join(x.split()[:2]))

    counts = (
        df.groupby(["short_name", "business_date"])
          .size()
          .reset_index(name="Qualified Leads (Pushed)")
    )
    return counts

def build_report(payslip_path: str, lead_counts: pd.DataFrame) -> pd.DataFrame:
    trial = pd.read_excel(payslip_path, sheet_name="Trial 1")

    # Separate daily rows vs total rows (Day/date == "-")
    daily = trial[trial["Day/date"] != "-"].copy()
    totals = trial[trial["Day/date"] == "-"].copy()

    daily["date"] = pd.to_datetime(daily["Day/date"]).dt.date
    daily["Name_key"] = daily["Name"].astype(str).str.strip()

    # Merge leads into the daily rows
    daily = daily.merge(
        lead_counts,
        left_on=["Name_key", "date"],
        right_on=["short_name", "business_date"],
        how="left",
    )

    daily["Qualified Leads (Pushed)"] = daily["Qualified Leads (Pushed)"].fillna(0).astype(int)
    daily = daily.drop(columns=["short_name", "business_date"], errors="ignore")

    # Put daily + totals back together
    out = pd.concat([daily, totals], ignore_index=True)

    return out

def main():
    lead_counts = load_qualified_pushed_leads(LEADS_PATH)
    report_trial = build_report(PAYSLIP_PATH, lead_counts)

    # Write a new Excel file with a new sheet "Trial 1 (Auto)"
    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        report_trial.to_excel(writer, index=False, sheet_name="Trial 1 (Auto)")

    print(f"Saved: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()

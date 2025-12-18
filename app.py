import streamlit as st
import pandas as pd
import base64

# ---------------------------
# Page config
# ---------------------------
st.set_page_config(
    page_title="DFU-VA | Excel Stats",
    page_icon="logo.png",
    layout="wide"
)

# ---------------------------
# Helper: load logo as base64
# ---------------------------
def img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

LOGO_B64 = img_to_base64("logo.png")

# ---------------------------
# Custom red & white styling
# ---------------------------
st.markdown("""
<style>
/* Layout */
.block-container { padding-top: 1.2rem; max-width: 1100px; }

/* Header */
.dfu-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid #f1f1f1;
  border-radius: 18px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.06);
  margin-bottom: 1.5rem;
  background: #ffffff;
}
.dfu-title { margin: 0; font-size: 30px; font-weight: 800; }
.dfu-sub { margin: 0; color: #6b7280; font-size: 14px; }

/* Uploader: make it more “brand” */
section[data-testid="stFileUploaderDropzone"] {
  border-radius: 18px;
  padding: 18px;
  border: 2px dashed rgba(225, 29, 46, 0.45);
  background: #fff5f5;
}

/* Dataframes */
[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)


# ---------------------------
# Header (logo + title)
# ---------------------------
st.markdown(f"""
<div class="dfu-header">
  <img src="data:image/png;base64,{LOGO_B64}" style="height:50px;" />
  <div>
    <p class="dfu-title">Real Estate Excel Stats</p>
    <p class="dfu-sub">Upload your Excel file and get instant insights.</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------
# File upload
# ---------------------------
file = st.file_uploader(
    "Upload your Excel file",
    type=["xlsx", "xls"]
)

if file:
    df = pd.read_excel(file)

    st.subheader("Preview")
    st.dataframe(df.head(20), use_container_width=True)

    cols = list(df.columns)

    st.subheader("Statistics")
    stat_type = st.selectbox(
        "Choose a statistic",
        [
            "Most common value in a column",
            "Top N counts by column",
            "Average of a numeric column by another column",
            "Sum of a numeric column by another column",
        ]
    )

    if stat_type == "Most common value in a column":
        col = st.selectbox("Column", cols)
        if st.button("Run"):
            s = df[col].dropna()
            if s.empty:
                st.warning("No data found.")
            else:
                st.success(f"Most common {col}: {s.mode().iloc[0]}")

    elif stat_type == "Top N counts by column":
        col = st.selectbox("Column", cols)
        top_n = st.number_input("Top N", min_value=1, max_value=50, value=10)
        if st.button("Run"):
            res = df[col].astype(str).value_counts().head(int(top_n))
            st.dataframe(res, use_container_width=True)

    elif stat_type == "Average of a numeric column by another column":
        group_col = st.selectbox("Group by", cols)
        value_col = st.selectbox("Numeric column (average)", cols)
        if st.button("Run"):
            tmp = df[[group_col, value_col]].copy()
            tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce")
            res = tmp.groupby(group_col)[value_col].mean().dropna().sort_values(ascending=False)
            st.dataframe(res, use_container_width=True)

    elif stat_type == "Sum of a numeric column by another column":
        group_col = st.selectbox("Group by", cols)
        value_col = st.selectbox("Numeric column (sum)", cols)
        if st.button("Run"):
            tmp = df[[group_col, value_col]].copy()
            tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce")
            res = tmp.groupby(group_col)[value_col].sum().dropna().sort_values(ascending=False)
            st.dataframe(res, use_container_width=True)

else:
    st.info("Upload an Excel file to start.")

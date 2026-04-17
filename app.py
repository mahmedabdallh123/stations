#1
import streamlit as st
import pandas as pd
import numpy as np
import json
import os
import requests
import shutil
import re
from datetime import datetime, timedelta
import io
import uuid
from PIL import Image
from github import Github, GithubException

# ------------------------------- الإعدادات الثابتة -------------------------------
APP_CONFIG = {
    "APP_TITLE": "نظام إدارة الصيانة - CMMS",
    "APP_ICON": "🏭",
    "REPO_NAME": "mahmedabdallh123/stations",
    "BRANCH": "main",
    "FILE_PATH": "l9.xlsx",
    "LOCAL_FILE": "l9.xlsx",
    "MAX_ACTIVE_USERS": 5,
    "SESSION_DURATION_MINUTES": 60,
    "IMAGES_FOLDER": "event_images",
    "ALLOWED_IMAGE_TYPES": ["jpg", "jpeg", "png", "gif", "bmp", "webp"],
    "MAX_IMAGE_SIZE_MB": 10,
    "DEFAULT_SHEET_COLUMNS": ["مده الاصلاح", "التاريخ", "المعدة", "الحدث/العطل", "الإجراء التصحيحي", "تم بواسطة", "قطع غيار مستخدمة", "نوع العطل", "قدرة الفني (حل/تفكير/مبادرة/قرار)", "الالتزام بتعليمات السلامة", "رابط الصورة"],
    "SPARE_PARTS_SHEET": "قطع_الغيار",
    "SPARE_PARTS_COLUMNS": ["اسم القطعة", "المقاس", "الرصيد الموجود", "مدة التوريد", "ضرورية", "اسم الماكينة", "رابط_الصورة"],
    "MAINTENANCE_SHEET": "صيانة_وقائية",
    "MAINTENANCE_COLUMNS": ["المعدة", "نوع_الصيانة", "اسم_البند", "الفترة_بالأيام", "آخر_تنفيذ", "التاريخ_التالي", "ملاحظات", "قطع_غيار_مستخدمة_افتراضية", "رابط_الصورة"]
}

# ------------------------------- إعداد الصفحة -------------------------------
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

# ------------------------------- استيرادات إضافية مع معالجة الأخطاء -------------------------------
try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        plt.rcParams['font.family'] = 'Arial'
        MATPLOTLIB_AVAILABLE = True
    except ImportError:
        MATPLOTLIB_AVAILABLE = False

# ------------------------------- ثوابت إضافية -------------------------------
USERS_FILE = "users.json"
STATE_FILE = "state.json"
SESSION_DURATION = timedelta(minutes=APP_CONFIG["SESSION_DURATION_MINUTES"])
MAX_ACTIVE_USERS = APP_CONFIG["MAX_ACTIVE_USERS"]
IMAGES_FOLDER = APP_CONFIG["IMAGES_FOLDER"]
EQUIPMENT_CONFIG_FILE = "equipment_config.json"

GITHUB_EXCEL_URL = f"https://github.com/{APP_CONFIG['REPO_NAME'].split('/')[0]}/{APP_CONFIG['REPO_NAME'].split('/')[1]}/raw/{APP_CONFIG['BRANCH']}/{APP_CONFIG['FILE_PATH']}"
GITHUB_USERS_URL = "https://raw.githubusercontent.com/mahmedabdallh123/stations/refs/heads/main/users.json"
GITHUB_REPO_USERS = "mahmedabdallh123/stations"
GITHUB_TOKEN = st.secrets.get("github", {}).get("token", None)
GITHUB_AVAILABLE = GITHUB_TOKEN is not None

# ------------------------------- دوال رفع الصور -------------------------------
def upload_image_to_github(image_file, entity_type, entity_id, custom_filename=None):
    """رفع صورة إلى GitHub وحفظ رابطها."""
    if not GITHUB_AVAILABLE:
        st.error("❌ GitHub token غير متوفر، لا يمكن رفع الصور")
        return None
    
    try:
        img = Image.open(image_file)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=85, optimize=True)
        buffer.seek(0)
        
        if custom_filename:
            filename = custom_filename
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{entity_type}_{entity_id}_{timestamp}.jpg"
        
        repo_path = f"{IMAGES_FOLDER}/{entity_type}/{filename}"
        
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(APP_CONFIG["REPO_NAME"])
        
        try:
            repo.get_contents(f"{IMAGES_FOLDER}/{entity_type}/", ref=APP_CONFIG["BRANCH"])
        except GithubException:
            repo.create_file(f"{IMAGES_FOLDER}/{entity_type}/.gitkeep", 
                            f"Create folder for {entity_type} images", 
                            "", branch=APP_CONFIG["BRANCH"])
        
        content = buffer.getvalue()
        result = repo.create_file(
            path=repo_path,
            message=f"Add image for {entity_type} {entity_id}",
            content=content,
            branch=APP_CONFIG["BRANCH"]
        )
        return f"https://raw.githubusercontent.com/{APP_CONFIG['REPO_NAME']}/{APP_CONFIG['BRANCH']}/{repo_path}"
    except Exception as e:
        st.error(f"❌ خطأ في معالجة الصورة: {e}")
        return None

def get_image_component(image_url, caption=""):
    """عرض الصورة من الرابط مع معالجة الأخطاء."""
    if not image_url or not isinstance(image_url, str):
        return None
    try:
        return st.image(image_url, caption=caption, use_container_width=True)
    except:
        st.warning(f"⚠️ تعذر عرض الصورة: {image_url}")
        return None

# ------------------------------- دوال قطع الغيار -------------------------------
def load_spare_parts():
    if not os.path.exists(APP_CONFIG["LOCAL_FILE"]):
        return pd.DataFrame(columns=APP_CONFIG["SPARE_PARTS_COLUMNS"])
    try:
        df = pd.read_excel(APP_CONFIG["LOCAL_FILE"], sheet_name=APP_CONFIG["SPARE_PARTS_SHEET"])
        df.columns = df.columns.astype(str).str.strip()
        for col in APP_CONFIG["SPARE_PARTS_COLUMNS"]:
            if col not in df.columns:
                df[col] = ""
        df = df.fillna("")
        df["الرصيد الموجود"] = pd.to_numeric(df["الرصيد الموجود"], errors='coerce').fillna(0)
        return df
    except Exception:
        return pd.DataFrame(columns=APP_CONFIG["SPARE_PARTS_COLUMNS"])

def get_spare_parts_for_equipment(equipment_name):
    df = load_spare_parts()
    if df.empty:
        return []
    filtered = df[df["اسم الماكينة"] == equipment_name]
    return list(zip(filtered["اسم القطعة"], filtered["الرصيد الموجود"]))

def consume_spare_part(part_name, quantity=1):
    df = load_spare_parts()
    if df.empty:
        return False, "لا توجد قطع غيار مسجلة", None
    mask = df["اسم القطعة"] == part_name
    if not mask.any():
        return False, f"القطعة '{part_name}' غير موجودة", None
    current_qty = df.loc[mask, "الرصيد الموجود"].values[0]
    if current_qty < quantity:
        return False, f"الرصيد غير كافٍ (الموجود: {current_qty}, المطلوب: {quantity})", current_qty
    new_qty = current_qty - quantity
    df.loc[mask, "الرصيد الموجود"] = new_qty
    if "temp_spare_parts_df" not in st.session_state:
        st.session_state.temp_spare_parts_df = df
    else:
        st.session_state.temp_spare_parts_df = df
    return True, f"تم خصم {quantity} من '{part_name}'، الرصيد الجديد: {new_qty}", new_qty

def get_critical_spare_parts():
    df = load_spare_parts()
    if df.empty:
        return []
    critical = df[(df["ضرورية"] == "نعم") | (df["ضرورية"] == True) | (df["ضرورية"] == "ضروري")]
    critical = critical[critical["الرصيد الموجود"] < 1]
    return critical[["اسم القطعة", "اسم الماكينة", "الرصيد الموجود"]].to_dict('records')

# ------------------------------- دوال الصيانة الوقائية -------------------------------
def load_maintenance_tasks():
    if not os.path.exists(APP_CONFIG["LOCAL_FILE"]):
        return pd.DataFrame(columns=APP_CONFIG["MAINTENANCE_COLUMNS"])
    try:
        df = pd.read_excel(APP_CONFIG["LOCAL_FILE"], sheet_name=APP_CONFIG["MAINTENANCE_SHEET"])
        df.columns = df.columns.astype(str).str.strip()
        for col in APP_CONFIG["MAINTENANCE_COLUMNS"]:
            if col not in df.columns:
                df[col] = ""
        df = df.fillna("")
        if "آخر_تنفيذ" in df.columns:
            df["آخر_تنفيذ"] = pd.to_datetime(df["آخر_تنفيذ"], errors='coerce')
        if "التاريخ_التالي" in df.columns:
            df["التاريخ_التالي"] = pd.to_datetime(df["التاريخ_التالي"], errors='coerce')
        if "الفترة_بالأيام" in df.columns:
            df["الفترة_بالأيام"] = pd.to_numeric(df["الفترة_بالأيام"], errors='coerce').fillna(0)
        return df
    except Exception:
        return pd.DataFrame(columns=APP_CONFIG["MAINTENANCE_COLUMNS"])

def get_tasks_for_equipment(equipment_name):
    df = load_maintenance_tasks()
    if df.empty:
        return df
    return df[df["المعدة"] == equipment_name]

def add_maintenance_task(sheets_edit, equipment, task_name, period_hours, start_date=None, notes="", default_spare="", image_url=None):
    """إضافة بند صيانة جديد مع فترة بالساعات وتاريخ بدء محدد"""
    df = sheets_edit.get(APP_CONFIG["MAINTENANCE_SHEET"])
    if df is None:
        df = pd.DataFrame(columns=APP_CONFIG["MAINTENANCE_COLUMNS"])
    
    # إذا لم يتم تحديد تاريخ البدء، استخدم تاريخ اليوم
    if start_date is None:
        start_date = datetime.now().date()
    
    period_days = period_hours / 24.0
    next_date = start_date + timedelta(days=period_days)
    
    new_row = pd.DataFrame([{
        "المعدة": equipment,
        "نوع_الصيانة": f"{period_hours} ساعة",
        "اسم_البند": task_name,
        "الفترة_بالأيام": period_days,
        "آخر_تنفيذ": pd.NaT,  # لا يوجد تنفيذ سابق
        "التاريخ_التالي": next_date,
        "ملاحظات": notes,
        "قطع_غيار_مستخدمة_افتراضية": default_spare,
        "رابط_الصورة": image_url or ""
    }])
    new_df = pd.concat([df, new_row], ignore_index=True)
    sheets_edit[APP_CONFIG["MAINTENANCE_SHEET"]] = new_df
    return sheets_edit

def execute_maintenance(sheets_edit, task_id, equipment_name, task_name, used_spare_part="", used_quantity=1):
    df = sheets_edit.get(APP_CONFIG["MAINTENANCE_SHEET"])
    if df is None:
        return False, "لا توجد مهام صيانة"
    mask = (df["المعدة"] == equipment_name) & (df["اسم_البند"] == task_name)
    if not mask.any():
        return False, "المهمة غير موجودة"
    idx = df[mask].index[0]
    period = df.loc[idx, "الفترة_بالأيام"]
    today = datetime.now().date()
    df.loc[idx, "آخر_تنفيذ"] = today
    next_date = today + timedelta(days=period)
    df.loc[idx, "التاريخ_التالي"] = next_date
    warning_msg = ""
    if used_spare_part and used_quantity > 0:
        success, msg, new_qty = consume_spare_part(used_spare_part, used_quantity)
        if not success:
            return False, f"فشل خصم قطعة الغيار: {msg}"
        old_notes = df.loc[idx, "ملاحظات"]
        new_note = f"{datetime.now().strftime('%Y-%m-%d')}: استخدمت {used_spare_part} كمية {used_quantity} - {msg}"
        df.loc[idx, "ملاحظات"] = old_notes + "\n" + new_note if old_notes else new_note
        critical_parts = get_critical_spare_parts()
        for cp in critical_parts:
            if cp["اسم القطعة"] == used_spare_part:
                warning_msg = f"⚠️ **تحذير:** القطعة '{used_spare_part}' ضرورية وأصبح رصيدها {new_qty} (أقل من 1). يرجى إعادة التوريد."
                break
    sheets_edit[APP_CONFIG["MAINTENANCE_SHEET"]] = df
    return True, f"تم تنفيذ الصيانة '{task_name}' بنجاح. التاريخ التالي: {next_date.strftime('%Y-%m-%d')}" + (f" {warning_msg}" if warning_msg else "")

def get_upcoming_maintenance(days_ahead=3):
    df = load_maintenance_tasks()
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    today = datetime.now().date()
    overdue = df[df["التاريخ_التالي"] < pd.Timestamp(today)]
    upcoming = df[(df["التاريخ_التالي"] >= pd.Timestamp(today)) & (df["التاريخ_التالي"] <= pd.Timestamp(today + timedelta(days=days_ahead)))]
    return overdue, upcoming

# ------------------------------- دوال تحليل الأعطال المتقدمة -------------------------------
def analyze_time_between_failures(df):
    """تحليل المدة الزمنية بين الأعطال لكل معدة"""
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    if "التاريخ" not in data.columns or "المعدة" not in data.columns:
        return pd.DataFrame()
    data["التاريخ"] = pd.to_datetime(data["التاريخ"], errors='coerce')
    data = data.dropna(subset=["التاريخ"]).sort_values(["المعدة", "التاريخ"])
    results = []
    for equipment in data["المعدة"].unique():
        eq_data = data[data["المعدة"] == equipment]
        if len(eq_data) < 2:
            continue
        time_diffs = eq_data["التاريخ"].diff().dropna()
        days_diffs = time_diffs.dt.total_seconds() / (24 * 3600)
        results.append({
            "المعدة": equipment,
            "عدد الأعطال": len(eq_data),
            "متوسط الفجوة (أيام)": round(days_diffs.mean(), 1),
            "أقل فجوة (أيام)": round(days_diffs.min(), 1),
            "أكبر فجوة (أيام)": round(days_diffs.max(), 1),
            "انحراف معياري": round(days_diffs.std(), 1) if len(days_diffs) > 1 else 0
        })
    return pd.DataFrame(results)

def analyze_technician_performance(df):
    """تحليل أداء الفنيين: مدة الإصلاح، القدرة، الالتزام بالسلامة، وتحليل حسب نوع العطل"""
    if df is None or df.empty:
        return None, None, None
    data = df.copy()
    required_cols = ["تم بواسطة", "مده الاصلاح", "قدرة الفني (حل/تفكير/مبادرة/قرار)", "الالتزام بتعليمات السلامة", "نوع العطل"]
    for col in required_cols:
        if col not in data.columns:
            return None, None, None
    data["مده الاصلاح"] = pd.to_numeric(data["مده الاصلاح"], errors='coerce').fillna(0)
    data["قدرة الفني"] = pd.to_numeric(data["قدرة الفني (حل/تفكير/مبادرة/قرار)"], errors='coerce').fillna(0)
    data["نوع العطل"] = data["نوع العطل"].fillna("غير محدد").astype(str)
    data["الالتزام"] = data["الالتزام بتعليمات السلامة"].fillna("غير مطبق").astype(str)
    
    tech_summary = data.groupby("تم بواسطة").agg({
        "مده الاصلاح": ["mean", "count", "std"],
        "قدرة الفني": "mean",
        "الالتزام": lambda x: x.value_counts().to_dict() if not x.empty else {}
    }).round(2)
    tech_summary.columns = ["متوسط_مدة_الاصلاح", "عدد_الأعطال", "انحراف_مدة_الاصلاح", "متوسط_القدرة", "توزيع_الالتزام"]
    tech_summary = tech_summary.reset_index()
    tech_summary["متوسط_مدة_الاصلاح"] = tech_summary["متوسط_مدة_الاصلاح"].round(1)
    
    tech_by_fault = data.groupby(["تم بواسطة", "نوع العطل"]).agg({
        "قدرة الفني": "mean",
        "مده الاصلاح": "mean"
    }).round(2).reset_index()
    tech_by_fault.columns = ["تم بواسطة", "نوع العطل", "متوسط_القدرة_لهذا_النوع", "متوسط_مدة_اصلاح_لهذا_النوع"]
    
    fault_avg = data.groupby("نوع العطل")["قدرة الفني"].mean().reset_index()
    fault_avg.columns = ["نوع العطل", "متوسط_القدرة_العام"]
    tech_by_fault = tech_by_fault.merge(fault_avg, on="نوع العطل", how="left")
    tech_by_fault["مقارنة_بالمتوسط"] = tech_by_fault["متوسط_القدرة_لهذا_النوع"] - tech_by_fault["متوسط_القدرة_العام"]
    tech_by_fault["الأداء"] = tech_by_fault["مقارنة_بالمتوسط"].apply(
        lambda x: "🟢 قوي" if x > 0.3 else ("🟡 متوسط" if abs(x) <= 0.3 else "🔴 ضعيف")
    )
    
    strengths = {}
    weaknesses = {}
    for tech in tech_summary["تم بواسطة"].unique():
        tech_data = tech_by_fault[tech_by_fault["تم بواسطة"] == tech]
        strengths[tech] = tech_data[tech_data["الأداء"] == "🟢 قوي"]["نوع العطل"].tolist()
        weaknesses[tech] = tech_data[tech_data["الأداء"] == "🔴 ضعيف"]["نوع العطل"].tolist()
    
    return tech_summary, tech_by_fault, {"strengths": strengths, "weaknesses": weaknesses}

def analyze_failures(df, equipment_name=None):
    if df is None or df.empty:
        return None
    data = df.copy()
    if "التاريخ" not in data.columns or "المعدة" not in data.columns:
        return None
    data["التاريخ"] = pd.to_datetime(data["التاريخ"], errors='coerce')
    data = data.dropna(subset=["التاريخ"])
    if data.empty:
        return None
    if equipment_name and equipment_name != "جميع المعدات":
        data = data[data["المعدة"] == equipment_name]
    if data.empty:
        return None
    data = data.sort_values("التاريخ")
    total_failures = len(data)
    unique_equipment = data["المعدة"].nunique()
    failure_rate = data["المعدة"].value_counts().reset_index()
    failure_rate.columns = ["المعدة", "عدد الأعطال"]
    failure_rate["النسبة المئوية"] = (failure_rate["عدد الأعطال"] / total_failures * 100).round(2)
    
    if "الحدث/العطل" in data.columns:
        all_issues = data["الحدث/العطل"].dropna().astype(str)
        issue_counts = all_issues.value_counts().head(10).reset_index()
        issue_counts.columns = ["الحدث/العطل", "عدد المرات"]
    else:
        issue_counts = pd.DataFrame()
    
    if "نوع العطل" in data.columns:
        fault_types = data["نوع العطل"].dropna().astype(str).value_counts().reset_index()
        fault_types.columns = ["نوع العطل", "عدد المرات"]
    else:
        fault_types = pd.DataFrame()
    
    mtbf_results = []
    for equipment in data["المعدة"].unique():
        eq_data = data[data["المعدة"] == equipment].sort_values("التاريخ")
        if len(eq_data) >= 2:
            time_diffs = eq_data["التاريخ"].diff().dropna()
            days_diff = time_diffs.dt.total_seconds() / (24 * 3600)
            avg_mtbf = days_diff.mean()
            mtbf_results.append({
                "المعدة": equipment,
                "عدد الأعطال": len(eq_data),
                "متوسط MTBF (أيام)": round(avg_mtbf, 1),
                "أول عطل": eq_data["التاريخ"].min().strftime("%Y-%m-%d"),
                "آخر عطل": eq_data["التاريخ"].max().strftime("%Y-%m-%d")
            })
    mtbf_df = pd.DataFrame(mtbf_results) if mtbf_results else pd.DataFrame()
    
    time_between_df = analyze_time_between_failures(data)
    tech_summary, tech_by_fault, tech_strengths_weaknesses = analyze_technician_performance(data)
    
    data["الشهر"] = data["التاريخ"].dt.to_period("M").astype(str)
    monthly_failures = data.groupby(["الشهر", "المعدة"]).size().reset_index(name="عدد الأعطال")
    
    weekday_names = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    data["يوم_الأسبوع"] = data["التاريخ"].dt.dayofweek.map({
        0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس", 
        4: "الجمعة", 5: "السبت", 6: "الأحد"
    })
    weekday_failures = data["يوم_الأسبوع"].value_counts().reindex(weekday_names).fillna(0).reset_index()
    weekday_failures.columns = ["اليوم", "عدد الأعطال"]
    
    if "الإجراء التصحيحي" in data.columns:
        corrections = data["الإجراء التصحيحي"].dropna().astype(str)
        correction_counts = corrections.value_counts().head(10).reset_index()
        correction_counts.columns = ["الإجراء التصحيحي", "عدد المرات"]
    else:
        correction_counts = pd.DataFrame()
    
    if "مده الاصلاح" in data.columns:
        data["مده الاصلاح"] = pd.to_numeric(data["مده الاصلاح"], errors='coerce')
        avg_repair_time = data["مده الاصلاح"].mean()
        median_repair_time = data["مده الاصلاح"].median()
        repair_by_equipment = data.groupby("المعدة")["مده الاصلاح"].mean().reset_index()
        repair_by_equipment.columns = ["المعدة", "متوسط مدة الإصلاح (ساعات)"]
    else:
        avg_repair_time = None
        median_repair_time = None
        repair_by_equipment = pd.DataFrame()
    
    return {
        "total_failures": total_failures,
        "unique_equipment": unique_equipment,
        "date_range": {"from": data["التاريخ"].min().strftime("%Y-%m-%d"), "to": data["التاريخ"].max().strftime("%Y-%m-%d")},
        "failure_rate": failure_rate,
        "issue_counts": issue_counts,
        "fault_types": fault_types,
        "mtbf": mtbf_df,
        "time_between_failures": time_between_df,
        "monthly": monthly_failures,
        "weekday": weekday_failures,
        "correction_counts": correction_counts,
        "avg_repair_time": avg_repair_time,
        "median_repair_time": median_repair_time,
        "repair_by_equipment": repair_by_equipment,
        "technician_summary": tech_summary,
        "technician_by_fault": tech_by_fault,
        "technician_strengths_weaknesses": tech_strengths_weaknesses,
        "raw_data": data
    }

def generate_excel_report(analysis, sheet_name, equipment_filter):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_data = {
            "المعيار": ["إجمالي الأعطال", "عدد المعدات", "فترة التحليل من", "فترة التحليل إلى", "المعدة المفلترة"],
            "القيمة": [analysis["total_failures"], analysis["unique_equipment"], analysis["date_range"]["from"], analysis["date_range"]["to"], equipment_filter if equipment_filter else "جميع المعدات"]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name="الملخص", index=False)
        if not analysis["failure_rate"].empty:
            analysis["failure_rate"].to_excel(writer, sheet_name="معدل تكرار الأعطال", index=False)
        if not analysis["issue_counts"].empty:
            analysis["issue_counts"].to_excel(writer, sheet_name="أكثر الأعطال تكراراً", index=False)
        if not analysis["fault_types"].empty:
            analysis["fault_types"].to_excel(writer, sheet_name="أنواع الأعطال", index=False)
        if not analysis["mtbf"].empty:
            analysis["mtbf"].to_excel(writer, sheet_name="متوسط الوقت بين الأعطال (MTBF)", index=False)
        if not analysis["time_between_failures"].empty:
            analysis["time_between_failures"].to_excel(writer, sheet_name="الفجوات الزمنية بين الأعطال", index=False)
        if not analysis["monthly"].empty:
            pivot_monthly = analysis["monthly"].pivot(index="الشهر", columns="المعدة", values="عدد الأعطال").fillna(0)
            pivot_monthly.to_excel(writer, sheet_name="التحليل الشهري")
        if not analysis["weekday"].empty:
            analysis["weekday"].to_excel(writer, sheet_name="تحليل أيام الأسبوع", index=False)
        if not analysis["correction_counts"].empty:
            analysis["correction_counts"].to_excel(writer, sheet_name="الإجراءات التصحيحية", index=False)
        if not analysis["repair_by_equipment"].empty:
            analysis["repair_by_equipment"].to_excel(writer, sheet_name="متوسط مدة الإصلاح", index=False)
        if analysis["technician_summary"] is not None and not analysis["technician_summary"].empty:
            analysis["technician_summary"].to_excel(writer, sheet_name="ملخص أداء الفنيين", index=False)
        if analysis["technician_by_fault"] is not None and not analysis["technician_by_fault"].empty:
            analysis["technician_by_fault"].to_excel(writer, sheet_name="أداء الفنيين حسب نوع العطل", index=False)
        
        # تحديد الأعمدة الموجودة فقط في raw_data
        desired_cols = ["التاريخ", "المعدة", "الحدث/العطل", "الإجراء التصحيحي", "تم بواسطة", "قطع غيار مستخدمة", "نوع العطل", "قدرة الفني (حل/تفكير/مبادرة/قرار)", "الالتزام بتعليمات السلامة", "رابط الصورة"]
        if "مده الاصلاح" in analysis["raw_data"].columns:
            desired_cols.insert(0, "مده الاصلاح")
        # تصفية الأعمدة الموجودة فقط
        existing_cols = [col for col in desired_cols if col in analysis["raw_data"].columns]
        raw_export = analysis["raw_data"][existing_cols].copy()
        raw_export.to_excel(writer, sheet_name="البيانات الخام", index=False)
    output.seek(0)
    return output

def create_failure_charts_plotly(analysis):
    charts = []
    if not PLOTLY_AVAILABLE:
        return charts
    if not analysis["failure_rate"].empty:
        fig = px.bar(analysis["failure_rate"].head(10), x="المعدة", y="عدد الأعطال", title="أكثر الماكينات تعطلاً", text="عدد الأعطال", color="عدد الأعطال", color_continuous_scale="Reds")
        fig.update_traces(textposition='outside')
        fig.update_layout(showlegend=False)
        charts.append(fig)
    if not analysis["failure_rate"].empty:
        fig = px.pie(analysis["failure_rate"].head(8), values="عدد الأعطال", names="المعدة", title="نسب الأعطال حسب الماكينة", hole=0.3)
        charts.append(fig)
    if not analysis["fault_types"].empty:
        fig = px.bar(analysis["fault_types"], x="نوع العطل", y="عدد المرات", title="توزيع أنواع الأعطال", text="عدد المرات", color="عدد المرات", color_continuous_scale="Teal")
        fig.update_traces(textposition='outside')
        charts.append(fig)
    if not analysis["monthly"].empty:
        fig = px.line(analysis["monthly"], x="الشهر", y="عدد الأعطال", color="المعدة", title="تطور الأعطال شهرياً", markers=True)
        charts.append(fig)
    if not analysis["weekday"].empty:
        fig = px.bar(analysis["weekday"], x="اليوم", y="عدد الأعطال", title="توزيع الأعطال حسب أيام الأسبوع", text="عدد الأعطال", color="عدد الأعطال", color_continuous_scale="Blues")
        fig.update_traces(textposition='outside')
        charts.append(fig)
    if not analysis["mtbf"].empty:
        fig = px.bar(analysis["mtbf"], x="المعدة", y="متوسط MTBF (أيام)", title="متوسط الوقت بين الأعطال (MTBF) - أيام", text="متوسط MTBF (أيام)", color="متوسط MTBF (أيام)", color_continuous_scale="Greens")
        fig.update_traces(textposition='outside')
        charts.append(fig)
    if not analysis["time_between_failures"].empty:
        fig = px.bar(analysis["time_between_failures"], x="المعدة", y="متوسط الفجوة (أيام)", title="متوسط الفجوة الزمنية بين الأعطال (أيام)", text="متوسط الفجوة (أيام)", color="متوسط الفجوة (أيام)", color_continuous_scale="Purples")
        fig.update_traces(textposition='outside')
        charts.append(fig)
    if not analysis["issue_counts"].empty:
        fig = px.bar(analysis["issue_counts"].head(10), x="عدد المرات", y="الحدث/العطل", title="أكثر الأعطال تكراراً", text="عدد المرات", orientation='h', color="عدد المرات", color_continuous_scale="Purples")
        fig.update_traces(textposition='outside')
        charts.append(fig)
    if not analysis["repair_by_equipment"].empty:
        fig = px.bar(analysis["repair_by_equipment"], x="المعدة", y="متوسط مدة الإصلاح (ساعات)", title="متوسط مدة الإصلاح حسب الماكينة", text="متوسط مدة الإصلاح (ساعات)", color="متوسط مدة الإصلاح (ساعات)", color_continuous_scale="Oranges")
        fig.update_traces(textposition='outside')
        charts.append(fig)
    return charts

def failures_analysis_tab(all_sheets):
    st.header("📊 تحليل الأعطال والإجراءات التصحيحية")
    if not all_sheets:
        st.warning("لا توجد بيانات للتحليل")
        return
    col1, col2 = st.columns(2)
    with col1:
        sheet_options = list(all_sheets.keys())
        selected_sheet = st.selectbox("اختر القسم للتحليل:", sheet_options, key="analysis_sheet")
    with col2:
        df = all_sheets[selected_sheet]
        equipment_list = get_equipment_list_from_sheet(df)
        equipment_options = ["جميع الماكينات"] + equipment_list
        selected_equipment = st.selectbox("اختر الماكينة للتحليل:", equipment_options, key="analysis_equipment")
    if st.button("🔄 تشغيل التحليل", key="run_analysis", type="primary"):
        with st.spinner("جاري تحليل البيانات..."):
            analysis = analyze_failures(df, selected_equipment if selected_equipment != "جميع الماكينات" else None)
            if analysis is None:
                st.error("❌ لا توجد بيانات كافية للتحليل.")
                return
            st.subheader("📈 ملخص التحليل")
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a: st.metric("إجمالي الأعطال", analysis["total_failures"])
            with col_b: st.metric("عدد الماكينات", analysis["unique_equipment"])
            with col_c: st.metric("من تاريخ", analysis["date_range"]["from"])
            with col_d: st.metric("إلى تاريخ", analysis["date_range"]["to"])
            if analysis["avg_repair_time"] is not None:
                st.subheader("⏱️ إحصائيات مدة الإصلاح")
                col_r1, col_r2 = st.columns(2)
                with col_r1: st.metric("متوسط مدة الإصلاح (ساعات)", f"{analysis['avg_repair_time']:.1f}")
                with col_r2: st.metric("الوسيط", f"{analysis['median_repair_time']:.1f}")
            st.subheader("📊 الرسوم البيانية")
            if PLOTLY_AVAILABLE:
                charts = create_failure_charts_plotly(analysis)
                for chart in charts: st.plotly_chart(chart, use_container_width=True)
            else:
                st.warning("مكتبات الرسم غير متوفرة")
            
            st.subheader("📋 الجداول التفصيلية")
            tabs_list = ["معدل تكرار الأعطال", "أكثر الأعطال تكراراً", "أنواع الأعطال", "MTBF", "الفجوات الزمنية", "التحليل الشهري", "الإجراءات التصحيحية", "متوسط مدة الإصلاح", "تحليل أداء الفنيين"]
            tabs_analysis = st.tabs(tabs_list)
            with tabs_analysis[0]:
                if not analysis["failure_rate"].empty: st.dataframe(analysis["failure_rate"])
                else: st.info("لا توجد بيانات")
            with tabs_analysis[1]:
                if not analysis["issue_counts"].empty: st.dataframe(analysis["issue_counts"])
                else: st.info("لا توجد بيانات")
            with tabs_analysis[2]:
                if not analysis["fault_types"].empty: st.dataframe(analysis["fault_types"])
                else: st.info("لا توجد بيانات عن أنواع الأعطال")
            with tabs_analysis[3]:
                if not analysis["mtbf"].empty: st.dataframe(analysis["mtbf"])
                else: st.info("لا توجد بيانات كافية لحساب MTBF")
            with tabs_analysis[4]:
                if not analysis["time_between_failures"].empty: st.dataframe(analysis["time_between_failures"])
                else: st.info("لا توجد بيانات كافية لتحليل الفجوات الزمنية")
            with tabs_analysis[5]:
                if not analysis["monthly"].empty: st.dataframe(analysis["monthly"].pivot(index="الشهر", columns="المعدة", values="عدد الأعطال").fillna(0))
                else: st.info("لا توجد بيانات")
            with tabs_analysis[6]:
                if not analysis["correction_counts"].empty: st.dataframe(analysis["correction_counts"])
                else: st.info("لا توجد بيانات")
            with tabs_analysis[7]:
                if not analysis["repair_by_equipment"].empty: st.dataframe(analysis["repair_by_equipment"])
                else: st.info("لا توجد بيانات")
            with tabs_analysis[8]:
                st.subheader("👨‍🔧 تحليل أداء الفنيين")
                if analysis["technician_summary"] is not None and not analysis["technician_summary"].empty:
                    st.markdown("#### ملخص أداء الفنيين")
                    tech_cols = st.columns(min(3, len(analysis["technician_summary"])))
                    for i, row in analysis["technician_summary"].iterrows():
                        with tech_cols[i % len(tech_cols)]:
                            with st.container(border=True):
                                st.markdown(f"**👤 {row['تم بواسطة']}**")
                                st.metric("عدد الأعطال", int(row['عدد_الأعطال']))
                                st.metric("متوسط مدة الإصلاح (ساعات)", f"{row['متوسط_مدة_الاصلاح']:.1f}")
                                st.metric("متوسط القدرة (1-5)", f"{row['متوسط_القدرة']:.2f}")
                                compliance = row['توزيع_الالتزام']
                                if isinstance(compliance, dict):
                                    compliant_pct = compliance.get("ملتزم بالكامل", 0) / row['عدد_الأعطال'] * 100 if row['عدد_الأعطال'] > 0 else 0
                                    st.progress(compliant_pct/100, text=f"الالتزام الكامل: {compliant_pct:.0f}%")
                    
                    st.markdown("#### أداء الفنيين حسب نوع العطل")
                    if analysis["technician_by_fault"] is not None and not analysis["technician_by_fault"].empty:
                        display_df = analysis["technician_by_fault"].copy()
                        if "الأداء" in display_df.columns:
                            def color_cells(val):
                                if isinstance(val, str) and "🟢" in val:
                                    return 'background-color: #90EE90'
                                elif isinstance(val, str) and "🔴" in val:
                                    return 'background-color: #FFCCCC'
                                return ''
                            styled = display_df.style.map(color_cells, subset=['الأداء'])
                            st.dataframe(styled, use_container_width=True)
                        else:
                            st.dataframe(display_df, use_container_width=True)
                    else:
                        st.info("لا توجد بيانات كافية عن أداء الفنيين حسب نوع العطل")
                    
                    st.markdown("#### نقاط القوة والضعف")
                    strengths_weak = analysis["technician_strengths_weaknesses"]
                    if strengths_weak:
                        for tech in analysis["technician_summary"]["تم بواسطة"]:
                            with st.expander(f"📌 {tech}"):
                                strong = strengths_weak.get("strengths", {}).get(tech, [])
                                weak = strengths_weak.get("weaknesses", {}).get(tech, [])
                                if strong:
                                    st.success(f"✅ **قوي في:** {', '.join(strong)}")
                                else:
                                    st.info("لا توجد نقاط قوة مميزة (أداؤه متوسط في جميع الأنواع)")
                                if weak:
                                    st.error(f"❌ **ضعيف في:** {', '.join(weak)}")
                                else:
                                    st.info("لا توجد نقاط ضعف واضحة (أداؤه جيد في جميع الأنواع)")
                    else:
                        st.info("لا توجد بيانات كافية لتحليل نقاط القوة والضعف")
                else:
                    st.info("لا توجد بيانات كافية لتحليل أداء الفنيين (تأكد من وجود أعطال مسجلة مع تحديد 'تم بواسطة' و'قدرة الفني' و'نوع العطل')")
            
            st.markdown("---")
            st.subheader("📥 تصدير التقرير")
            excel_report = generate_excel_report(analysis, selected_sheet, selected_equipment)
            st.download_button("📊 تحميل تقرير التحليل كملف Excel", excel_report, f"failure_analysis_{selected_sheet}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="download_analysis_report")
            # ------------------------------- دوال المستخدمين والجلسات -------------------------------
def download_users_from_github():
    try:
        response = requests.get(GITHUB_USERS_URL, timeout=10)
        response.raise_for_status()
        users_data = response.json()
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_data, f, indent=4, ensure_ascii=False)
        return users_data
    except:
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {"admin": {"password": "admin123", "role": "admin", "created_at": datetime.now().isoformat(), "permissions": ["all"], "active": False}}

def upload_users_to_github(users_data):
    try:
        token = st.secrets.get("github", {}).get("token", None)
        if not token:
            st.error("❌ لم يتم العثور على GitHub token")
            return False
        g = Github(token)
        repo = g.get_repo(GITHUB_REPO_USERS)
        users_json = json.dumps(users_data, indent=4, ensure_ascii=False, sort_keys=True)
        try:
            contents = repo.get_contents("users.json", ref="main")
            repo.update_file(path="users.json", message="تحديث ملف المستخدمين", content=users_json, sha=contents.sha, branch="main")
            return True
        except:
            repo.create_file(path="users.json", message="إنشاء ملف المستخدمين", content=users_json, branch="main")
            return True
    except Exception as e:
        st.error(f"❌ فشل رفع المستخدمين: {e}")
        return False

def load_users():
    try:
        users_data = download_users_from_github()
        if "admin" not in users_data:
            users_data["admin"] = {"password": "admin123", "role": "admin", "created_at": datetime.now().isoformat(), "permissions": ["all"], "active": False}
        return users_data
    except:
        return {"admin": {"password": "admin123", "role": "admin", "created_at": datetime.now().isoformat(), "permissions": ["all"], "active": False}}

def load_state():
    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

def cleanup_sessions(state):
    now = datetime.now()
    changed = False
    for user, info in list(state.items()):
        if info.get("active") and "login_time" in info:
            try:
                login_time = datetime.fromisoformat(info["login_time"])
                if now - login_time > SESSION_DURATION:
                    info["active"] = False
                    info.pop("login_time", None)
                    changed = True
            except:
                info["active"] = False
                changed = True
    if changed:
        save_state(state)
    return state

def remaining_time(state, username):
    if not username or username not in state:
        return None
    info = state.get(username)
    if not info or not info.get("active"):
        return None
    try:
        lt = datetime.fromisoformat(info["login_time"])
        remaining = SESSION_DURATION - (datetime.now() - lt)
        if remaining.total_seconds() <= 0:
            return None
        return remaining
    except:
        return None

def logout_action():
    state = load_state()
    username = st.session_state.get("username")
    if username and username in state:
        state[username]["active"] = False
        state[username].pop("login_time", None)
        save_state(state)
    for k in list(st.session_state.keys()):
        st.session_state.pop(k, None)
    st.rerun()

def login_ui():
    users = load_users()
    state = cleanup_sessions(load_state())
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.user_role = None
        st.session_state.user_permissions = []

    st.title(f"{APP_CONFIG['APP_ICON']} تسجيل الدخول - {APP_CONFIG['APP_TITLE']}")
    username_input = st.selectbox("اختر المستخدم", list(users.keys()))
    password = st.text_input("كلمة المرور", type="password")
    active_users = [u for u, v in state.items() if v.get("active")]
    active_count = len(active_users)
    st.caption(f"المستخدمون النشطون: {active_count} / {MAX_ACTIVE_USERS}")

    if not st.session_state.logged_in:
        if st.button("تسجيل الدخول"):
            current_users = load_users()
            if username_input in current_users and current_users[username_input]["password"] == password:
                if username_input != "admin" and username_input in active_users:
                    st.warning("هذا المستخدم مسجل دخول بالفعل.")
                    return False
                elif active_count >= MAX_ACTIVE_USERS and username_input != "admin":
                    st.error("الحد الأقصى للمستخدمين المتصلين.")
                    return False
                state[username_input] = {"active": True, "login_time": datetime.now().isoformat()}
                save_state(state)
                st.session_state.logged_in = True
                st.session_state.username = username_input
                st.session_state.user_role = current_users[username_input].get("role", "viewer")
                st.session_state.user_permissions = current_users[username_input].get("permissions", ["view"])
                st.success(f"تم تسجيل الدخول: {username_input}")
                st.rerun()
            else:
                st.error("كلمة المرور غير صحيحة.")
        return False
    else:
        st.success(f"مسجل الدخول كـ: {st.session_state.username}")
        rem = remaining_time(state, st.session_state.username)
        if rem:
            mins, secs = divmod(int(rem.total_seconds()), 60)
            st.info(f"الوقت المتبقي: {mins:02d}:{secs:02d}")
        if st.button("تسجيل الخروج"):
            logout_action()
        return True

# ------------------------------- دوال الملفات -------------------------------
def fetch_from_github_requests():
    try:
        response = requests.get(GITHUB_EXCEL_URL, stream=True, timeout=15)
        response.raise_for_status()
        with open(APP_CONFIG["LOCAL_FILE"], "wb") as f:
            shutil.copyfileobj(response.raw, f)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"فشل التحديث: {e}")
        return False

@st.cache_data(show_spinner=False)
def load_all_sheets():
    if not os.path.exists(APP_CONFIG["LOCAL_FILE"]):
        return None
    try:
        sheets = pd.read_excel(APP_CONFIG["LOCAL_FILE"], sheet_name=None)
        if not sheets:
            return None
        for name, df in sheets.items():
            if df.empty:
                continue
            df.columns = df.columns.astype(str).str.strip()
            df = df.fillna('')
            sheets[name] = df
        return sheets
    except Exception as e:
        st.error(f"خطأ في تحميل الأقسام: {e}")
        return None

@st.cache_data(show_spinner=False)
def load_sheets_for_edit():
    if not os.path.exists(APP_CONFIG["LOCAL_FILE"]):
        return None
    try:
        sheets = pd.read_excel(APP_CONFIG["LOCAL_FILE"], sheet_name=None, dtype=object)
        if not sheets:
            return None
        for name, df in sheets.items():
            df.columns = df.columns.astype(str).str.strip()
            df = df.fillna('')
            sheets[name] = df
        return sheets
    except Exception as e:
        st.error(f"خطأ في تحميل الأقسام: {e}")
        return None

def save_excel_locally(sheets_dict):
    try:
        if "temp_spare_parts_df" in st.session_state:
            sheets_dict[APP_CONFIG["SPARE_PARTS_SHEET"]] = st.session_state.temp_spare_parts_df
            del st.session_state.temp_spare_parts_df
        with pd.ExcelWriter(APP_CONFIG["LOCAL_FILE"], engine="openpyxl") as writer:
            for name, sh in sheets_dict.items():
                try:
                    sh.to_excel(writer, sheet_name=name, index=False)
                except Exception:
                    sh.astype(object).to_excel(writer, sheet_name=name, index=False)
        return True
    except Exception as e:
        st.error(f"❌ خطأ في الحفظ المحلي: {e}")
        return False

def push_to_github():
    try:
        token = st.secrets.get("github", {}).get("token", None)
        if not token:
            st.error("❌ لم يتم العثور على GitHub token في secrets")
            return False
        if not GITHUB_AVAILABLE:
            st.error("❌ PyGithub غير متوفر")
            return False
        g = Github(token)
        repo = g.get_repo(APP_CONFIG["REPO_NAME"])
        with open(APP_CONFIG["LOCAL_FILE"], "rb") as f:
            content = f.read()
        try:
            contents = repo.get_contents(APP_CONFIG["FILE_PATH"], ref=APP_CONFIG["BRANCH"])
            repo.update_file(path=APP_CONFIG["FILE_PATH"], message=f"تحديث البيانات - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", content=content, sha=contents.sha, branch=APP_CONFIG["BRANCH"])
            st.success("✅ تم رفع التغييرات إلى GitHub")
            return True
        except GithubException as e:
            if e.status == 404:
                repo.create_file(path=APP_CONFIG["FILE_PATH"], message=f"إنشاء ملف جديد - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", content=content, branch=APP_CONFIG["BRANCH"])
                st.success("✅ تم إنشاء الملف على GitHub")
                return True
            else:
                st.error(f"❌ خطأ GitHub: {e}")
                return False
    except Exception as e:
        st.error(f"❌ فشل الرفع: {e}")
        return False

def save_and_push_to_github(sheets_dict, operation_name):
    st.info(f"💾 جاري حفظ {operation_name}...")
    if save_excel_locally(sheets_dict):
        st.success("✅ تم الحفظ محلياً")
        if push_to_github():
            st.success("✅ تم الرفع إلى GitHub")
            st.cache_data.clear()
            return True
        else:
            st.warning("⚠️ تم الحفظ محلياً فقط")
            return True
    else:
        st.error("❌ فشل الحفظ المحلي")
        return False

# ------------------------------- دوال التصدير والعرض -------------------------------
def export_sheet_to_excel(sheets_dict, sheet_name):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df = sheets_dict[sheet_name]
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return output

def export_all_sheets_to_excel(sheets_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in sheets_dict.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return output

def export_filtered_results_to_excel(results_df, sheet_name):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        results_df.to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return output

def display_sheet_data(sheet_name, df, unique_id, sheets_edit):
    st.markdown(f"### 🏭 {sheet_name}")
    st.info(f"عدد الماكينات المسجلة: {len(df)} | عدد الأعمدة: {len(df.columns)}")
    equipment_list = get_equipment_list_from_sheet(df)
    if equipment_list and "المعدة" in df.columns:
        st.markdown("#### 🔍 فلتر حسب الماكينة:")
        selected_filter = st.selectbox("اختر الماكينة:", ["جميع الماكينات"] + equipment_list, key=f"filter_{unique_id}")
        if selected_filter != "جميع الماكينات":
            df = df[df["المعدة"] == selected_filter]
            st.info(f"عرض لماكينة: {selected_filter} - السجلات: {len(df)}")
    
    # عمل نسخة للعرض مع تحويل رابط الصورة إلى عنصر HTML لعرض الصورة (لن يظهر في dataframe، سنعرضها بشكل منفصل)
    display_df = df.copy()
    for col in display_df.columns:
        if display_df[col].dtype == 'object':
            display_df[col] = display_df[col].astype(str).apply(lambda x: x[:100] + "..." if len(x) > 100 else x)
    
    # إزالة عمود رابط الصورة من الجدول لتجنب النص الطويل، وسنعرض الصور بشكل منفصل
    if "رابط الصورة" in display_df.columns:
        display_df = display_df.drop(columns=["رابط الصورة"])
    
    st.dataframe(display_df, use_container_width=True, height=400)
    
    # عرض الصور المرتبطة بالصفوف
    if "رابط الصورة" in df.columns and not df["رابط الصورة"].isnull().all():
        st.markdown("#### 🖼️ الصور المرفقة")
        for idx, row in df.iterrows():
            img_url = row["رابط الصورة"]
            if img_url and isinstance(img_url, str) and img_url.strip() != "":
                with st.expander(f"📸 صورة للصف رقم {idx+1}"):
                    try:
                        st.image(img_url, use_container_width=True)
                        # إضافة رابط تحميل مباشر
                        st.caption(f"[رابط الصورة]({img_url})")
                    except Exception as e:
                        st.warning(f"⚠️ تعذر عرض الصورة: {e}")
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        excel_file = export_sheet_to_excel({sheet_name: df}, sheet_name)
        st.download_button("📥 تحميل بيانات هذا القسم كملف Excel", excel_file, f"{sheet_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"export_sheet_{unique_id}")
    with col_btn2:
        all_sheets_excel = export_all_sheets_to_excel({sheet_name: df})
        st.download_button("📥 تحميل جميع البيانات كملف Excel", all_sheets_excel, f"all_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"export_all_{unique_id}")
def search_across_sheets(all_sheets):
    st.subheader("بحث متقدم في السجلات")
    if not all_sheets:
        st.warning("لا توجد بيانات للبحث")
        return
    
    col1, col2 = st.columns(2)
    with col1:
        sheet_options = ["جميع الأقسام"] + list(all_sheets.keys())
        selected_sheet = st.selectbox("اختر القسم للبحث:", sheet_options, key="search_sheet")
        if selected_sheet != "جميع الأقسام":
            df_temp = all_sheets[selected_sheet]
            equipment_list = get_equipment_list_from_sheet(df_temp)
        else:
            all_eq = set()
            for sh_name, sh_df in all_sheets.items():
                all_eq.update(get_equipment_list_from_sheet(sh_df))
            equipment_list = sorted(all_eq)
        filter_equipment = st.selectbox("فلتر حسب الماكينة:", ["الكل"] + equipment_list, key="search_eq")
        search_term = st.text_input("كلمة البحث:", placeholder="أدخل نصاً للبحث...", key="search_term")
    with col2:
        st.markdown("#### نطاق التاريخ")
        use_date_filter = st.checkbox("تفعيل البحث بالتاريخ", key="use_date_filter")
        if use_date_filter:
            col_date1, col_date2 = st.columns(2)
            with col_date1:
                start_date = st.date_input("من تاريخ:", value=datetime.now() - timedelta(days=30), key="start_date")
            with col_date2:
                end_date = st.date_input("إلى تاريخ:", value=datetime.now(), key="end_date")
        else:
            start_date = None
            end_date = None
    
    # خيار طريقة العرض
    view_mode = st.radio("طريقة العرض:", ["جدول", "بطاقات مع الصور"], horizontal=True, key="search_view_mode")
    
    if st.button("بحث", key="search_btn", type="primary"):
        results = []
        sheets_to_search = all_sheets.items()
        if selected_sheet != "جميع الأقسام":
            sheets_to_search = [(selected_sheet, all_sheets[selected_sheet])]
        for sheet_name, df in sheets_to_search:
            df_filtered = df.copy()
            if filter_equipment != "الكل" and "المعدة" in df_filtered.columns:
                df_filtered = df_filtered[df_filtered["المعدة"] == filter_equipment]
            if use_date_filter and start_date and end_date and "التاريخ" in df_filtered.columns:
                try:
                    df_filtered["التاريخ"] = pd.to_datetime(df_filtered["التاريخ"], errors='coerce')
                    mask = (df_filtered["التاريخ"].dt.date >= start_date) & (df_filtered["التاريخ"].dt.date <= end_date)
                    df_filtered = df_filtered[mask]
                except:
                    pass
            if search_term:
                search_columns = ["الحدث/العطل", "الإجراء التصحيحي", "قطع غيار مستخدمة", "نوع العطل", "قدرة الفني (حل/تفكير/مبادرة/قرار)", "الالتزام بتعليمات السلامة", "رابط الصورة"]
                if "مده الاصلاح" in df_filtered.columns:
                    search_columns.append("مده الاصلاح")
                mask = pd.Series([False] * len(df_filtered))
                for col in search_columns:
                    if col in df_filtered.columns:
                        mask = mask | df_filtered[col].astype(str).str.contains(search_term, case=False, na=False)
                df_filtered = df_filtered[mask]
            if not df_filtered.empty:
                df_filtered["القسم"] = sheet_name
                results.append(df_filtered)
        
        if results:
            combined_results = pd.concat(results, ignore_index=True)
            st.success(f"تم العثور على {len(combined_results)} نتيجة")
            
            if view_mode == "جدول":
                # العرض الجدولي: إخفاء عمود الصورة إن وجد لتجنب النص الطويل
                display_cols = [c for c in combined_results.columns if c != "رابط الصورة"]
                st.dataframe(combined_results[display_cols], use_container_width=True, height=500)
            else:
                # العرض بالبطاقات مع الصور
                for idx, row in combined_results.iterrows():
                    with st.container(border=True):
                        col_img, col_info = st.columns([1, 3])
                        img_url = row.get("رابط الصورة", "")
                        with col_img:
                            if img_url and isinstance(img_url, str) and img_url.strip() != "":
                                try:
                                    st.image(img_url, use_container_width=True)
                                except:
                                    st.write("🖼️ (تعذر عرض الصورة)")
                            else:
                                st.write("📄 لا توجد صورة")
                        with col_info:
                            st.markdown(f"**📁 القسم:** {row.get('القسم', '')}")
                            st.markdown(f"**📅 التاريخ:** {row.get('التاريخ', '')}")
                            st.markdown(f"**⚙️ المعدة:** {row.get('المعدة', '')}")
                            st.markdown(f"**⚠️ العطل:** {row.get('الحدث/العطل', '')[:150]}")
                            st.markdown(f"**🔧 الإجراء:** {row.get('الإجراء التصحيحي', '')[:150]}")
                            if img_url:
                                st.caption(f"[🔗 رابط الصورة]({img_url})")
            
            # زر تحميل Excel (موجود في كلتا الحالتين)
            excel_file = export_filtered_results_to_excel(combined_results, "نتائج_البحث")
            st.download_button("📥 تحميل نتائج البحث كملف Excel", excel_file, f"search_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key='download-excel')
        else:
            st.warning("لا توجد نتائج مطابقة للبحث")
# ------------------------------- دوال إدارة المعدات والأقسام -------------------------------
def load_equipment_config():
    if not os.path.exists(EQUIPMENT_CONFIG_FILE):
        default_config = {}
        with open(EQUIPMENT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)
        return default_config
    try:
        with open(EQUIPMENT_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_equipment_config(config):
    try:
        with open(EQUIPMENT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"خطأ في حفظ تكوين المعدات: {e}")
        return False

def get_equipment_list_from_sheet(df):
    if df is None or df.empty or "المعدة" not in df.columns:
        return []
    equipment = df["المعدة"].dropna().unique()
    equipment = [str(e).strip() for e in equipment if str(e).strip() != ""]
    return sorted(equipment)
def get_available_sections(sheets_edit):
    """إرجاع قائمة الأقسام (الشيتات) التي تحتوي على ماكينات، مع استبعاد شيتات النظام"""
    sections = []
    for sheet_name, df in sheets_edit.items():
        if sheet_name in [APP_CONFIG["SPARE_PARTS_SHEET"], APP_CONFIG["MAINTENANCE_SHEET"]]:
            continue
        if "المعدة" in df.columns and not df["المعدة"].dropna().empty:
            sections.append(sheet_name)
    return sections
def add_equipment_to_sheet_data(sheets_edit, sheet_name, new_equipment):
    if sheet_name not in sheets_edit:
        return False, "القسم غير موجود"
    df = sheets_edit[sheet_name]
    if "المعدة" not in df.columns:
        return False, "عمود 'المعدة' غير موجود في هذا القسم"
    existing = get_equipment_list_from_sheet(df)
    if new_equipment in existing:
        return False, f"الماكينة '{new_equipment}' موجودة بالفعل في هذا القسم"
    new_row = {col: "" for col in df.columns}
    new_row["المعدة"] = new_equipment
    new_row_df = pd.DataFrame([new_row])
    sheets_edit[sheet_name] = pd.concat([df, new_row_df], ignore_index=True)
    return True, f"تم إضافة الماكينة '{new_equipment}' بنجاح إلى قسم {sheet_name}"

def remove_equipment_from_sheet_data(sheets_edit, sheet_name, equipment_name):
    if sheet_name not in sheets_edit:
        return False, "القسم غير موجود"
    df = sheets_edit[sheet_name]
    if "المعدة" not in df.columns:
        return False, "عمود 'المعدة' غير موجود"
    if equipment_name not in get_equipment_list_from_sheet(df):
        return False, "الماكينة غير موجودة"
    new_df = df[df["المعدة"] != equipment_name]
    sheets_edit[sheet_name] = new_df
    return True, f"تم حذف جميع سجلات الماكينة '{equipment_name}'"

def add_new_department(sheets_edit):
    st.subheader("➕ إضافة قسم جديد")
    st.info("سيتم إنشاء قسم جديد (شيت جديد) في ملف Excel لإدارة ماكينات هذا القسم")
    col1, col2 = st.columns(2)
    with col1:
        new_department_name = st.text_input("📝 اسم القسم الجديد:", key="new_department_name", placeholder="مثال: قسم الميكانيكا, قسم الكهرباء, محطة المياه")
        if new_department_name and new_department_name in sheets_edit:
            st.error(f"❌ القسم '{new_department_name}' موجود بالفعل!")
        elif new_department_name:
            st.success(f"✅ اسم القسم '{new_department_name}' متاح")
    with col2:
        st.markdown("#### 📋 إعدادات الأعمدة")
        use_default = st.checkbox("استخدام الأعمدة الافتراضية", value=True, key="use_default_columns")
        if use_default:
            columns_list = APP_CONFIG["DEFAULT_SHEET_COLUMNS"]
            st.info(f"📊 الأعمدة: {', '.join(columns_list)}")
        else:
            columns_text = st.text_area("✏️ الأعمدة (كل عمود في سطر):", value="\n".join(APP_CONFIG["DEFAULT_SHEET_COLUMNS"]), key="custom_columns", height=150)
            columns_list = [col.strip() for col in columns_text.split("\n") if col.strip()]
            if not columns_list:
                columns_list = APP_CONFIG["DEFAULT_SHEET_COLUMNS"]
    st.markdown("---")
    st.markdown("### 📋 معاينة القسم الجديد")
    preview_df = pd.DataFrame(columns=columns_list)
    st.dataframe(preview_df, use_container_width=True)
    st.caption(f"📊 عدد الأعمدة: {len(columns_list)} | سيتم إنشاء قسم فارغ بهذه الأعمدة")
    if st.button("✅ إنشاء وإضافة القسم الجديد", key="create_department_btn", type="primary", use_container_width=True):
        if not new_department_name:
            st.error("❌ الرجاء إدخال اسم القسم")
            return sheets_edit
        clean_name = re.sub(r'[\\/*?:"<>|]', '_', new_department_name.strip())
        if clean_name != new_department_name:
            st.warning(f"⚠ تم تعديل اسم القسم إلى: {clean_name}")
            new_department_name = clean_name
        if new_department_name in sheets_edit:
            st.error(f"❌ القسم '{new_department_name}' موجود بالفعل!")
            return sheets_edit
        new_df = pd.DataFrame(columns=columns_list)
        sheets_edit[new_department_name] = new_df
        if save_and_push_to_github(sheets_edit, f"إنشاء قسم جديد: {new_department_name}"):
            st.success(f"✅ تم إنشاء القسم '{new_department_name}' بنجاح!")
            st.cache_data.clear()
            st.balloons()
            st.rerun()
        else:
            st.error("❌ فشل حفظ القسم")
            return sheets_edit
    st.markdown("---")
    st.markdown("### 📋 الأقسام الموجودة حالياً:")
    if sheets_edit:
        for dept_name in sheets_edit.keys():
            if dept_name not in [APP_CONFIG["SPARE_PARTS_SHEET"], APP_CONFIG["MAINTENANCE_SHEET"]]:
                st.write(f"- 🏭 {dept_name}")
    else:
        st.info("لا توجد أقسام بعد")
    return sheets_edit

def add_new_machine(sheets_edit, sheet_name):
    st.markdown(f"### 🔧 إضافة ماكينة جديدة في قسم: {sheet_name}")
    df = sheets_edit[sheet_name]
    equipment_list = get_equipment_list_from_sheet(df)
    st.markdown(f"**الماكينات الموجودة حالياً في هذا القسم:**")
    if equipment_list:
        for eq in equipment_list:
            st.markdown(f"- 🔹 {eq}")
    else:
        st.info("لا توجد ماكينات مسجلة بعد في هذا القسم")
    st.markdown("---")
    new_machine = st.text_input("📝 اسم الماكينة الجديدة:", key=f"new_machine_{sheet_name}", placeholder="مثال: محرك رئيسي 1, مضخة مياه, ضاغط هواء")
    if st.button("➕ إضافة ماكينة", key=f"add_machine_{sheet_name}", type="primary"):
        if new_machine:
            success, msg = add_equipment_to_sheet_data(sheets_edit, sheet_name, new_machine)
            if success:
                if save_and_push_to_github(sheets_edit, f"إضافة ماكينة جديدة: {new_machine} في قسم {sheet_name}"):
                    st.success(msg)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("فشل الحفظ")
            else:
                st.error(msg)
        else:
            st.warning("يرجى إدخال اسم الماكينة")
    return sheets_edit

def manage_machines(sheets_edit, sheet_name):
    st.markdown(f"### 🔧 إدارة الماكينات في قسم: {sheet_name}")
    df = sheets_edit[sheet_name]
    equipment_list = get_equipment_list_from_sheet(df)
    if equipment_list:
        st.markdown("#### 📋 قائمة الماكينات في هذا القسم:")
        for eq in equipment_list:
            st.markdown(f"- 🔹 {eq}")
    else:
        st.info("لا توجد ماكينات مسجلة في هذا القسم بعد")
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        new_machine = st.text_input("➕ اسم الماكينة الجديدة:", key=f"new_machine_{sheet_name}")
        if st.button("➕ إضافة ماكينة", key=f"add_machine_{sheet_name}"):
            if new_machine:
                success, msg = add_equipment_to_sheet_data(sheets_edit, sheet_name, new_machine)
                if success:
                    if save_and_push_to_github(sheets_edit, f"إضافة ماكينة: {new_machine} في قسم {sheet_name}"):
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("فشل الحفظ")
                else:
                    st.error(msg)
            else:
                st.warning("يرجى إدخال اسم الماكينة")
    with col2:
        if equipment_list:
            machine_to_delete = st.selectbox("🗑️ اختر الماكينة للحذف:", equipment_list, key=f"delete_machine_{sheet_name}")
            st.warning("⚠️ تحذير: حذف الماكينة سيؤدي إلى حذف جميع سجلات الأعطال المرتبطة بها نهائياً!")
            if st.button("🗑️ حذف الماكينة نهائياً", key=f"delete_machine_btn_{sheet_name}"):
                success, msg = remove_equipment_from_sheet_data(sheets_edit, sheet_name, machine_to_delete)
                if success:
                    if save_and_push_to_github(sheets_edit, f"حذف ماكينة: {machine_to_delete} من قسم {sheet_name}"):
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("فشل الحفظ")
                else:
                    st.error(msg)

def add_new_event(sheets_edit, sheet_name):
    st.markdown(f"### 📝 إضافة حدث عطل جديد في قسم: {sheet_name}")
    df = sheets_edit[sheet_name]
    equipment_list = get_equipment_list_from_sheet(df)
    
    if not equipment_list:
        st.warning("⚠ لا توجد ماكينات مسجلة في هذا القسم. يرجى إضافة ماكينة أولاً من تبويب 'إدارة الماكينات'")
        return sheets_edit

    if "selected_equipment_temp" not in st.session_state:
        st.session_state.selected_equipment_temp = equipment_list[0] if equipment_list else ""
    
    selected_equipment = st.selectbox(
        "🔧 اختر الماكينة:",
        equipment_list,
        index=equipment_list.index(st.session_state.selected_equipment_temp) if st.session_state.selected_equipment_temp in equipment_list else 0,
        key="equipment_select"
    )
    if selected_equipment != st.session_state.selected_equipment_temp:
        st.session_state.selected_equipment_temp = selected_equipment
        st.rerun()
    
    spare_parts_list = get_spare_parts_for_equipment(selected_equipment)
    
    with st.form(key="add_event_form"):
        col1, col2 = st.columns(2)
        with col1:
            event_date = st.date_input("📅 التاريخ:", value=datetime.now())
            repair_duration = st.number_input("⏱️ مدة الإصلاح (ساعات):", min_value=0.0, step=0.5, format="%.1f")
            event_desc = st.text_area("📝 الحدث/العطل:", height=100)
            fault_type = st.selectbox("🏷️ نوع العطل:", ["", "ميكانيكي", "كهربائي", "إلكتروني", "هيدروليكي", "هوائي", "هيكلي", "آخر"])
            uploaded_image = st.file_uploader("🖼️ رفع صورة (اختياري):", type=APP_CONFIG["ALLOWED_IMAGE_TYPES"])
        with col2:
            correction_desc = st.text_area("🔧 الإجراء التصحيحي:", height=100)
            servised_by = st.text_input("👨‍🔧 تم بواسطة:")
            technician_rating = st.select_slider("⭐ قدرة الفني (حل/تفكير/مبادرة/قرار):", options=[1, 2, 3, 4, 5], value=3)
            safety_compliance = st.selectbox("🛡️ الالتزام بتعليمات السلامة:", ["", "ملتزم بالكامل", "ملتزم جزئياً", "غير ملتزم", "غير مطبق"])
            st.markdown("---")
            st.markdown("**🔩 قطع الغيار المستخدمة**")
            if spare_parts_list:
                part_names = [f"{name} (الرصيد: {qty})" for name, qty in spare_parts_list]
                selected_part_display = st.selectbox("اختر قطعة:", [""] + part_names, key="spare_part_select")
                if selected_part_display:
                    part_name = selected_part_display.split(" (")[0]
                    current_qty = next((qty for name, qty in spare_parts_list if name == part_name), 0)
                    st.caption(f"الرصيد الحالي: {current_qty}")
                    consume_qty = st.number_input("الكمية المستخدمة:", min_value=1, max_value=max(1, current_qty), value=1, step=1, key="consume_qty")
                    if consume_qty > current_qty:
                        st.error(f"⚠️ الرصيد غير كافٍ (الموجود {current_qty})")
                    else:
                        st.success(f"سيتم خصم {consume_qty} من الرصيد")
                else:
                    part_name = ""
                    consume_qty = 0
            else:
                st.info("لا توجد قطع غيار مسجلة لهذه الماكينة. يمكنك إضافتها من تبويب 'قطع الغيار'.")
                part_name = ""
                consume_qty = 0
        
        submitted = st.form_submit_button("✅ إضافة الحدث", type="primary")
        
        if submitted:
            spare_part_used = ""
            warning_msg = ""
            if part_name and consume_qty > 0:
                success, msg, new_qty = consume_spare_part(part_name, consume_qty)
                if success:
                    spare_part_used = f"{part_name} (كمية {consume_qty})"
                    critical_parts = get_critical_spare_parts()
                    for cp in critical_parts:
                        if cp["اسم القطعة"] == part_name:
                            warning_msg = f"⚠️ **تحذير:** القطعة '{part_name}' ضرورية وأصبح رصيدها {new_qty} (أقل من 1). يرجى إعادة التوريد."
                            break
                else:
                    st.error(msg)
                    return sheets_edit
            
            # معالجة الصورة
            image_url = None
            if uploaded_image is not None:
                event_id = str(uuid.uuid4())[:8]
                image_url = upload_image_to_github(uploaded_image, "event", event_id)
                if image_url:
                    st.success("✅ تم رفع الصورة بنجاح!")
                else:
                    st.warning("⚠️ فشل رفع الصورة، سيتم حفظ الحدث بدون صورة")
            
            new_row = {
                "مده الاصلاح": repair_duration if repair_duration > 0 else "",
                "التاريخ": event_date.strftime("%Y-%m-%d"),
                "المعدة": selected_equipment,
                "الحدث/العطل": event_desc,
                "الإجراء التصحيحي": correction_desc,
                "تم بواسطة": servised_by,
                "قطع غيار مستخدمة": spare_part_used,
                "نوع العطل": fault_type if fault_type else "",
                "قدرة الفني (حل/تفكير/مبادرة/قرار)": technician_rating,
                "الالتزام بتعليمات السلامة": safety_compliance if safety_compliance else "",
                "رابط الصورة": image_url or ""
            }
            for col in df.columns:
                if col not in new_row:
                    new_row[col] = ""
            new_row_df = pd.DataFrame([new_row])
            df_new = pd.concat([df, new_row_df], ignore_index=True)
            sheets_edit[sheet_name] = df_new
            
            if "temp_spare_parts_df" in st.session_state:
                sheets_edit[APP_CONFIG["SPARE_PARTS_SHEET"]] = st.session_state.temp_spare_parts_df
                del st.session_state.temp_spare_parts_df
            
            if save_and_push_to_github(sheets_edit, f"إضافة حدث عطل مع استخدام قطعة {part_name}"):
                st.cache_data.clear()
                st.success("✅ تم إضافة الحدث بنجاح ورفعه إلى GitHub!")
                if warning_msg:
                    st.warning(warning_msg)
                st.rerun()
            else:
                st.error("❌ فشل الحفظ")
    return sheets_edit

# ------------------------------- الجزء السادس: إدارة قطع الغيار، الصيانة الوقائية، والواجهة الرئيسية -------------------------------

def manage_spare_parts_tab(sheets_edit):
    st.header("📦 إدارة قطع الغيار")
    st.info("هنا يمكنك إضافة وتعديل قطع الغيار المرتبطة بكل ماكينة.")

    sections = get_available_sections(sheets_edit)
    if not sections:
        st.warning("⚠️ لا توجد أقسام بها ماكينات. أضف قسم وماكينات أولاً.")
        return sheets_edit

    selected_section = st.selectbox("🏭 اختر القسم:", sections, key="spare_section")
    df_section = sheets_edit[selected_section]
    equipment_list = get_equipment_list_from_sheet(df_section)
    if not equipment_list:
        st.warning(f"⚠️ لا توجد ماكينات في قسم '{selected_section}'.")
        return sheets_edit

    selected_equipment = st.selectbox("🔧 اختر الماكينة:", equipment_list, key="spare_equipment")

    spare_df = load_spare_parts()
    view_mode = st.radio("طريقة العرض:", ["جدول", "بطاقات مع الصور"], horizontal=True, key="spare_view_mode")

    st.subheader("📋 قائمة قطع الغيار")
    filtered_df = spare_df[spare_df["اسم الماكينة"] == selected_equipment].copy()
    filtered_df.reset_index(drop=False, inplace=True)
    filtered_df.rename(columns={'index': 'original_index'}, inplace=True)
    filtered_df["id"] = filtered_df.index

    if filtered_df.empty:
        st.info(f"لا توجد قطع غيار مسجلة للماكينة '{selected_equipment}'.")
    else:
        part_name_filter = st.text_input("فلتر حسب اسم القطعة:", placeholder="اكتب جزءاً من الاسم...", key="spare_name_filter")
        if part_name_filter:
            filtered_df = filtered_df[filtered_df["اسم القطعة"].str.contains(part_name_filter, case=False, na=False)]

        if view_mode == "جدول":
            display_cols = [c for c in filtered_df.columns if c not in ["original_index", "id", "رابط_الصورة"]]
            st.dataframe(filtered_df[display_cols], use_container_width=True)
            
            st.markdown("#### 🛠️ تعديل أو حذف قطعة")
            part_options = filtered_df["اسم القطعة"].tolist()
            selected_part_name = st.selectbox("اختر القطعة:", part_options, key="edit_part_name_select")
            if selected_part_name:
                part_row = filtered_df[filtered_df["اسم القطعة"] == selected_part_name].iloc[0]
                with st.expander(f"✏️ تعديل قطعة: {selected_part_name}"):
                    new_name = st.text_input("اسم القطعة", value=part_row["اسم القطعة"], key="edit_name")
                    new_size = st.text_input("المقاس", value=part_row["المقاس"], key="edit_size")
                    new_qty = st.number_input("الرصيد", value=int(part_row["الرصيد الموجود"]), step=1, key="edit_qty")
                    new_lead = st.text_input("مدة التوريد", value=part_row["مدة التوريد"], key="edit_lead")
                    new_critical = st.checkbox("قطعة ضرورية", value=(part_row["ضرورية"] == "نعم"), key="edit_critical")
                    if st.button("💾 حفظ التغييرات", key="save_edit_part"):
                        original_idx = part_row["original_index"]
                        spare_df.loc[original_idx, "اسم القطعة"] = new_name
                        spare_df.loc[original_idx, "المقاس"] = new_size
                        spare_df.loc[original_idx, "الرصيد الموجود"] = new_qty
                        spare_df.loc[original_idx, "مدة التوريد"] = new_lead
                        spare_df.loc[original_idx, "ضرورية"] = "نعم" if new_critical else "لا"
                        sheets_edit[APP_CONFIG["SPARE_PARTS_SHEET"]] = spare_df
                        if save_and_push_to_github(sheets_edit, f"تعديل قطعة: {selected_part_name}"):
                            st.success("تم التعديل")
                            st.rerun()
                
                if st.button("🗑️ حذف هذه القطعة", key="delete_part_btn"):
                    original_idx = part_row["original_index"]
                    spare_df = spare_df.drop(index=original_idx)
                    sheets_edit[APP_CONFIG["SPARE_PARTS_SHEET"]] = spare_df
                    if save_and_push_to_github(sheets_edit, f"حذف قطعة: {selected_part_name}"):
                        st.success("تم الحذف")
                        st.rerun()
        else:
            # وضع البطاقات مع أزرار تعديل وحذف
            cols_per_row = 2
            for i in range(0, len(filtered_df), cols_per_row):
                row_cols = st.columns(cols_per_row)
                for j, col in enumerate(row_cols):
                    idx = i + j
                    if idx < len(filtered_df):
                        row = filtered_df.iloc[idx]
                        with col:
                            with st.container(border=True):
                                img_url = row.get("رابط_الصورة", "")
                                if img_url and isinstance(img_url, str) and img_url.strip():
                                    try:
                                        st.image(img_url, use_container_width=True)
                                    except:
                                        st.write("🖼️ (تعذر عرض الصورة)")
                                else:
                                    st.write("📦 لا توجد صورة")
                                st.markdown(f"**🔩 {row['اسم القطعة']}**")
                                st.markdown(f"**المقاس:** {row['المقاس']}")
                                st.markdown(f"**الرصيد:** {row['الرصيد الموجود']}")
                                st.markdown(f"**ضرورية:** {row['ضرورية']}")
                                if row.get('مدة التوريد'):
                                    st.markdown(f"**مدة التوريد:** {row['مدة التوريد']}")
                                
                                col_btn1, col_btn2 = st.columns(2)
                                with col_btn1:
                                    if st.button("✏️ تعديل", key=f"edit_card_{row['id']}"):
                                        st.session_state[f"edit_mode_{row['id']}"] = True
                                with col_btn2:
                                    if st.button("🗑️ حذف", key=f"delete_card_{row['id']}"):
                                        original_idx = row["original_index"]
                                        spare_df = spare_df.drop(index=original_idx)
                                        sheets_edit[APP_CONFIG["SPARE_PARTS_SHEET"]] = spare_df
                                        if save_and_push_to_github(sheets_edit, f"حذف قطعة: {row['اسم القطعة']}"):
                                            st.success("تم الحذف")
                                            st.rerun()
                                
                                if st.session_state.get(f"edit_mode_{row['id']}", False):
                                    with st.form(key=f"edit_form_{row['id']}"):
                                        new_name = st.text_input("اسم القطعة", value=row['اسم القطعة'])
                                        new_size = st.text_input("المقاس", value=row['المقاس'])
                                        new_qty = st.number_input("الرصيد", value=int(row['الرصيد الموجود']))
                                        new_lead = st.text_input("مدة التوريد", value=row['مدة التوريد'])
                                        new_critical = st.checkbox("ضرورية", value=(row['ضرورية'] == "نعم"))
                                        if st.form_submit_button("💾 حفظ"):
                                            original_idx = row["original_index"]
                                            spare_df.loc[original_idx, "اسم القطعة"] = new_name
                                            spare_df.loc[original_idx, "المقاس"] = new_size
                                            spare_df.loc[original_idx, "الرصيد الموجود"] = new_qty
                                            spare_df.loc[original_idx, "مدة التوريد"] = new_lead
                                            spare_df.loc[original_idx, "ضرورية"] = "نعم" if new_critical else "لا"
                                            sheets_edit[APP_CONFIG["SPARE_PARTS_SHEET"]] = spare_df
                                            if save_and_push_to_github(sheets_edit, f"تعديل قطعة: {row['اسم القطعة']}"):
                                                st.success("تم التعديل")
                                                del st.session_state[f"edit_mode_{row['id']}"]
                                                st.rerun()
                                            else:
                                                st.error("فشل الحفظ")

    # إضافة قطعة جديدة (نفس الكود القديم)
    st.subheader("➕ إضافة قطعة غيار جديدة")
    with st.form(key="add_spare_part_form"):
        col1, col2 = st.columns(2)
        with col1:
            part_name = st.text_input("🔩 اسم القطعة:")
            part_size = st.text_input("📏 المقاس:")
            part_image = st.file_uploader("🖼️ صورة القطعة (اختياري):", type=APP_CONFIG["ALLOWED_IMAGE_TYPES"], key="spare_part_image")
        with col2:
            initial_qty = st.number_input("📦 الرصيد الموجود:", min_value=0, step=1, value=0)
            lead_time = st.text_input("⏱️ مدة التوريد (أيام أو نص):")
            is_critical = st.checkbox("⚠️ قطعة ضرورية")
        submitted = st.form_submit_button("✅ إضافة قطعة")
        if submitted:
            if not part_name:
                st.error("❌ الرجاء إدخال اسم القطعة")
            else:
                existing = spare_df[(spare_df["اسم القطعة"] == part_name) & (spare_df["اسم الماكينة"] == selected_equipment)]
                if not existing.empty:
                    st.error(f"❌ القطعة '{part_name}' موجودة بالفعل للماكينة '{selected_equipment}'")
                else:
                    image_url = None
                    if part_image is not None:
                        part_id = str(uuid.uuid4())[:8]
                        image_url = upload_image_to_github(part_image, "spare_part", part_id)
                        if image_url:
                            st.success("✅ تم رفع الصورة")
                        else:
                            st.warning("⚠️ فشل رفع الصورة")
                    new_row = pd.DataFrame([{
                        "اسم القطعة": part_name,
                        "المقاس": part_size,
                        "الرصيد الموجود": initial_qty,
                        "مدة التوريد": lead_time,
                        "ضرورية": "نعم" if is_critical else "لا",
                        "اسم الماكينة": selected_equipment,
                        "رابط_الصورة": image_url or ""
                    }])
                    new_spare_df = pd.concat([spare_df, new_row], ignore_index=True)
                    sheets_edit[APP_CONFIG["SPARE_PARTS_SHEET"]] = new_spare_df
                    if save_and_push_to_github(sheets_edit, f"إضافة قطعة غيار: {part_name} للماكينة {selected_equipment}"):
                        st.success("✅ تمت إضافة قطعة الغيار")
                        st.rerun()
                    else:
                        st.error("❌ فشل الحفظ")
    return sheets_edit
# ------------------------------- دوال مساعدة للصيانة الوقائية -------------------------------
def execute_maintenance_with_date(sheets_edit, equipment_name, task_name, execution_date, performed_by, used_spare_part="", used_quantity=1, image_url=None):
    """تنفيذ صيانة مع تحديد تاريخ التنفيذ واسم المنفذ (الفترة بالساعات)"""
    df = sheets_edit.get(APP_CONFIG["MAINTENANCE_SHEET"])
    if df is None:
        return False, "لا توجد مهام صيانة"
    mask = (df["المعدة"] == equipment_name) & (df["اسم_البند"] == task_name)
    if not mask.any():
        return False, "المهمة غير موجودة"
    idx = df[mask].index[0]
    period_days = df.loc[idx, "الفترة_بالأيام"]
    df.loc[idx, "آخر_تنفيذ"] = pd.to_datetime(execution_date)
    next_date = execution_date + timedelta(days=period_days)
    df.loc[idx, "التاريخ_التالي"] = next_date
    
    warning_msg = ""
    old_notes = df.loc[idx, "ملاحظات"]
    new_entry = f"{execution_date.strftime('%Y-%m-%d')} | تم بواسطة: {performed_by}"
    if used_spare_part and used_quantity > 0:
        success, msg, new_qty = consume_spare_part(used_spare_part, used_quantity)
        if not success:
            return False, f"فشل خصم قطعة الغيار: {msg}"
        new_entry += f" | استخدمت {used_spare_part} كمية {used_quantity} - {msg}"
        critical_parts = get_critical_spare_parts()
        for cp in critical_parts:
            if cp["اسم القطعة"] == used_spare_part:
                warning_msg = f"⚠️ **تحذير:** القطعة '{used_spare_part}' ضرورية وأصبح رصيدها {new_qty} (أقل من 1). يرجى إعادة التوريد."
                break
    if image_url:
        new_entry += f" | صورة: {image_url}"
    df.loc[idx, "ملاحظات"] = (old_notes + "\n" + new_entry) if old_notes else new_entry
    sheets_edit[APP_CONFIG["MAINTENANCE_SHEET"]] = df
    return True, f"تم تنفيذ الصيانة '{task_name}' بتاريخ {execution_date.strftime('%Y-%m-%d')} بواسطة {performed_by}. التاريخ التالي: {next_date.strftime('%Y-%m-%d')}" + (f" {warning_msg}" if warning_msg else "")

def add_maintenance_as_event(sheets_edit, equipment_name, task_name, execution_date, performed_by, used_spare_part="", used_quantity=1, image_url=None):
    """إضافة سجل في جدول الأعطال لتسجيل تنفيذ الصيانة مع اسم المنفذ"""
    target_sheet = None
    target_df = None
    for sheet_name, df in sheets_edit.items():
        if sheet_name not in [APP_CONFIG["SPARE_PARTS_SHEET"], APP_CONFIG["MAINTENANCE_SHEET"]]:
            if equipment_name in get_equipment_list_from_sheet(df):
                target_sheet = sheet_name
                target_df = df
                break
    if target_sheet is None:
        return False, f"لم يتم العثور على قسم يحتوي على المعدة '{equipment_name}'"
    
    spare_part_used = f"{used_spare_part} (كمية {used_quantity})" if used_spare_part else ""
    new_row = {
        "مده الاصلاح": 0,
        "التاريخ": execution_date.strftime("%Y-%m-%d"),
        "المعدة": equipment_name,
        "الحدث/العطل": f"صيانة وقائية: {task_name}",
        "الإجراء التصحيحي": f"تم تنفيذ الصيانة الدورية '{task_name}' بواسطة {performed_by}",
        "تم بواسطة": performed_by,
        "قطع غيار مستخدمة": spare_part_used,
        "نوع العطل": "صيانة وقائية",
        "قدرة الفني (حل/تفكير/مبادرة/قرار)": 5,
        "الالتزام بتعليمات السلامة": "ملتزم بالكامل",
        "رابط الصورة": image_url or ""
    }
    for col in target_df.columns:
        if col not in new_row:
            new_row[col] = ""
    new_row_df = pd.DataFrame([new_row])
    sheets_edit[target_sheet] = pd.concat([target_df, new_row_df], ignore_index=True)
    return True, f"تم تسجيل الصيانة كحدث في قسم '{target_sheet}' بواسطة {performed_by}"


# ------------------------------- تبويب الصيانة الوقائية -------------------------------
def preventive_maintenance_tab(sheets_edit):
    st.header("🛠 الصيانة الوقائية")
    st.info("إدارة بنود الصيانة الدورية. يمكنك تنفيذ الصيانة يدوياً مع تحديد تاريخ واسم المنفذ، وسيتم تحديث التاريخ التالي تلقائياً.")

    sections = get_available_sections(sheets_edit)
    if not sections:
        st.warning("⚠️ لا توجد أقسام بها ماكينات. أضف قسم وماكينات أولاً.")
        return sheets_edit

    selected_section = st.selectbox("🏭 اختر القسم:", sections, key="pm_section")
    df_section = sheets_edit[selected_section]
    equipment_list = get_equipment_list_from_sheet(df_section)
    if not equipment_list:
        st.warning(f"⚠️ لا توجد ماكينات في قسم '{selected_section}'.")
        return sheets_edit

    selected_equipment = st.selectbox("🔧 اختر المعدة:", equipment_list, key="pm_equipment")

    tasks_df = get_tasks_for_equipment(selected_equipment)
    if tasks_df.empty:
        st.info("لا توجد بنود صيانة مسجلة لهذه المعدة. يمكنك إضافة بند جديد أدناه.")
    else:
        view_mode = st.radio("طريقة العرض:", ["جدول", "بطاقات مع الصور"], horizontal=True, key="maintenance_view_mode")
        today = datetime.now().date()
        tasks_display = tasks_df.copy().reset_index(drop=False)  # نحتفظ بالفهرس الأصلي كعمود 'index'
        tasks_display.rename(columns={'index': 'original_index'}, inplace=True)
        tasks_display["id"] = tasks_display.index

        def days_remaining(row):
            if pd.isna(row["التاريخ_التالي"]):
                return "غير محدد"
            return (row["التاريخ_التالي"].date() - today).days

        tasks_display["الأيام_المتبقية"] = tasks_display.apply(days_remaining, axis=1)
        tasks_display["الحالة"] = tasks_display["الأيام_المتبقية"].apply(
            lambda x: "🔴 متأخرة" if (isinstance(x, int) and x < 0) else ("🟡 قادمة" if (isinstance(x, int) and x <= 3) else "🟢 جيدة")
        )
        tasks_display["عدد_الصيانات"] = tasks_display["آخر_تنفيذ"].apply(lambda x: 1 if pd.notna(x) else 0)

        if view_mode == "جدول":
            cols_to_show = ["نوع_الصيانة", "اسم_البند", "الفترة_بالأيام", "آخر_تنفيذ", "التاريخ_التالي", "الأيام_المتبقية", "الحالة", "عدد_الصيانات", "ملاحظات"]
            st.dataframe(tasks_display[cols_to_show], use_container_width=True)
            
            st.markdown("#### 🛠️ تعديل أو حذف بند صيانة")
            task_options = tasks_display["اسم_البند"].tolist()
            selected_task_name = st.selectbox("اختر البند:", task_options, key="edit_task_select")
            if selected_task_name:
                task_row = tasks_display[tasks_display["اسم_البند"] == selected_task_name].iloc[0]
                with st.expander(f"✏️ تعديل بند: {selected_task_name}"):
                    new_name = st.text_input("اسم البند", value=task_row["اسم_البند"], key="edit_task_name")
                    new_period_hours = st.number_input("عدد الساعات بين الصيانة", min_value=1, value=int(task_row["الفترة_بالأيام"]*24), key="edit_period_hours")
                    new_notes = st.text_area("ملاحظات", value=task_row["ملاحظات"], key="edit_task_notes")
                    if st.button("💾 حفظ التغييرات", key="save_task_edit"):
                        original_idx = task_row["original_index"]
                        new_period_days = new_period_hours / 24.0
                        tasks_df.loc[original_idx, "اسم_البند"] = new_name
                        tasks_df.loc[original_idx, "الفترة_بالأيام"] = new_period_days
                        tasks_df.loc[original_idx, "نوع_الصيانة"] = f"{new_period_hours} ساعة"
                        tasks_df.loc[original_idx, "ملاحظات"] = new_notes
                        last_exec = tasks_df.loc[original_idx, "آخر_تنفيذ"]
                        if pd.notna(last_exec):
                            tasks_df.loc[original_idx, "التاريخ_التالي"] = last_exec + timedelta(days=new_period_days)
                        sheets_edit[APP_CONFIG["MAINTENANCE_SHEET"]] = tasks_df
                        if save_and_push_to_github(sheets_edit, f"تعديل بند صيانة: {selected_task_name}"):
                            st.success("تم التعديل")
                            st.rerun()
                
                if st.button("🗑️ حذف هذا البند", key="delete_task_btn"):
                    original_idx = task_row["original_index"]
                    tasks_df = tasks_df.drop(index=original_idx)
                    sheets_edit[APP_CONFIG["MAINTENANCE_SHEET"]] = tasks_df
                    if save_and_push_to_github(sheets_edit, f"حذف بند صيانة: {selected_task_name}"):
                        st.success("تم الحذف")
                        st.rerun()
        else:
            # عرض البطاقات
            cols_per_row = 2
            for i in range(0, len(tasks_display), cols_per_row):
                row_cols = st.columns(cols_per_row)
                for j, col in enumerate(row_cols):
                    idx = i + j
                    if idx < len(tasks_display):
                        row = tasks_display.iloc[idx]
                        with col:
                            with st.container(border=True):
                                img_url = row.get("رابط_الصورة", "")
                                if img_url and isinstance(img_url, str) and img_url.strip():
                                    try:
                                        st.image(img_url, use_container_width=True)
                                    except:
                                        st.write("🖼️ (تعذر عرض الصورة)")
                                else:
                                    st.write("🔧 لا توجد صورة")
                                st.markdown(f"**{row['اسم_البند']}**")
                                st.markdown(f"**نوع الصيانة:** {row['نوع_الصيانة']}")
                                st.markdown(f"**الفترة:** {row['الفترة_بالأيام']:.2f} يوم")
                                st.markdown(f"**آخر تنفيذ:** {row['آخر_تنفيذ'].strftime('%Y-%m-%d') if pd.notna(row['آخر_تنفيذ']) else 'لم تنفذ بعد'}")
                                st.markdown(f"**التاريخ التالي:** {row['التاريخ_التالي'].strftime('%Y-%m-%d') if pd.notna(row['التاريخ_التالي']) else 'غير محدد'}")
                                st.markdown(f"**الحالة:** {row['الحالة']}")
                                
                                col_btn1, col_btn2 = st.columns(2)
                                with col_btn1:
                                    if st.button("✏️ تعديل", key=f"edit_task_card_{row['id']}"):
                                        st.session_state[f"edit_task_mode_{row['id']}"] = True
                                with col_btn2:
                                    if st.button("🗑️ حذف", key=f"delete_task_card_{row['id']}"):
                                        original_idx = row["original_index"]
                                        tasks_df = tasks_df.drop(index=original_idx)
                                        sheets_edit[APP_CONFIG["MAINTENANCE_SHEET"]] = tasks_df
                                        if save_and_push_to_github(sheets_edit, f"حذف بند صيانة: {row['اسم_البند']}"):
                                            st.success("تم الحذف")
                                            st.rerun()
                                
                                if st.session_state.get(f"edit_task_mode_{row['id']}", False):
                                    with st.form(key=f"edit_task_form_{row['id']}"):
                                        new_name = st.text_input("اسم البند", value=row['اسم_البند'])
                                        new_period_hours = st.number_input("عدد الساعات", min_value=1, value=int(row['الفترة_بالأيام']*24))
                                        new_notes = st.text_area("ملاحظات", value=row['ملاحظات'])
                                        if st.form_submit_button("💾 حفظ"):
                                            original_idx = row["original_index"]
                                            new_period_days = new_period_hours / 24.0
                                            tasks_df.loc[original_idx, "اسم_البند"] = new_name
                                            tasks_df.loc[original_idx, "الفترة_بالأيام"] = new_period_days
                                            tasks_df.loc[original_idx, "نوع_الصيانة"] = f"{new_period_hours} ساعة"
                                            tasks_df.loc[original_idx, "ملاحظات"] = new_notes
                                            last_exec = tasks_df.loc[original_idx, "آخر_تنفيذ"]
                                            if pd.notna(last_exec):
                                                tasks_df.loc[original_idx, "التاريخ_التالي"] = last_exec + timedelta(days=new_period_days)
                                            sheets_edit[APP_CONFIG["MAINTENANCE_SHEET"]] = tasks_df
                                            if save_and_push_to_github(sheets_edit, f"تعديل بند صيانة: {row['اسم_البند']}"):
                                                st.success("تم التعديل")
                                                del st.session_state[f"edit_task_mode_{row['id']}"]
                                                st.rerun()
                                            else:
                                                st.error("فشل الحفظ")

        # تنفيذ صيانة (نفس الكود السابق لكن مع التأكد من وجود المتغيرات)
        st.markdown("---")
        st.subheader("✅ تنفيذ صيانة")
        task_options = tasks_df["اسم_البند"].tolist()
        if not task_options:
            st.info("لا توجد بنود صيانة لتنفيذها.")
        else:
            selected_task = st.selectbox("اختر البند المنفذ:", task_options, key="execute_task_select")
            if selected_task:
                execution_date = st.date_input("📅 تاريخ التنفيذ:", value=datetime.now().date(), key="execution_date_input")
                performed_by = st.text_input("👨‍🔧 تم بواسطة:", key="maintenance_performed_by", placeholder="اسم الشخص الذي نفذ الصيانة")
                spare_parts_list = get_spare_parts_for_equipment(selected_equipment)
                st.markdown("**🔩 استهلاك قطع غيار (اختياري)**")
                part_name = ""
                consume_qty = 0
                use_part = True
                if spare_parts_list:
                    part_names = [""] + [f"{name} (الرصيد: {qty})" for name, qty in spare_parts_list]
                    selected_part_display = st.selectbox("اختر قطعة:", part_names, key="pm_spare_part")
                    if selected_part_display:
                        part_name = selected_part_display.split(" (")[0]
                        current_qty = next((qty for name, qty in spare_parts_list if name == part_name), 0)
                        st.caption(f"الرصيد الحالي: {current_qty}")
                        consume_qty = st.number_input("الكمية المستخدمة:", min_value=1, max_value=max(1, current_qty), value=1, step=1, key="pm_consume_qty")
                        if consume_qty > current_qty:
                            st.error(f"⚠️ الرصيد غير كافٍ")
                            use_part = False
                else:
                    st.info("لا توجد قطع غيار مسجلة لهذه المعدة")

                execution_image = st.file_uploader("🖼️ رفع صورة للصيانة المنفذة (اختياري):", type=APP_CONFIG["ALLOWED_IMAGE_TYPES"], key="maintenance_execution_image")
                link_to_event = st.checkbox("🔗 تسجيل هذه الصيانة كحدث عطل", value=False)

                if st.button("✅ تم تنفيذ الصيانة", type="primary"):
                    if not performed_by:
                        st.error("❌ الرجاء إدخال اسم المنفذ")
                    elif not use_part:
                        st.error("لا يمكن التنفيذ بسبب نقص الرصيد")
                    else:
                        image_url = None
                        if execution_image:
                            maint_id = str(uuid.uuid4())[:8]
                            image_url = upload_image_to_github(execution_image, "maintenance_execution", maint_id)
                        success, msg = execute_maintenance_with_date(sheets_edit, selected_equipment, selected_task, execution_date, performed_by, part_name, consume_qty, image_url)
                        if success:
                            if link_to_event:
                                event_success, event_msg = add_maintenance_as_event(sheets_edit, selected_equipment, selected_task, execution_date, performed_by, part_name, consume_qty, image_url)
                                if event_success:
                                    st.success(f"✅ {msg} وتم تسجيله كحدث عطل")
                                else:
                                    st.warning(f"✅ {msg} لكن فشل تسجيل الحدث: {event_msg}")
                            else:
                                st.success(msg)
                            if "temp_spare_parts_df" in st.session_state:
                                sheets_edit[APP_CONFIG["SPARE_PARTS_SHEET"]] = st.session_state.temp_spare_parts_df
                                del st.session_state.temp_spare_parts_df
                            if save_and_push_to_github(sheets_edit, f"تنفيذ صيانة '{selected_task}' لـ {selected_equipment} بواسطة {performed_by}"):
                                st.rerun()
                        else:
                            st.error(msg)

    # إضافة بند صيانة جديد
    st.markdown("---")
    st.subheader("➕ إضافة بند صيانة جديد")
    with st.form(key="add_maintenance_form"):
        col1, col2 = st.columns(2)
        with col1:
            task_name = st.text_input("اسم البند:")
            period_hours = st.number_input("⏱️ عدد الساعات بين الصيانة:", min_value=1, step=1, value=24)
            st.caption(f"✅ الفترة: {period_hours} ساعة = {period_hours/24:.2f} يوم")
            use_custom_start = st.checkbox("📅 تحديد تاريخ بدء الصيانة", value=False)
            if use_custom_start:
                start_date = st.date_input("تاريخ البدء:", value=datetime.now().date(), key="maintenance_start_date")
            else:
                start_date = None
            task_image = st.file_uploader("🖼️ صورة توضيحية:", type=APP_CONFIG["ALLOWED_IMAGE_TYPES"], key="maintenance_task_image")
        with col2:
            notes = st.text_area("ملاحظات:")
            default_spare = st.text_input("قطعة غيار افتراضية:", placeholder="اختياري")
        submitted = st.form_submit_button("➕ إضافة بند صيانة")
        if submitted:
            if not task_name:
                st.error("❌ الرجاء إدخال اسم البند")
            else:
                image_url = None
                if task_image:
                    task_id = str(uuid.uuid4())[:8]
                    image_url = upload_image_to_github(task_image, "maintenance_task", task_id)
                sheets_edit = add_maintenance_task(sheets_edit, selected_equipment, task_name, period_hours, start_date, notes, default_spare, image_url)
                if save_and_push_to_github(sheets_edit, f"إضافة بند صيانة '{task_name}'"):
                    st.success("✅ تم إضافة البند بنجاح")
                    st.rerun()
                else:
                    st.error("❌ فشل الحفظ")
    return sheets_edit

# ------------------------------- دالة إدارة البيانات الرئيسية -------------------------------
def manage_data_edit(sheets_edit):
    if sheets_edit is None:
        st.warning("الملف غير موجود. استخدم زر 'تحديث من GitHub' في الشريط الجانبي أولاً")
        return sheets_edit
    if APP_CONFIG["SPARE_PARTS_SHEET"] not in sheets_edit:
        sheets_edit[APP_CONFIG["SPARE_PARTS_SHEET"]] = load_spare_parts()
    if APP_CONFIG["MAINTENANCE_SHEET"] not in sheets_edit:
        sheets_edit[APP_CONFIG["MAINTENANCE_SHEET"]] = load_maintenance_tasks()
    
    tab_names = ["📋 عرض الأقسام", "📝 إضافة حدث عطل", "🔧 إدارة الماكينات", "➕ إضافة قسم جديد", "📦 قطع الغيار", "🛠 الصيانة الوقائية"]
    tabs_edit = st.tabs(tab_names)
    with tabs_edit[0]:
        st.subheader("جميع الأقسام")
        if sheets_edit:
            dept_names = [name for name in sheets_edit.keys() if name not in [APP_CONFIG["SPARE_PARTS_SHEET"], APP_CONFIG["MAINTENANCE_SHEET"]]]
            if dept_names:
                dept_tabs = st.tabs(dept_names)
                for i, dept_name in enumerate(dept_names):
                    with dept_tabs[i]:
                        df = sheets_edit[dept_name]
                        display_sheet_data(dept_name, df, f"view_{dept_name}", sheets_edit)
                        with st.expander("✏️ تعديل مباشر للبيانات", expanded=False):
                            edited_df = st.data_editor(df.astype(str), num_rows="dynamic", use_container_width=True, key=f"editor_{dept_name}")
                            if st.button(f"💾 حفظ", key=f"save_{dept_name}"):
                                sheets_edit[dept_name] = edited_df.astype(object)
                                if save_and_push_to_github(sheets_edit, f"تعديل بيانات في قسم {dept_name}"):
                                    st.cache_data.clear()
                                    st.success("تم الحفظ والرفع إلى GitHub!")
                                    st.rerun()
            else:
                st.info("لا توجد أقسام بعد")
    with tabs_edit[1]:
        if sheets_edit:
            sheet_name = st.selectbox("اختر القسم:", [name for name in sheets_edit.keys() if name not in [APP_CONFIG["SPARE_PARTS_SHEET"], APP_CONFIG["MAINTENANCE_SHEET"]]], key="add_event_sheet")
            sheets_edit = add_new_event(sheets_edit, sheet_name)
    with tabs_edit[2]:
        if sheets_edit:
            sheet_name = st.selectbox("اختر القسم:", [name for name in sheets_edit.keys() if name not in [APP_CONFIG["SPARE_PARTS_SHEET"], APP_CONFIG["MAINTENANCE_SHEET"]]], key="manage_machines_sheet")
            manage_machines(sheets_edit, sheet_name)
    with tabs_edit[3]:
        sheets_edit = add_new_department(sheets_edit)
    with tabs_edit[4]:
        sheets_edit = manage_spare_parts_tab(sheets_edit)
    with tabs_edit[5]:
        sheets_edit = preventive_maintenance_tab(sheets_edit)
    return sheets_edit


# ------------------------------- الواجهة الرئيسية -------------------------------
# ------------------------------- الواجهة الرئيسية -------------------------------
with st.sidebar:
    st.header("الجلسة")
    if not st.session_state.get("logged_in"):
        if not login_ui():
            st.stop()
    else:
        state = cleanup_sessions(load_state())
        username = st.session_state.username
        rem = remaining_time(state, username)
        if rem:
            mins, secs = divmod(int(rem.total_seconds()), 60)
            st.success(f"👋 {username} | ⏳ {mins:02d}:{secs:02d}")
        st.markdown("---")
        if st.button("🔄 تحديث من GitHub"):
            if fetch_from_github_requests():
                st.rerun()
        if st.button("🗑 مسح الكاش"):
            st.cache_data.clear()
            st.rerun()
        if st.button("🚪 تسجيل الخروج"):
            logout_action()
        # تم إزالة أقسام الإشعارات من الشريط الجانبي

all_sheets = load_all_sheets()
sheets_edit = load_sheets_for_edit()

st.title(f"{APP_CONFIG['APP_ICON']} {APP_CONFIG['APP_TITLE']}")

user_role = st.session_state.get("user_role", "viewer")
user_permissions = st.session_state.get("user_permissions", ["view"])
can_edit = (user_role == "admin" or user_role == "editor" or "edit" in user_permissions)

# إضافة تبويب الإشعارات
tabs_list = ["🔍 بحث متقدم", "📊 تحليل الأعطال", "🔔 الإشعارات"]
if can_edit:
    tabs_list.append("🛠 تعديل وإدارة البيانات")

tabs = st.tabs(tabs_list)

with tabs[0]:
    search_across_sheets(all_sheets)

with tabs[1]:
    failures_analysis_tab(all_sheets)

with tabs[2]:
    st.header("🔔 الإشعارات")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("⚠️ قطع غيار حرجة")
        critical = get_critical_spare_parts()
        if critical:
            for part in critical:
                st.error(f"🔴 **{part['اسم القطعة']}** (ماكينة: {part['اسم الماكينة']}) - الرصيد: {part['الرصيد الموجود']} < حد الإنذار: {part['حد_الإنذار']}")
        else:
            st.success("✅ لا توجد قطع غيار حرجة")
    with col2:
        st.subheader("🔧 صيانة مستحقة")
        overdue, upcoming = get_upcoming_maintenance(3)
        if not overdue.empty:
            st.warning("🟡 صيانة متأخرة:")
            for _, row in overdue.iterrows():
                st.write(f"- {row['المعدة']}: {row['اسم_البند']} (تاريخ مستحق: {row['التاريخ_التالي'].strftime('%Y-%m-%d')})")
        else:
            st.info("✅ لا توجد صيانات متأخرة")
        if not upcoming.empty:
            st.info("🟢 صيانة قادمة خلال 3 أيام:")
            for _, row in upcoming.iterrows():
                days = (row['التاريخ_التالي'].date() - datetime.now().date()).days
                st.write(f"- {row['المعدة']}: {row['اسم_البند']} (بعد {days} يوم)")
        else:
            st.info("✅ لا توجد صيانات قادمة")

if can_edit and len(tabs) > 3:  # إذا كان هناك تبويب إدارة البيانات (الرابع)
    with tabs[3]:
        sheets_edit = manage_data_edit(sheets_edit)

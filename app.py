import streamlit as st
import pandas as pd
import numpy as np
import json
import os
import requests
import shutil
import re
from datetime import datetime, timedelta
from base64 import b64decode
import uuid
import io

# محاولة استيراد Plotly مع معالجة الخطأ
try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
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

try:
    from github import Github, GithubException
    GITHUB_AVAILABLE = True
except Exception:
    GITHUB_AVAILABLE = False

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
    "DEFAULT_SHEET_COLUMNS": ["التاريخ", "المعدة", "الحدث/العطل", "الإجراء التصحيحي", "تم بواسطة", "الطن", "الصور", "ملاحظات"],
}

USERS_FILE = "users.json"
STATE_FILE = "state.json"
SESSION_DURATION = timedelta(minutes=APP_CONFIG["SESSION_DURATION_MINUTES"])
MAX_ACTIVE_USERS = APP_CONFIG["MAX_ACTIVE_USERS"]
IMAGES_FOLDER = APP_CONFIG["IMAGES_FOLDER"]
EQUIPMENT_CONFIG_FILE = "equipment_config.json"

GITHUB_EXCEL_URL = f"https://github.com/{APP_CONFIG['REPO_NAME'].split('/')[0]}/{APP_CONFIG['REPO_NAME'].split('/')[1]}/raw/{APP_CONFIG['BRANCH']}/{APP_CONFIG['FILE_PATH']}"
GITHUB_USERS_URL = "https://raw.githubusercontent.com/mahmedabdallh123/stations/refs/heads/main/users.json"
GITHUB_REPO_USERS = "mahmedabdallh123/stations"

# ------------------------------- دوال تحليل الأعطال -------------------------------
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
    
    return {
        "total_failures": total_failures,
        "unique_equipment": unique_equipment,
        "date_range": {
            "from": data["التاريخ"].min().strftime("%Y-%m-%d"),
            "to": data["التاريخ"].max().strftime("%Y-%m-%d")
        },
        "failure_rate": failure_rate,
        "issue_counts": issue_counts,
        "mtbf": mtbf_df,
        "monthly": monthly_failures,
        "weekday": weekday_failures,
        "correction_counts": correction_counts,
        "raw_data": data
    }

def generate_excel_report(analysis, sheet_name, equipment_filter):
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_data = {
            "المعيار": ["إجمالي الأعطال", "عدد المعدات", "فترة التحليل من", "فترة التحليل إلى", "المعدة المفلترة"],
            "القيمة": [
                analysis["total_failures"],
                analysis["unique_equipment"],
                analysis["date_range"]["from"],
                analysis["date_range"]["to"],
                equipment_filter if equipment_filter else "جميع المعدات"
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name="الملخص", index=False)
        
        if not analysis["failure_rate"].empty:
            analysis["failure_rate"].to_excel(writer, sheet_name="معدل تكرار الأعطال", index=False)
        
        if not analysis["issue_counts"].empty:
            analysis["issue_counts"].to_excel(writer, sheet_name="أكثر الأعطال تكراراً", index=False)
        
        if not analysis["mtbf"].empty:
            analysis["mtbf"].to_excel(writer, sheet_name="متوسط الوقت بين الأعطال (MTBF)", index=False)
        
        if not analysis["monthly"].empty:
            pivot_monthly = analysis["monthly"].pivot(index="الشهر", columns="المعدة", values="عدد الأعطال").fillna(0)
            pivot_monthly.to_excel(writer, sheet_name="التحليل الشهري")
        
        if not analysis["weekday"].empty:
            analysis["weekday"].to_excel(writer, sheet_name="تحليل أيام الأسبوع", index=False)
        
        if not analysis["correction_counts"].empty:
            analysis["correction_counts"].to_excel(writer, sheet_name="الإجراءات التصحيحية", index=False)
        
        raw_export = analysis["raw_data"][["التاريخ", "المعدة", "الحدث/العطل", "الإجراء التصحيحي", "تم بواسطة", "الطن", "ملاحظات"]].copy()
        raw_export.to_excel(writer, sheet_name="البيانات الخام", index=False)
    
    output.seek(0)
    return output

# ------------------------------- دوال تصدير البيانات -------------------------------
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

# ------------------------------- دوال إدارة المعدات -------------------------------
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

def add_equipment_to_sheet_data(sheets_edit, sheet_name, new_equipment):
    if sheet_name not in sheets_edit:
        return False, "الشيت غير موجود"
    
    df = sheets_edit[sheet_name]
    if "المعدة" not in df.columns:
        return False, "عمود 'المعدة' غير موجود في هذا الشيت"
    
    existing = get_equipment_list_from_sheet(df)
    if new_equipment in existing:
        return False, f"المعدة '{new_equipment}' موجودة بالفعل"
    
    new_row = {col: "" for col in df.columns}
    new_row["المعدة"] = new_equipment
    new_row_df = pd.DataFrame([new_row])
    sheets_edit[sheet_name] = pd.concat([df, new_row_df], ignore_index=True)
    
    return True, f"تم إضافة المعدة '{new_equipment}' بنجاح"

def remove_equipment_from_sheet_data(sheets_edit, sheet_name, equipment_name):
    if sheet_name not in sheets_edit:
        return False, "الشيت غير موجود"
    df = sheets_edit[sheet_name]
    if "المعدة" not in df.columns:
        return False, "عمود 'المعدة' غير موجود"
    if equipment_name not in get_equipment_list_from_sheet(df):
        return False, "المعدة غير موجودة"
    
    new_df = df[df["المعدة"] != equipment_name]
    sheets_edit[sheet_name] = new_df
    return True, f"تم حذف جميع سجلات المعدة '{equipment_name}'"

# ------------------------------- دوال المستخدمين -------------------------------
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

# ------------------------------- دوال الملفات (المعدلة) -------------------------------
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
        st.error(f"خطأ في تحميل الشيتات: {e}")
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
        st.error(f"خطأ في تحميل الشيتات: {e}")
        return None

def save_excel_locally(sheets_dict):
    """حفظ ملف Excel محلياً فقط"""
    try:
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
    """رفع الملف المحلي إلى GitHub"""
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
            result = repo.update_file(
                path=APP_CONFIG["FILE_PATH"],
                message=f"تحديث البيانات - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                content=content,
                sha=contents.sha,
                branch=APP_CONFIG["BRANCH"]
            )
            st.success(f"✅ تم رفع التغييرات إلى GitHub بنجاح!")
            return True
        except GithubException as e:
            if e.status == 404:
                result = repo.create_file(
                    path=APP_CONFIG["FILE_PATH"],
                    message=f"إنشاء ملف جديد - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    content=content,
                    branch=APP_CONFIG["BRANCH"]
                )
                st.success(f"✅ تم إنشاء الملف على GitHub بنجاح!")
                return True
            else:
                st.error(f"❌ خطأ في GitHub: {e}")
                return False
    except Exception as e:
        st.error(f"❌ فشل الرفع إلى GitHub: {str(e)}")
        return False

def save_and_push_to_github(sheets_dict, operation_name):
    """حفظ محلياً ثم رفع إلى GitHub"""
    st.info(f"💾 جاري حفظ {operation_name}...")
    
    if save_excel_locally(sheets_dict):
        st.success("✅ تم الحفظ محلياً")
        
        if push_to_github():
            st.success("✅ تم الرفع إلى GitHub")
            st.cache_data.clear()
            return True
        else:
            st.warning("⚠️ تم الحفظ محلياً فقط، فشل الرفع إلى GitHub")
            return True
    else:
        st.error("❌ فشل الحفظ المحلي")
        return False

# ------------------------------- دوال العرض -------------------------------
def display_sheet_data(sheet_name, df, unique_id, sheets_edit):
    st.markdown(f"### {sheet_name}")
    st.info(f"عدد السجلات: {len(df)} | عدد الأعمدة: {len(df.columns)}")
    
    equipment_list = get_equipment_list_from_sheet(df)
    if equipment_list and "المعدة" in df.columns:
        st.markdown("#### فلتر حسب المعدة:")
        selected_filter = st.selectbox(
            "اختر المعدة:", 
            ["جميع المعدات"] + equipment_list,
            key=f"filter_{unique_id}"
        )
        if selected_filter != "جميع المعدات":
            df = df[df["المعدة"] == selected_filter]
            st.info(f"عرض للمعدة: {selected_filter} - السجلات: {len(df)}")
    
    display_df = df.copy()
    for col in display_df.columns:
        if display_df[col].dtype == 'object':
            display_df[col] = display_df[col].astype(str).apply(lambda x: x[:100] + "..." if len(x) > 100 else x)
    st.dataframe(display_df, use_container_width=True, height=400)
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        excel_file = export_sheet_to_excel({sheet_name: df}, sheet_name)
        st.download_button(
            "📥 تحميل هذا الشيت كملف Excel",
            excel_file,
            f"{sheet_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"export_sheet_{unique_id}"
        )
    with col_btn2:
        all_sheets_excel = export_all_sheets_to_excel({sheet_name: df})
        st.download_button(
            "📥 تحميل جميع البيانات كملف Excel",
            all_sheets_excel,
            f"all_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"export_all_{unique_id}"
        )

def search_across_sheets(all_sheets):
    st.subheader("بحث متقدم في السجلات")
    
    if not all_sheets:
        st.warning("لا توجد بيانات للبحث")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        sheet_options = ["جميع الشيتات"] + list(all_sheets.keys())
        selected_sheet = st.selectbox("اختر الشيت للبحث:", sheet_options, key="search_sheet")
        
        if selected_sheet != "جميع الشيتات":
            df_temp = all_sheets[selected_sheet]
            equipment_list = get_equipment_list_from_sheet(df_temp)
        else:
            all_eq = set()
            for sh_name, sh_df in all_sheets.items():
                all_eq.update(get_equipment_list_from_sheet(sh_df))
            equipment_list = sorted(all_eq)
        
        filter_equipment = st.selectbox("فلتر حسب المعدة:", ["الكل"] + equipment_list, key="search_eq")
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
        search_in_notes = st.checkbox("البحث في الملاحظات أيضاً", value=True, key="search_notes")
    
    if st.button("بحث", key="search_btn", type="primary"):
        results = []
        sheets_to_search = all_sheets.items()
        if selected_sheet != "جميع الشيتات":
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
                search_columns = ["الحدث/العطل", "الإجراء التصحيحي"]
                if search_in_notes:
                    search_columns.append("ملاحظات")
                mask = pd.Series([False] * len(df_filtered))
                for col in search_columns:
                    if col in df_filtered.columns:
                        mask = mask | df_filtered[col].astype(str).str.contains(search_term, case=False, na=False)
                df_filtered = df_filtered[mask]
            if not df_filtered.empty:
                df_filtered["الشيت"] = sheet_name
                results.append(df_filtered)
        
        if results:
            combined_results = pd.concat(results, ignore_index=True)
            st.success(f"تم العثور على {len(combined_results)} نتيجة")
            st.dataframe(combined_results, use_container_width=True, height=500)
            
            excel_file = export_filtered_results_to_excel(combined_results, "نتائج_البحث")
            st.download_button(
                "📥 تحميل نتائج البحث كملف Excel",
                excel_file,
                f"search_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key='download-excel'
            )
        else:
            st.warning("لا توجد نتائج مطابقة للبحث")

# ==================== تحليل الأعطال ====================
def failures_analysis_tab(all_sheets):
    st.header("📊 تحليل الأعطال والإجراءات التصحيحية")
    
    if not all_sheets:
        st.warning("لا توجد بيانات للتحليل")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        sheet_options = list(all_sheets.keys())
        selected_sheet = st.selectbox("اختر الشيت للتحليل:", sheet_options, key="analysis_sheet")
    
    with col2:
        df = all_sheets[selected_sheet]
        equipment_list = get_equipment_list_from_sheet(df)
        equipment_options = ["جميع المعدات"] + equipment_list
        selected_equipment = st.selectbox("اختر المعدة للتحليل:", equipment_options, key="analysis_equipment")
    
    if st.button("🔄 تشغيل التحليل", key="run_analysis", type="primary"):
        with st.spinner("جاري تحليل البيانات..."):
            analysis = analyze_failures(df, selected_equipment if selected_equipment != "جميع المعدات" else None)
            
            if analysis is None:
                st.error("❌ لا توجد بيانات كافية للتحليل. تأكد من وجود بيانات في الشيت المحدد مع تواريخ صالحة.")
                return
            
            st.subheader("📈 ملخص التحليل")
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                st.metric("إجمالي الأعطال", analysis["total_failures"])
            with col_b:
                st.metric("عدد المعدات", analysis["unique_equipment"])
            with col_c:
                st.metric("من تاريخ", analysis["date_range"]["from"])
            with col_d:
                st.metric("إلى تاريخ", analysis["date_range"]["to"])
            
            st.subheader("📊 الرسوم البيانية")
            
            if PLOTLY_AVAILABLE:
                charts = create_failure_charts_plotly(analysis)
                for chart in charts:
                    st.plotly_chart(chart, use_container_width=True)
            elif MATPLOTLIB_AVAILABLE:
                charts = create_failure_charts_matplotlib(analysis)
                for chart in charts:
                    st.pyplot(chart)
                    plt.close(chart)
            else:
                st.warning("⚠️ مكتبات الرسم البياني غير متوفرة. يرجى تثبيت plotly أو matplotlib لعرض الرسوم البيانية.")
            
            st.subheader("📋 الجداول التفصيلية")
            
            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "معدل تكرار الأعطال", "أكثر الأعطال تكراراً", "MTBF", "التحليل الشهري", "الإجراءات التصحيحية"
            ])
            
            with tab1:
                if not analysis["failure_rate"].empty:
                    st.dataframe(analysis["failure_rate"], use_container_width=True)
                else:
                    st.info("لا توجد بيانات")
            
            with tab2:
                if not analysis["issue_counts"].empty:
                    st.dataframe(analysis["issue_counts"], use_container_width=True)
                else:
                    st.info("لا توجد بيانات")
            
            with tab3:
                if not analysis["mtbf"].empty:
                    st.dataframe(analysis["mtbf"], use_container_width=True)
                    st.caption("MTBF = متوسط الوقت بين الأعطال (Mean Time Between Failures) - بالأيام")
                else:
                    st.info("لا توجد بيانات كافية لحساب MTBF (يلزم على الأقل عطلين لكل معدة)")
            
            with tab4:
                if not analysis["monthly"].empty:
                    pivot = analysis["monthly"].pivot(index="الشهر", columns="المعدة", values="عدد الأعطال").fillna(0)
                    st.dataframe(pivot, use_container_width=True)
                else:
                    st.info("لا توجد بيانات")
            
            with tab5:
                if not analysis["correction_counts"].empty:
                    st.dataframe(analysis["correction_counts"], use_container_width=True)
                else:
                    st.info("لا توجد بيانات")
            
            st.markdown("---")
            st.subheader("📥 تصدير التقرير")
            
            excel_report = generate_excel_report(analysis, selected_sheet, selected_equipment)
            st.download_button(
                "📊 تحميل تقرير التحليل كملف Excel",
                excel_report,
                f"failure_analysis_{selected_sheet}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_analysis_report"
            )

def create_failure_charts_matplotlib(analysis):
    charts = []
    
    if not MATPLOTLIB_AVAILABLE:
        return charts
    
    if not analysis["failure_rate"].empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        top_equipment = analysis["failure_rate"].head(10)
        colors = plt.cm.Reds(np.linspace(0.4, 0.9, len(top_equipment)))
        bars = ax.barh(top_equipment["المعدة"], top_equipment["عدد الأعطال"], color=colors)
        ax.set_xlabel("عدد الأعطال")
        ax.set_title("أكثر المعدات تعطلاً", fontsize=14)
        ax.invert_yaxis()
        for bar, val in zip(bars, top_equipment["عدد الأعطال"]):
            ax.text(val + 0.5, bar.get_y() + bar.get_height()/2, str(val), va='center')
        charts.append(fig)
    
    if not analysis["failure_rate"].empty:
        fig, ax = plt.subplots(figsize=(8, 8))
        top8 = analysis["failure_rate"].head(8)
        ax.pie(top8["عدد الأعطال"], labels=top8["المعدة"], autopct='%1.1f%%', startangle=90)
        ax.set_title("نسب الأعطال حسب المعدة", fontsize=14)
        charts.append(fig)
    
    if not analysis["monthly"].empty:
        fig, ax = plt.subplots(figsize=(12, 6))
        pivot = analysis["monthly"].pivot(index="الشهر", columns="المعدة", values="عدد الأعطال").fillna(0)
        pivot.plot(kind='line', marker='o', ax=ax)
        ax.set_xlabel("الشهر")
        ax.set_ylabel("عدد الأعطال")
        ax.set_title("تطور الأعطال شهرياً", fontsize=14)
        ax.legend(loc='upper left', bbox_to_anchor=(1, 1))
        plt.xticks(rotation=45)
        charts.append(fig)
    
    if not analysis["weekday"].empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        colors = plt.cm.Blues(np.linspace(0.4, 0.9, len(analysis["weekday"])))
        bars = ax.bar(analysis["weekday"]["اليوم"], analysis["weekday"]["عدد الأعطال"], color=colors)
        ax.set_xlabel("اليوم")
        ax.set_ylabel("عدد الأعطال")
        ax.set_title("توزيع الأعطال حسب أيام الأسبوع", fontsize=14)
        for bar, val in zip(bars, analysis["weekday"]["عدد الأعطال"]):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5, str(val), ha='center')
        charts.append(fig)
    
    if not analysis["mtbf"].empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        colors = plt.cm.Greens(np.linspace(0.4, 0.9, len(analysis["mtbf"])))
        bars = ax.barh(analysis["mtbf"]["المعدة"], analysis["mtbf"]["متوسط MTBF (أيام)"], color=colors)
        ax.set_xlabel("متوسط MTBF (أيام)")
        ax.set_title("متوسط الوقت بين الأعطال", fontsize=14)
        for bar, val in zip(bars, analysis["mtbf"]["متوسط MTBF (أيام)"]):
            ax.text(val + 0.5, bar.get_y() + bar.get_height()/2, f'{val:.1f}', va='center')
        charts.append(fig)
    
    if not analysis["issue_counts"].empty:
        fig, ax = plt.subplots(figsize=(10, 8))
        top_issues = analysis["issue_counts"].head(10)
        colors = plt.cm.Purples(np.linspace(0.4, 0.9, len(top_issues)))
        bars = ax.barh(top_issues["الحدث/العطل"], top_issues["عدد المرات"], color=colors)
        ax.set_xlabel("عدد المرات")
        ax.set_title("أكثر الأعطال تكراراً", fontsize=14)
        ax.invert_yaxis()
        for bar, val in zip(bars, top_issues["عدد المرات"]):
            ax.text(val + 0.5, bar.get_y() + bar.get_height()/2, str(val), va='center')
        charts.append(fig)
    
    return charts

def create_failure_charts_plotly(analysis):
    charts = []
    
    if not PLOTLY_AVAILABLE:
        return charts
    
    if not analysis["failure_rate"].empty:
        fig = px.bar(
            analysis["failure_rate"].head(10),
            x="المعدة",
            y="عدد الأعطال",
            title="📊 أكثر المعدات تعطلاً",
            text="عدد الأعطال",
            color="عدد الأعطال",
            color_continuous_scale="Reds"
        )
        fig.update_traces(textposition='outside')
        fig.update_layout(showlegend=False)
        charts.append(fig)
    
    if not analysis["failure_rate"].empty:
        fig = px.pie(
            analysis["failure_rate"].head(8),
            values="عدد الأعطال",
            names="المعدة",
            title="🥧 نسب الأعطال حسب المعدة",
            hole=0.3
        )
        charts.append(fig)
    
    if not analysis["monthly"].empty:
        fig = px.line(
            analysis["monthly"],
            x="الشهر",
            y="عدد الأعطال",
            color="المعدة",
            title="📈 تطور الأعطال شهرياً",
            markers=True
        )
        charts.append(fig)
    
    if not analysis["weekday"].empty:
        fig = px.bar(
            analysis["weekday"],
            x="اليوم",
            y="عدد الأعطال",
            title="📅 توزيع الأعطال حسب أيام الأسبوع",
            text="عدد الأعطال",
            color="عدد الأعطال",
            color_continuous_scale="Blues"
        )
        fig.update_traces(textposition='outside')
        charts.append(fig)
    
    if not analysis["mtbf"].empty:
        fig = px.bar(
            analysis["mtbf"],
            x="المعدة",
            y="متوسط MTBF (أيام)",
            title="⏱️ متوسط الوقت بين الأعطال (MTBF) - أيام",
            text="متوسط MTBF (أيام)",
            color="متوسط MTBF (أيام)",
            color_continuous_scale="Greens"
        )
        fig.update_traces(textposition='outside')
        charts.append(fig)
    
    if not analysis["issue_counts"].empty:
        fig = px.bar(
            analysis["issue_counts"].head(10),
            x="عدد المرات",
            y="الحدث/العطل",
            title="🔧 أكثر الأعطال تكراراً",
            text="عدد المرات",
            orientation='h',
            color="عدد المرات",
            color_continuous_scale="Purples"
        )
        fig.update_traces(textposition='outside')
        charts.append(fig)
    
    return charts

# ==================== دوال إدارة الشيتات والأحداث ====================
def add_new_sheet_to_github(sheets_edit):
    st.subheader("➕ إضافة شيت جديد إلى GitHub")
    st.info("سيتم إضافة الشيت الجديد إلى ملف Excel الموجود على GitHub")
    
    col1, col2 = st.columns(2)
    with col1:
        new_sheet_name = st.text_input("📝 اسم الشيت الجديد:", key="new_sheet_name_github",
                                       placeholder="مثال: قسم الميكانيكا, محطة الكهرباء")
        if new_sheet_name and new_sheet_name in sheets_edit:
            st.error(f"❌ الشيت '{new_sheet_name}' موجود بالفعل!")
        elif new_sheet_name:
            st.success(f"✅ اسم الشيت '{new_sheet_name}' متاح")
    with col2:
        use_default = st.checkbox("استخدام الأعمدة الافتراضية", value=True, key="use_default_columns")
        if use_default:
            columns_list = APP_CONFIG["DEFAULT_SHEET_COLUMNS"]
            st.info(f"📊 الأعمدة: {', '.join(columns_list)}")
        else:
            columns_text = st.text_area("✏️ الأعمدة (كل عمود في سطر):", 
                                        value="\n".join(APP_CONFIG["DEFAULT_SHEET_COLUMNS"]), 
                                        key="custom_columns", height=150)
            columns_list = [col.strip() for col in columns_text.split("\n") if col.strip()]
            if not columns_list:
                columns_list = APP_CONFIG["DEFAULT_SHEET_COLUMNS"]
    
    st.markdown("---")
    st.markdown("### 📋 معاينة الشيت الجديد")
    preview_df = pd.DataFrame(columns=columns_list)
    st.dataframe(preview_df, use_container_width=True)
    st.caption(f"📊 عدد الأعمدة: {len(columns_list)} | سيتم إنشاء شيت فارغ بهذه الأعمدة")
    
    if st.button("✅ إنشاء وإضافة الشيت إلى GitHub", key="create_sheet_github_btn", type="primary", use_container_width=True):
        if not new_sheet_name:
            st.error("❌ الرجاء إدخال اسم الشيت")
            return sheets_edit
        clean_name = re.sub(r'[\\/*?:"<>|]', '_', new_sheet_name.strip())
        if clean_name != new_sheet_name:
            st.warning(f"⚠ تم تعديل اسم الشيت إلى: {clean_name}")
            new_sheet_name = clean_name
        if new_sheet_name in sheets_edit:
            st.error(f"❌ الشيت '{new_sheet_name}' موجود بالفعل!")
            return sheets_edit
        
        new_df = pd.DataFrame(columns=columns_list)
        sheets_edit[new_sheet_name] = new_df
        
        if save_and_push_to_github(sheets_edit, f"إنشاء شيت جديد: {new_sheet_name}"):
            st.success(f"✅ تم إنشاء الشيت '{new_sheet_name}' بنجاح!")
            st.cache_data.clear()
            st.balloons()
            st.rerun()
        else:
            st.error("❌ فشل حفظ الشيت")
            return sheets_edit
    
    st.markdown("---")
    st.markdown("### 📋 الشيتات الموجودة حالياً على GitHub:")
    if sheets_edit:
        for sheet_name in sheets_edit.keys():
            st.write(f"- {sheet_name}")
    else:
        st.info("لا توجد شيتات بعد")
    return sheets_edit

def add_new_event(sheets_edit, sheet_name):
    st.markdown(f"### إضافة حدث جديد في شيت: {sheet_name}")
    df = sheets_edit[sheet_name]
    equipment_list = get_equipment_list_from_sheet(df)
    
    if not equipment_list:
        st.warning("⚠ لا توجد معدات مسجلة بعد. يمكنك إضافة معدة جديدة عن طريق كتابة اسمها في الحقل المخصص.")
        new_equipment = st.text_input("➕ إضافة معدة جديدة (اكتب الاسم ثم استخدم الزر بالأسفل):", key="new_eq_fast")
        if st.button("إضافة المعدة أولاً", key="add_eq_fast"):
            if new_equipment:
                success, msg = add_equipment_to_sheet_data(sheets_edit, sheet_name, new_equipment)
                if success:
                    if save_and_push_to_github(sheets_edit, f"إضافة معدة: {new_equipment}"):
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("فشل الحفظ")
                else:
                    st.error(msg)
            else:
                st.warning("يرجى إدخال اسم المعدة")
        return sheets_edit
    
    with st.form(key="add_event_form"):
        col1, col2 = st.columns(2)
        with col1:
            selected_equipment = st.selectbox("🔧 اختر المعدة:", equipment_list)
            event_date = st.date_input("📅 التاريخ:", value=datetime.now())
            event_desc = st.text_area("📝 الحدث/العطل:", height=100)
        with col2:
            correction_desc = st.text_area("🔧 الإجراء التصحيحي:", height=100)
            servised_by = st.text_input("👨‍🔧 تم بواسطة:")
            tones = st.text_input("⚖️ الطن:")
        notes = st.text_area("📝 ملاحظات:")
        
        add_new_equipment_inline = st.text_input("➕ أو أضف معدة جديدة (اختياري):", key="new_eq_inline", placeholder="اكتب اسم معدة غير موجودة")
        
        submitted = st.form_submit_button("✅ إضافة الحدث", type="primary")
        
        if submitted:
            if add_new_equipment_inline and add_new_equipment_inline not in equipment_list:
                success, msg = add_equipment_to_sheet_data(sheets_edit, sheet_name, add_new_equipment_inline)
                if success:
                    st.success(msg)
                    df = sheets_edit[sheet_name]
                    equipment_list = get_equipment_list_from_sheet(df)
                    selected_equipment = add_new_equipment_inline
                else:
                    st.error(msg)
                    return sheets_edit
            
            new_row = {
                "التاريخ": event_date.strftime("%Y-%m-%d"),
                "المعدة": selected_equipment,
                "الحدث/العطل": event_desc,
                "الإجراء التصحيحي": correction_desc,
                "تم بواسطة": servised_by,
                "الطن": tones,
                "الصور": "",
                "ملاحظات": notes
            }
            for col in df.columns:
                if col not in new_row:
                    new_row[col] = ""
            new_row_df = pd.DataFrame([new_row])
            df_new = pd.concat([df, new_row_df], ignore_index=True)
            sheets_edit[sheet_name] = df_new
            
            if save_and_push_to_github(sheets_edit, f"إضافة حدث جديد في {sheet_name}"):
                st.cache_data.clear()
                st.success("✅ تم إضافة الحدث بنجاح ورفعه إلى GitHub!")
                st.rerun()
            else:
                st.error("❌ فشل الحفظ")
    return sheets_edit

def manage_equipment(sheets_edit, sheet_name):
    st.markdown(f"### 🔧 إدارة المعدات في شيت: {sheet_name}")
    df = sheets_edit[sheet_name]
    equipment_list = get_equipment_list_from_sheet(df)
    
    if equipment_list:
        st.markdown("#### 📋 المعدات الحالية:")
        for eq in equipment_list:
            st.markdown(f"- 🔹 {eq}")
    else:
        st.info("لا توجد معدات مسجلة بعد")
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        new_equipment = st.text_input("➕ اسم المعدة الجديدة:", key="new_equipment_name")
        if st.button("➕ إضافة معدة", key="add_equipment_btn"):
            if new_equipment:
                success, msg = add_equipment_to_sheet_data(sheets_edit, sheet_name, new_equipment)
                if success:
                    if save_and_push_to_github(sheets_edit, f"إضافة معدة: {new_equipment}"):
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("فشل الحفظ")
                else:
                    st.error(msg)
            else:
                st.warning("يرجى إدخال اسم المعدة")
    with col2:
        if equipment_list:
            eq_to_delete = st.selectbox("🗑️ اختر المعدة للحذف:", equipment_list, key="delete_eq_select")
            st.warning("⚠️ تحذير: حذف المعدة سيؤدي إلى حذف جميع سجلات الأعطال المرتبطة بها نهائياً!")
            if st.button("🗑️ حذف المعدة نهائياً", key="delete_equipment_btn"):
                success, msg = remove_equipment_from_sheet_data(sheets_edit, sheet_name, eq_to_delete)
                if success:
                    if save_and_push_to_github(sheets_edit, f"حذف معدة: {eq_to_delete}"):
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("فشل الحفظ")
                else:
                    st.error(msg)

def manage_data_edit(sheets_edit):
    if sheets_edit is None:
        st.warning("الملف غير موجود. استخدم زر 'تحديث من GitHub' في الشريط الجانبي أولاً")
        return sheets_edit
    
    tab_names = ["📋 عرض البيانات", "➕ إضافة حدث جديد", "🔧 إدارة المعدات", "➕ إضافة شيت جديد"]
    tabs_edit = st.tabs(tab_names)
    
    with tabs_edit[0]:
        st.subheader("جميع الشيتات")
        if sheets_edit:
            sheet_tabs = st.tabs(list(sheets_edit.keys()))
            for i, (sheet_name, df) in enumerate(sheets_edit.items()):
                with sheet_tabs[i]:
                    display_sheet_data(sheet_name, df, f"view_{sheet_name}", sheets_edit)
                    with st.expander("✏️ تعديل مباشر", expanded=False):
                        edited_df = st.data_editor(df.astype(str), num_rows="dynamic", use_container_width=True, key=f"editor_{sheet_name}")
                        if st.button(f"💾 حفظ", key=f"save_{sheet_name}"):
                            sheets_edit[sheet_name] = edited_df.astype(object)
                            if save_and_push_to_github(sheets_edit, f"تعديل بيانات في {sheet_name}"):
                                st.cache_data.clear()
                                st.success("تم الحفظ والرفع إلى GitHub!")
                                st.rerun()
    
    with tabs_edit[1]:
        if sheets_edit:
            sheet_name = st.selectbox("اختر الشيت:", list(sheets_edit.keys()), key="add_event_sheet")
            sheets_edit = add_new_event(sheets_edit, sheet_name)
    
    with tabs_edit[2]:
        if sheets_edit:
            sheet_name = st.selectbox("اختر الشيت:", list(sheets_edit.keys()), key="manage_eq_sheet")
            manage_equipment(sheets_edit, sheet_name)
    
    with tabs_edit[3]:
        sheets_edit = add_new_sheet_to_github(sheets_edit)
    
    return sheets_edit

# ------------------------------- الواجهة الرئيسية -------------------------------
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

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

all_sheets = load_all_sheets()
sheets_edit = load_sheets_for_edit()

st.title(f"{APP_CONFIG['APP_ICON']} {APP_CONFIG['APP_TITLE']}")

user_role = st.session_state.get("user_role", "viewer")
user_permissions = st.session_state.get("user_permissions", ["view"])
can_edit = (user_role == "admin" or user_role == "editor" or "edit" in user_permissions)

tabs_list = ["🔍 بحث متقدم", "📊 تحليل الأعطال"]
if can_edit:
    tabs_list.append("🛠 تعديل وإدارة البيانات")

tabs = st.tabs(tabs_list)

with tabs[0]:
    search_across_sheets(all_sheets)

with tabs[1]:
    failures_analysis_tab(all_sheets)

if can_edit and len(tabs) > 2:
    with tabs[2]:
        sheets_edit = manage_data_edit(sheets_edit)

import streamlit as st
import pandas as pd
import json
import os
import io
import requests
import shutil
import re
from datetime import datetime, timedelta
from base64 import b64decode
import uuid

try:
    from github import Github
    GITHUB_AVAILABLE = True
except Exception:
    GITHUB_AVAILABLE = False

APP_CONFIG = {
    "APP_TITLE": "  صيانه المحطات - CMMS",
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
    "DEFAULT_SHEET_COLUMNS": ["التاريخ", "المعدة", "الحدث/العطل", "الإجراء التصحيحي", "تم بواسطة", "الصور"],
}

USERS_FILE = "users.json"
STATE_FILE = "state.json"
SESSION_DURATION = timedelta(minutes=APP_CONFIG["SESSION_DURATION_MINUTES"])
MAX_ACTIVE_USERS = APP_CONFIG["MAX_ACTIVE_USERS"]
IMAGES_FOLDER = APP_CONFIG["IMAGES_FOLDER"]
EQUIPMENT_CONFIG_FILE = "equipment_config.json"

GITHUB_EXCEL_URL = f"https://github.com/{APP_CONFIG['REPO_NAME'].split('/')[0]}/{APP_CONFIG['REPO_NAME'].split('/')[1]}/raw/{APP_CONFIG['BRANCH']}/{APP_CONFIG['FILE_PATH']}"
GITHUB_USERS_URL = "https://raw.githubusercontent.com/mahmedabdallh123/Elqds/refs/heads/main/users.json"
GITHUB_REPO_USERS = "mahmedabdallh123/Elqds"

# ------------------------------- دوال إدارة تكوينات المعدات -------------------------------
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
        st.error(f"❌ خطأ في حفظ تكوين المعدات: {e}")
        return False

def get_sheet_equipment(sheet_name, config):
    if sheet_name in config:
        return config[sheet_name].get("equipment_list", [])
    return []

def add_equipment_to_sheet(sheet_name, equipment_name, config):
    if sheet_name not in config:
        config[sheet_name] = {"equipment_list": [], "created_at": datetime.now().isoformat()}
    if equipment_name in config[sheet_name]["equipment_list"]:
        return False, f"المعدة '{equipment_name}' موجودة بالفعل"
    config[sheet_name]["equipment_list"].append(equipment_name)
    save_equipment_config(config)
    return True, f"تم إضافة المعدة '{equipment_name}' بنجاح"

def remove_equipment_from_sheet(sheet_name, equipment_name, config):
    if sheet_name not in config:
        return False, "الشيت غير موجود"
    if equipment_name not in config[sheet_name]["equipment_list"]:
        return False, "المعدة غير موجودة"
    config[sheet_name]["equipment_list"].remove(equipment_name)
    save_equipment_config(config)
    return True, f"تم حذف المعدة '{equipment_name}' بنجاح"

# ------------------------------- دوال مساعدة للصور -------------------------------
def setup_images_folder():
    if not os.path.exists(IMAGES_FOLDER):
        os.makedirs(IMAGES_FOLDER)

def save_uploaded_images(uploaded_files):
    if not uploaded_files:
        return []
    saved_files = []
    for uploaded_file in uploaded_files:
        file_extension = uploaded_file.name.split('.')[-1].lower()
        if file_extension not in APP_CONFIG["ALLOWED_IMAGE_TYPES"]:
            continue
        unique_id = str(uuid.uuid4())[:8]
        original_name = uploaded_file.name.split('.')[0]
        safe_name = re.sub(r'[^\w\-_]', '_', original_name)
        new_filename = f"{safe_name}_{unique_id}.{file_extension}"
        file_path = os.path.join(IMAGES_FOLDER, new_filename)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        saved_files.append(new_filename)
    return saved_files

def delete_image_file(image_filename):
    try:
        file_path = os.path.join(IMAGES_FOLDER, image_filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
    except:
        pass
    return False

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
    except:
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
    username_input = st.selectbox("👤 اختر المستخدم", list(users.keys()))
    password = st.text_input("🔑 كلمة المرور", type="password")
    active_users = [u for u, v in state.items() if v.get("active")]
    active_count = len(active_users)
    st.caption(f"🔒 المستخدمون النشطون: {active_count} / {MAX_ACTIVE_USERS}")

    if not st.session_state.logged_in:
        if st.button("تسجيل الدخول"):
            current_users = load_users()
            if username_input in current_users and current_users[username_input]["password"] == password:
                if username_input != "admin" and username_input in active_users:
                    st.warning("⚠ هذا المستخدم مسجل دخول بالفعل.")
                    return False
                elif active_count >= MAX_ACTIVE_USERS and username_input != "admin":
                    st.error("🚫 الحد الأقصى للمستخدمين المتصلين.")
                    return False
                state[username_input] = {"active": True, "login_time": datetime.now().isoformat()}
                save_state(state)
                st.session_state.logged_in = True
                st.session_state.username = username_input
                st.session_state.user_role = current_users[username_input].get("role", "viewer")
                st.session_state.user_permissions = current_users[username_input].get("permissions", ["view"])
                st.success(f"✅ تم تسجيل الدخول: {username_input}")
                st.rerun()
            else:
                st.error("❌ كلمة المرور غير صحيحة.")
        return False
    else:
        st.success(f"✅ مسجل الدخول كـ: {st.session_state.username}")
        rem = remaining_time(state, st.session_state.username)
        if rem:
            mins, secs = divmod(int(rem.total_seconds()), 60)
            st.info(f"⏳ الوقت المتبقي: {mins:02d}:{secs:02d}")
        if st.button("🚪 تسجيل الخروج"):
            logout_action()
        return True

# ------------------------------- دوال جلب وحفظ الملفات -------------------------------
def fetch_from_github_requests():
    try:
        response = requests.get(GITHUB_EXCEL_URL, stream=True, timeout=15)
        response.raise_for_status()
        with open(APP_CONFIG["LOCAL_FILE"], "wb") as f:
            shutil.copyfileobj(response.raw, f)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"⚠ فشل التحديث: {e}")
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
        st.error(f"❌ خطأ في تحميل الشيتات: {e}")
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
        st.error(f"❌ خطأ في تحميل الشيتات: {e}")
        return None

def save_local_excel_and_push(sheets_dict, commit_message="Update"):
    try:
        with pd.ExcelWriter(APP_CONFIG["LOCAL_FILE"], engine="openpyxl") as writer:
            for name, sh in sheets_dict.items():
                try:
                    sh.to_excel(writer, sheet_name=name, index=False)
                except:
                    sh.astype(object).to_excel(writer, sheet_name=name, index=False)
    except Exception as e:
        st.error(f"⚠ خطأ في الحفظ: {e}")
        return None
    st.cache_data.clear()
    token = st.secrets.get("github", {}).get("token", None)
    if not token or not GITHUB_AVAILABLE:
        st.warning("⚠ تم الحفظ محلياً فقط")
        return load_sheets_for_edit()
    try:
        g = Github(token)
        repo = g.get_repo(APP_CONFIG["REPO_NAME"])
        with open(APP_CONFIG["LOCAL_FILE"], "rb") as f:
            content = f.read()
        try:
            contents = repo.get_contents(APP_CONFIG["FILE_PATH"], ref=APP_CONFIG["BRANCH"])
            repo.update_file(path=APP_CONFIG["FILE_PATH"], message=commit_message, content=content, sha=contents.sha, branch=APP_CONFIG["BRANCH"])
        except:
            repo.create_file(path=APP_CONFIG["FILE_PATH"], message=commit_message, content=content, branch=APP_CONFIG["BRANCH"])
        st.success("✅ تم الرفع إلى GitHub")
        return load_sheets_for_edit()
    except Exception as e:
        st.error(f"❌ فشل الرفع: {e}")
        return None

def auto_save_to_github(sheets_dict, operation_description):
    username = st.session_state.get("username", "unknown")
    commit_message = f"{operation_description} by {username}"
    result = save_local_excel_and_push(sheets_dict, commit_message)
    if result is not None:
        return result
    return sheets_dict

# ------------------------------- دوال العرض والتعديل -------------------------------
def create_new_sheet_in_excel(sheets_edit, new_sheet_name, template_columns=None):
    if template_columns is None:
        template_columns = APP_CONFIG["DEFAULT_SHEET_COLUMNS"]
    new_df = pd.DataFrame(columns=template_columns)
    sheets_edit[new_sheet_name] = new_df
    return sheets_edit

def add_new_event_with_equipment(sheets_edit, sheet_name, equipment_list, unique_id):
    st.markdown(f"### 📝 إضافة حدث جديد في شيت: {sheet_name}")
    
    if not equipment_list:
        st.warning("⚠ لا توجد معدات مضافة. يرجى إضافة معدات أولاً")
        return sheets_edit
    
    df = sheets_edit[sheet_name].copy()
    
    col1, col2 = st.columns(2)
    
    with col1:
        selected_equipment = st.selectbox("🔧 اختر المعدة:", equipment_list, key=f"eq_select_{unique_id}")
        event_date = st.date_input("📅 التاريخ:", value=datetime.now(), key=f"date_{unique_id}")
        event_desc = st.text_area("📝 الحدث/العطل:", height=100, key=f"event_{unique_id}", placeholder="وصف العطل أو المشكلة...")
    
    with col2:
        correction_desc = st.text_area("🔧 الإجراء التصحيحي:", height=100, key=f"correction_{unique_id}", placeholder="ما الذي تم إصلاحه...")
        servised_by = st.text_input("👨‍🔧 تم بواسطة:", key=f"servised_{unique_id}", placeholder="اسم الفني أو المشغل")
        tones = st.text_input("⚖️ الطن:", key=f"tones_{unique_id}", placeholder="مثال: 5.5 طن")
    
    st.markdown("#### 📷 الصور المرفقة")
    uploaded_files = st.file_uploader("اختر الصور:", type=APP_CONFIG["ALLOWED_IMAGE_TYPES"], accept_multiple_files=True, key=f"images_{unique_id}")
    
    images_str = ""
    if uploaded_files:
        saved_images = save_uploaded_images(uploaded_files)
        if saved_images:
            images_str = ",".join(saved_images)
    
    notes = st.text_area("📝 ملاحظات:", key=f"notes_{unique_id}", placeholder="أي ملاحظات إضافية...")
    
    if st.button("✅ إضافة الحدث", key=f"submit_{unique_id}", type="primary"):
        new_row = {
            "التاريخ": event_date.strftime("%Y-%m-%d"),
            "المعدة": selected_equipment,
            "الحدث/العطل": event_desc,
            "الإجراء التصحيحي": correction_desc,
            "تم بواسطة": servised_by,
            "الطن": tones,
            "الصور": images_str,
            "ملاحظات": notes
        }
        for col in df.columns:
            if col not in new_row:
                new_row[col] = ""
        new_row_df = pd.DataFrame([new_row])
        df_new = pd.concat([df, new_row_df], ignore_index=True)
        sheets_edit[sheet_name] = df_new
        new_sheets = auto_save_to_github(sheets_edit, f"إضافة حدث في {sheet_name}")
        if new_sheets is not None:
            st.success("✅ تم إضافة الحدث بنجاح!")
            st.rerun()
    return sheets_edit

def manage_sheet_equipment(sheet_name, config, unique_id):
    st.markdown(f"### 🔧 إدارة المعدات في شيت: {sheet_name}")
    equipment_list = get_sheet_equipment(sheet_name, config)
    
    if equipment_list:
        st.markdown("#### 📋 المعدات الحالية:")
        for eq in equipment_list:
            st.markdown(f"- 🔹 {eq}")
    else:
        st.info("ℹ️ لا توجد معدات مضافة")
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### ➕ إضافة معدة")
        new_equipment = st.text_input("اسم المعدة:", key=f"new_eq_{unique_id}", placeholder="مثال: محرك رئيسي 1, مضخة مياه")
        if st.button("➕ إضافة", key=f"add_eq_{unique_id}"):
            if new_equipment:
                success, msg = add_equipment_to_sheet(sheet_name, new_equipment, config)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    
    with col2:
        st.markdown("#### 🗑️ حذف معدة")
        if equipment_list:
            eq_to_delete = st.selectbox("اختر المعدة:", equipment_list, key=f"del_eq_{unique_id}")
            if st.button("🗑️ حذف", key=f"delete_eq_{unique_id}"):
                success, msg = remove_equipment_from_sheet(sheet_name, eq_to_delete, config)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

def display_sheet_data(sheet_name, df, equipment_list, unique_id):
    st.markdown(f"### 📄 {sheet_name}")
    st.info(f"عدد السجلات: {len(df)} | عدد الأعمدة: {len(df.columns)}")
    
    if equipment_list and "المعدة" in df.columns:
        st.markdown("#### 🔍 فلتر حسب المعدة:")
        selected_filter = st.selectbox(
            "اختر المعدة:", 
            ["جميع المعدات"] + equipment_list,
            key=f"filter_{unique_id}"
        )
        if selected_filter != "جميع المعدات":
            df = df[df["المعدة"] == selected_filter]
            st.info(f"🔍 عرض للمعدة: {selected_filter} - السجلات: {len(df)}")
    
    display_df = df.copy()
    for col in display_df.columns:
        if display_df[col].dtype == 'object':
            display_df[col] = display_df[col].astype(str).apply(lambda x: x[:100] + "..." if len(x) > 100 else x)
    st.dataframe(display_df, use_container_width=True, height=400)
    
    if "المعدة" in df.columns and len(df) > 0:
        with st.expander("📊 إحصائيات الأعطال حسب المعدة"):
            stats = df["المعدة"].value_counts().reset_index()
            stats.columns = ["المعدة", "عدد الأعطال"]
            st.dataframe(stats, use_container_width=True)

def search_across_sheets(all_sheets, equipment_config):
    st.subheader("🔍 بحث متقدم في السجلات")
    
    if not all_sheets:
        st.warning("لا توجد بيانات للبحث")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        sheet_options = ["جميع الشيتات"] + list(all_sheets.keys())
        selected_sheet = st.selectbox("📂 اختر الشيت للبحث:", sheet_options, key="search_sheet")
        
        if selected_sheet != "جميع الشيتات":
            equipment_list = get_sheet_equipment(selected_sheet, equipment_config)
        else:
            all_equipment = []
            for sheet_name in all_sheets.keys():
                all_equipment.extend(get_sheet_equipment(sheet_name, equipment_config))
            equipment_list = list(set(all_equipment))
        
        filter_equipment = st.selectbox("🔧 فلتر حسب المعدة:", ["الكل"] + equipment_list, key="search_eq")
        search_term = st.text_input("🔎 كلمة البحث:", placeholder="أدخل نصاً للبحث...", key="search_term")
    
    with col2:
        st.markdown("#### 📅 نطاق التاريخ")
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
    
    if st.button("🔍 بحث", key="search_btn", type="primary"):
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
            st.success(f"✅ تم العثور على {len(combined_results)} نتيجة")
            
            display_results = combined_results.copy()
            for col in display_results.columns:
                if display_results[col].dtype == 'object':
                    display_results[col] = display_results[col].astype(str).apply(lambda x: x[:80] + "..." if len(x) > 80 else x)
            
            st.dataframe(display_results, use_container_width=True, height=500)
            
            csv = combined_results.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 تحميل النتائج كملف CSV",
                csv,
                f"search_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv",
                key='download-csv'
            )
        else:
            st.warning("⚠ لا توجد نتائج مطابقة للبحث")

def add_new_sheet_to_github(sheets_edit, equipment_config, unique_id):
    st.subheader("➕ إضافة شيت جديد")
    
    col1, col2 = st.columns(2)
    with col1:
        new_sheet_name = st.text_input("اسم الشيت الجديد:", key=f"new_sheet_{unique_id}", placeholder="مثال: قسم الميكانيكا")
        if new_sheet_name and new_sheet_name in sheets_edit:
            st.warning(f"⚠ الشيت موجود بالفعل")
    with col2:
        default_columns = st.text_area(
            "الأعمدة (كل عمود في سطر):", 
            value="\n".join(APP_CONFIG["DEFAULT_SHEET_COLUMNS"]), 
            key=f"cols_{unique_id}", 
            height=150
        )
    
    columns_list = [col.strip() for col in default_columns.split("\n") if col.strip()]
    st.markdown("### 📋 معاينة الشيت")
    preview_df = pd.DataFrame(columns=columns_list)
    st.dataframe(preview_df, use_container_width=True)
    
    if st.button("✅ إنشاء الشيت", key=f"create_{unique_id}", type="primary"):
        if not new_sheet_name:
            st.error("❌ الرجاء إدخال اسم الشيت")
            return sheets_edit
        if new_sheet_name in sheets_edit:
            st.error("❌ الشيت موجود بالفعل")
            return sheets_edit
        sheets_edit = create_new_sheet_in_excel(sheets_edit, new_sheet_name, columns_list)
        new_sheets = auto_save_to_github(sheets_edit, f"إنشاء شيت: {new_sheet_name}")
        if new_sheets is not None:
            if new_sheet_name not in equipment_config:
                equipment_config[new_sheet_name] = {"equipment_list": [], "created_at": datetime.now().isoformat()}
                save_equipment_config(equipment_config)
            st.success(f"✅ تم إنشاء الشيت '{new_sheet_name}'!")
            st.rerun()
    return sheets_edit

def manage_images(unique_id):
    st.subheader("📷 إدارة الصور")
    if os.path.exists(IMAGES_FOLDER):
        image_files = [f for f in os.listdir(IMAGES_FOLDER) if f.lower().endswith(tuple(APP_CONFIG["ALLOWED_IMAGE_TYPES"]))]
        if image_files:
            st.info(f"عدد الصور: {len(image_files)}")
            for img in image_files:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"📷 {img}")
                with col2:
                    if st.button(f"🗑 حذف", key=f"del_img_{img}_{unique_id}"):
                        if delete_image_file(img):
                            st.success(f"✅ تم حذف {img}")
                            st.rerun()
        else:
            st.info("ℹ️ لا توجد صور")
    else:
        st.warning("⚠ مجلد الصور غير موجود")

def manage_data_edit(sheets_edit, equipment_config):
    if sheets_edit is None:
        st.warning("❗ الملف غير موجود. استخدم تحديث من GitHub")
        return sheets_edit
    
    edit_unique_id = str(uuid.uuid4())[:8]
    
    tab_names = ["📋 عرض البيانات", "➕ إضافة حدث جديد", "🔧 إدارة المعدات", "➕ إضافة شيت جديد", "📷 إدارة الصور"]
    tabs_edit = st.tabs(tab_names)
    
    with tabs_edit[0]:
        st.subheader("📋 جميع الشيتات")
        if sheets_edit:
            sheet_tabs = st.tabs(list(sheets_edit.keys()))
            for i, (sheet_name, df) in enumerate(sheets_edit.items()):
                with sheet_tabs[i]:
                    equipment_list = get_sheet_equipment(sheet_name, equipment_config)
                    display_sheet_data(sheet_name, df, equipment_list, f"{edit_unique_id}_{sheet_name}_view")
                    
                    with st.expander("✏️ تعديل مباشر للبيانات", expanded=False):
                        st.warning("⚠ كن حذراً عند التعديل المباشر")
                        edited_df = st.data_editor(
                            df.astype(str), 
                            num_rows="dynamic", 
                            use_container_width=True, 
                            key=f"editor_{edit_unique_id}_{sheet_name}"
                        )
                        if st.button(f"💾 حفظ التغييرات", key=f"save_{edit_unique_id}_{sheet_name}"):
                            sheets_edit[sheet_name] = edited_df.astype(object)
                            new_sheets = auto_save_to_github(sheets_edit, f"تعديل {sheet_name}")
                            if new_sheets is not None:
                                sheets_edit = new_sheets
                                st.success("✅ تم الحفظ!")
                                st.rerun()
    
    with tabs_edit[1]:
        if sheets_edit:
            sheet_name = st.selectbox("اختر الشيت:", list(sheets_edit.keys()), key=f"add_event_select_{edit_unique_id}")
            equipment_list = get_sheet_equipment(sheet_name, equipment_config)
            if not equipment_list:
                st.warning(f"⚠ لا توجد معدات في '{sheet_name}'. أضف معدات أولاً")
            else:
                sheets_edit = add_new_event_with_equipment(sheets_edit, sheet_name, equipment_list, f"{edit_unique_id}_event")
    
    with tabs_edit[2]:
        if sheets_edit:
            sheet_name = st.selectbox("اختر الشيت:", list(sheets_edit.keys()), key=f"manage_eq_select_{edit_unique_id}")
            manage_sheet_equipment(sheet_name, equipment_config, f"{edit_unique_id}_eq")
    
    with tabs_edit[3]:
        sheets_edit = add_new_sheet_to_github(sheets_edit, equipment_config, f"{edit_unique_id}_sheet")
    
    with tabs_edit[4]:
        manage_images(edit_unique_id)
    
    return sheets_edit

# ------------------------------- الواجهة الرئيسية -------------------------------
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

setup_images_folder()
equipment_config = load_equipment_config()

with st.sidebar:
    st.header("👤 الجلسة")
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

tabs_list = ["🔍 بحث متقدم"]

if can_edit:
    tabs_list.append("🛠 تعديل وإدارة البيانات")

tabs = st.tabs(tabs_list)

with tabs[0]:
    st.header("🔍 نظام البحث المتقدم")
    st.markdown("يمكنك البحث في جميع السجلات باستخدام الشيت، المعدة، التاريخ، أو كلمات البحث")
    search_across_sheets(all_sheets, equipment_config)

if can_edit and len(tabs) > 1:
    with tabs[1]:
        st.header("🛠 تعديل وإدارة البيانات")
        sheets_edit = manage_data_edit(sheets_edit, equipment_config)

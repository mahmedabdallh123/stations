import streamlit as st
import pandas as pd
import json
import os
import requests
import shutil
import re
from datetime import datetime, timedelta
from base64 import b64decode
import uuid

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

# ------------------------------- دوال تكوينات المعدات -------------------------------
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

def save_to_github(sheets_dict, commit_message):
    """حفظ الملف مباشرة إلى GitHub باستخدام PyGithub"""
    try:
        token = st.secrets.get("github", {}).get("token", None)
        if not token:
            st.error("❌ لم يتم العثور على GitHub token في secrets")
            return False
        
        if not GITHUB_AVAILABLE:
            st.error("❌ PyGithub غير متوفر")
            return False
        
        # حفظ الملف محلياً أولاً
        temp_file = APP_CONFIG["LOCAL_FILE"]
        try:
            with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
                for name, sh in sheets_dict.items():
                    try:
                        sh.to_excel(writer, sheet_name=name, index=False)
                    except Exception as e:
                        st.warning(f"تحذير في شيت {name}: {e}")
                        sh.astype(object).to_excel(writer, sheet_name=name, index=False)
        except Exception as e:
            st.error(f"❌ خطأ في إنشاء ملف Excel: {e}")
            return False
        
        # رفع الملف إلى GitHub
        try:
            g = Github(token)
            repo = g.get_repo(APP_CONFIG["REPO_NAME"])
            
            with open(temp_file, "rb") as f:
                content = f.read()
            
            try:
                # محاولة الحصول على الملف الموجود
                contents = repo.get_contents(APP_CONFIG["FILE_PATH"], ref=APP_CONFIG["BRANCH"])
                # تحديث الملف الموجود
                result = repo.update_file(
                    path=APP_CONFIG["FILE_PATH"],
                    message=commit_message,
                    content=content,
                    sha=contents.sha,
                    branch=APP_CONFIG["BRANCH"]
                )
                st.success(f"✅ تم تحديث الملف على GitHub")
                return True
            except GithubException as e:
                if e.status == 404:
                    # الملف غير موجود، نقوم بإنشائه
                    result = repo.create_file(
                        path=APP_CONFIG["FILE_PATH"],
                        message=commit_message,
                        content=content,
                        branch=APP_CONFIG["BRANCH"]
                    )
                    st.success(f"✅ تم إنشاء الملف على GitHub")
                    return True
                else:
                    st.error(f"❌ خطأ في GitHub: {e}")
                    return False
        except Exception as e:
            st.error(f"❌ فشل الرفع إلى GitHub: {str(e)}")
            return False
            
    except Exception as e:
        st.error(f"❌ خطأ عام: {str(e)}")
        return False

# ------------------------------- دوال العرض -------------------------------
def display_sheet_data(sheet_name, df, equipment_list, unique_id):
    st.markdown(f"### {sheet_name}")
    st.info(f"عدد السجلات: {len(df)} | عدد الأعمدة: {len(df.columns)}")
    
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

def search_across_sheets(all_sheets, equipment_config):
    st.subheader("بحث متقدم في السجلات")
    
    if not all_sheets:
        st.warning("لا توجد بيانات للبحث")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        sheet_options = ["جميع الشيتات"] + list(all_sheets.keys())
        selected_sheet = st.selectbox("اختر الشيت للبحث:", sheet_options, key="search_sheet")
        
        if selected_sheet != "جميع الشيتات":
            equipment_list = get_sheet_equipment(selected_sheet, equipment_config)
        else:
            all_equipment = []
            for sheet_name in all_sheets.keys():
                all_equipment.extend(get_sheet_equipment(sheet_name, equipment_config))
            equipment_list = list(set(all_equipment))
        
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
            
            csv = combined_results.to_csv(index=False).encode('utf-8')
            st.download_button(
                "تحميل النتائج كملف CSV",
                csv,
                f"search_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv",
                key='download-csv'
            )
        else:
            st.warning("لا توجد نتائج مطابقة للبحث")

# ==================== دالة إضافة الشيت إلى GitHub ====================
def add_new_sheet_to_github(sheets_edit, equipment_config):
    """إضافة شيت جديد وحفظه مباشرة على GitHub"""
    st.subheader("➕ إضافة شيت جديد إلى GitHub")
    
    st.info("سيتم إضافة الشيت الجديد إلى ملف Excel الموجود على GitHub")
    
    col1, col2 = st.columns(2)
    
    with col1:
        new_sheet_name = st.text_input(
            "📝 اسم الشيت الجديد:", 
            key="new_sheet_name_github",
            placeholder="مثال: قسم الميكانيكا, محطة الكهرباء, صيانة المضخات"
        )
        
        if new_sheet_name:
            if new_sheet_name in sheets_edit:
                st.error(f"❌ الشيت '{new_sheet_name}' موجود بالفعل في الملف!")
            else:
                st.success(f"✅ اسم الشيت '{new_sheet_name}' متاح")
    
    with col2:
        use_default = st.checkbox("استخدام الأعمدة الافتراضية", value=True, key="use_default_columns")
        
        if use_default:
            columns_list = APP_CONFIG["DEFAULT_SHEET_COLUMNS"]
            st.info(f"📊 الأعمدة: {', '.join(columns_list)}")
        else:
            columns_text = st.text_area(
                "✏️ الأعمدة (كل عمود في سطر):", 
                value="\n".join(APP_CONFIG["DEFAULT_SHEET_COLUMNS"]), 
                key="custom_columns",
                height=150
            )
            columns_list = [col.strip() for col in columns_text.split("\n") if col.strip()]
            if not columns_list:
                columns_list = APP_CONFIG["DEFAULT_SHEET_COLUMNS"]
    
    st.markdown("---")
    
    # معاينة
    st.markdown("### 📋 معاينة الشيت الجديد")
    preview_df = pd.DataFrame(columns=columns_list)
    st.dataframe(preview_df, use_container_width=True)
    st.caption(f"📊 عدد الأعمدة: {len(columns_list)} | سيتم إنشاء شيت فارغ بهذه الأعمدة")
    
    st.markdown("---")
    
    # زر الإنشاء
    if st.button("✅ إنشاء وإضافة الشيت إلى GitHub", key="create_sheet_github_btn", type="primary", use_container_width=True):
        if not new_sheet_name:
            st.error("❌ الرجاء إدخال اسم الشيت")
            return sheets_edit
        
        # تنظيف اسم الشيت
        clean_name = re.sub(r'[\\/*?:"<>|]', '_', new_sheet_name.strip())
        if clean_name != new_sheet_name:
            st.warning(f"⚠ تم تعديل اسم الشيت إلى: {clean_name}")
            new_sheet_name = clean_name
        
        if new_sheet_name in sheets_edit:
            st.error(f"❌ الشيت '{new_sheet_name}' موجود بالفعل في الملف!")
            return sheets_edit
        
        try:
            with st.spinner("جاري إنشاء الشيت ورفعه إلى GitHub..."):
                # إنشاء DataFrame جديد
                new_df = pd.DataFrame(columns=columns_list)
                sheets_edit[new_sheet_name] = new_df
                
                # حفظ ورفع إلى GitHub
                commit_msg = f"إضافة شيت جديد: {new_sheet_name} بواسطة {st.session_state.get('username', 'user')}"
                
                if save_to_github(sheets_edit, commit_msg):
                    st.success(f"✅ تم إنشاء الشيت '{new_sheet_name}' بنجاح ورفعه إلى GitHub!")
                    
                    # إضافة تكوين المعدات
                    if new_sheet_name not in equipment_config:
                        equipment_config[new_sheet_name] = {
                            "equipment_list": [], 
                            "created_at": datetime.now().isoformat()
                        }
                        save_equipment_config(equipment_config)
                    
                    # مسح الكاش وإعادة التحميل
                    st.cache_data.clear()
                    st.balloons()
                    st.rerun()
                else:
                    st.error("❌ فشل رفع الشيت إلى GitHub")
                    return sheets_edit
                    
        except Exception as e:
            st.error(f"❌ حدث خطأ: {str(e)}")
            return sheets_edit
    
    # عرض الشيتات الموجودة
    st.markdown("---")
    st.markdown("### 📋 الشيتات الموجودة حالياً على GitHub:")
    if sheets_edit:
        for sheet_name in sheets_edit.keys():
            st.write(f"- {sheet_name}")
    else:
        st.info("لا توجد شيتات بعد")
    
    return sheets_edit

def add_new_event(sheets_edit, sheet_name, equipment_list):
    """إضافة حدث جديد"""
    st.markdown(f"### إضافة حدث جديد في شيت: {sheet_name}")
    
    if not equipment_list:
        st.warning("⚠ لا توجد معدات مضافة. يرجى إضافة معدات أولاً")
        return sheets_edit
    
    with st.form(key="add_event_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            selected_equipment = st.selectbox("اختر المعدة:", equipment_list)
            event_date = st.date_input("التاريخ:", value=datetime.now())
            event_desc = st.text_area("الحدث/العطل:", height=100)
        
        with col2:
            correction_desc = st.text_area("الإجراء التصحيحي:", height=100)
            servised_by = st.text_input("تم بواسطة:")
            tones = st.text_input("الطن:")
        
        notes = st.text_area("ملاحظات:")
        
        if st.form_submit_button("إضافة الحدث", type="primary"):
            df = sheets_edit[sheet_name].copy()
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
            
            commit_msg = f"إضافة حدث جديد في {sheet_name} بواسطة {st.session_state.get('username', 'user')}"
            if save_to_github(sheets_edit, commit_msg):
                st.cache_data.clear()
                st.success("✅ تم إضافة الحدث بنجاح ورفعه إلى GitHub!")
                st.rerun()
    
    return sheets_edit

def manage_equipment(sheet_name, config):
    """إدارة المعدات"""
    st.markdown(f"### إدارة المعدات في شيت: {sheet_name}")
    equipment_list = get_sheet_equipment(sheet_name, config)
    
    if equipment_list:
        st.markdown("#### المعدات الحالية:")
        for eq in equipment_list:
            st.markdown(f"- {eq}")
    else:
        st.info("لا توجد معدات مضافة")
    
    st.markdown("---")
    
    new_equipment = st.text_input("اسم المعدة الجديدة:", key="new_equipment_name")
    if st.button("➕ إضافة معدة", key="add_equipment_btn"):
        if new_equipment:
            success, msg = add_equipment_to_sheet(sheet_name, new_equipment, config)
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

def manage_data_edit(sheets_edit, equipment_config):
    """إدارة البيانات الرئيسية"""
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
                    equipment_list = get_sheet_equipment(sheet_name, equipment_config)
                    display_sheet_data(sheet_name, df, equipment_list, f"view_{sheet_name}")
                    
                    with st.expander("✏️ تعديل مباشر", expanded=False):
                        edited_df = st.data_editor(
                            df.astype(str), 
                            num_rows="dynamic", 
                            use_container_width=True, 
                            key=f"editor_{sheet_name}"
                        )
                        if st.button(f"💾 حفظ", key=f"save_{sheet_name}"):
                            sheets_edit[sheet_name] = edited_df.astype(object)
                            commit_msg = f"تعديل بيانات في {sheet_name} بواسطة {st.session_state.get('username', 'user')}"
                            if save_to_github(sheets_edit, commit_msg):
                                st.cache_data.clear()
                                st.success("تم الحفظ والرفع إلى GitHub!")
                                st.rerun()
    
    with tabs_edit[1]:
        if sheets_edit:
            sheet_name = st.selectbox("اختر الشيت:", list(sheets_edit.keys()), key="add_event_sheet")
            equipment_list = get_sheet_equipment(sheet_name, equipment_config)
            if not equipment_list:
                st.warning(f"لا توجد معدات في '{sheet_name}'. أضف معدات أولاً")
            else:
                sheets_edit = add_new_event(sheets_edit, sheet_name, equipment_list)
    
    with tabs_edit[2]:
        if sheets_edit:
            sheet_name = st.selectbox("اختر الشيت:", list(sheets_edit.keys()), key="manage_eq_sheet")
            manage_equipment(sheet_name, equipment_config)
    
    with tabs_edit[3]:
        sheets_edit = add_new_sheet_to_github(sheets_edit, equipment_config)
    
    return sheets_edit

# ------------------------------- الواجهة الرئيسية -------------------------------
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

equipment_config = load_equipment_config()

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

tabs_list = ["🔍 بحث متقدم"]

if can_edit:
    tabs_list.append("🛠 تعديل وإدارة البيانات")

tabs = st.tabs(tabs_list)

with tabs[0]:
    st.header("نظام البحث المتقدم")
    search_across_sheets(all_sheets, equipment_config)

if can_edit and len(tabs) > 1:
    with tabs[1]:
        st.header("تعديل وإدارة البيانات")
        sheets_edit = manage_data_edit(sheets_edit, equipment_config)

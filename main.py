import flet as ft
from google import genai
from google.genai import types
import json
import datetime
import threading
import time
import os

# ========================================================
# --- محرك التخزين المحلي الأصيل ---
# ========================================================
STORAGE_FILE = os.path.join(os.environ.get("HOME", os.getcwd()), "carbapp_storage.json")

def get_storage(key, default=None):
    try:
        if os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(key, default)
    except: pass
    return default

def set_storage(key, value):
    data = {}
    try:
        if os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    except: pass
    data[key] = value
    try:
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except: pass

client = genai.Client(api_key="AQ.Ab8RN6Irz0KbpLAAqr-vacwrVx3yvmDnR724K4Xolq5LR2QImg")

def main(page: ft.Page):
    # --- 1. إعدادات الصفحة والنمط التكيفي ---
    page.title = "نظام إدارة السكري"
    page.rtl = True  
    page.theme = ft.Theme(color_scheme_seed="teal", use_material3=True)
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window_width = 420 
    page.window_height = 800
    page.horizontal_alignment = "center"
    page.padding = 0

    def toggle_theme(e):
        page.theme_mode = ft.ThemeMode.DARK if page.theme_mode == ft.ThemeMode.LIGHT else ft.ThemeMode.LIGHT
        theme_icon.icon = ft.Icons.DARK_MODE if page.theme_mode == ft.ThemeMode.LIGHT else ft.Icons.LIGHT_MODE
        page.update()

    theme_icon = ft.IconButton(icon=ft.Icons.DARK_MODE, icon_color="white", on_click=toggle_theme)

    app_header = ft.Container(
        content=ft.Row([
            ft.Container(width=40), 
            ft.Text("نظام إدارة السكري", size=24, color="white", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, expand=True),
            theme_icon
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        gradient=ft.LinearGradient(begin=ft.Alignment(-1.0, -1.0), end=ft.Alignment(1.0, 1.0), colors=["#0F766E", "#0284C7"]),
        padding=ft.Padding(left=20, top=50, right=20, bottom=20),
        border_radius=ft.BorderRadius(top_left=0, top_right=0, bottom_left=30, bottom_right=30),
        shadow=ft.BoxShadow(spread_radius=1, blur_radius=10, color="black26", offset=ft.Offset(0, 5))
    )

    # --- 2. إدارة السجل والأنسولين النشط ---
    def load_history():
        return get_storage("user_history", [])

    def save_history(data):
        set_storage("user_history", data)

    def log_dose(dose, bg):
        if dose <= 0: return
        history = load_history()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        history.append({"time": now_str, "dose": dose, "bg": bg})
        save_history(history)
        page.snack_bar = ft.SnackBar(ft.Text("تم تسجيل الجرعة بنجاح! 💉", weight=ft.FontWeight.BOLD), bgcolor="green")
        page.snack_bar.open = True
        page.update()

    def calculate_iob():
        history = load_history()
        now = datetime.datetime.now()
        iob = 0.0
        active_time_mins = 240 
        for record in history:
            try:
                dt = datetime.datetime.strptime(record["time"], "%Y-%m-%d %H:%M")
                diff_mins = (now - dt).total_seconds() / 60
                if 0 <= diff_mins < active_time_mins:
                    iob += record["dose"] * (1 - (diff_mins / active_time_mins))
            except: pass
        return max(0.0, iob)

    # --- 3. المنبه والتنبيهات ---
    def dismiss_alarm(e):
        alarm_dialog.open = False
        page.update()

    alarm_dialog = ft.AlertDialog(
        title=ft.Row([ft.Icon(ft.Icons.ALARM, color="red"), ft.Text("حان وقت التنبيه!", weight=ft.FontWeight.BOLD, color="red")]),
        content=ft.Text("", size=18, text_align="center", weight=ft.FontWeight.BOLD),
        actions=[ft.ElevatedButton("حسناً، تم", on_click=dismiss_alarm, bgcolor="red", color="white", icon=ft.Icons.CHECK_CIRCLE)],
        shape=ft.RoundedRectangleBorder(radius=20), modal=True
    )
    page.overlay.append(alarm_dialog)

    # --- 4. حقول الإدخال الذكية ---
    def custom_textfield(label, icon, value="", multiline=False, helper_text=None, disabled=False):
        return ft.TextField(
            label=label, value=value, prefix_icon=icon, border_radius=15, filled=True,
            border_color="transparent", multiline=multiline,
            keyboard_type="text" if multiline else "number", disabled=disabled,
            text_style=ft.TextStyle(weight=ft.FontWeight.BOLD),
            hint_text=helper_text
        )

    # ========================================================
    # --- 5. قسم الحاسبة الذكية والصور ---
    # ========================================================
    selected_images_paths = []
    images_row = ft.Row(wrap=True, spacing=10, alignment=ft.MainAxisAlignment.CENTER)
    
    current_bg_input = custom_textfield("مستوى السكر الحالي", ft.Icons.MONITOR_HEART)
    description_input = custom_textfield("ملاحظة إضافية للذكاء الاصطناعي (اختياري)", ft.Icons.EDIT_NOTE, multiline=True)
    extracted_carbs_input = custom_textfield("صافي الكارب (جم)", ft.Icons.CALCULATE, helper_text="الرقم المستخرج من الذكاء الاصطناعي")
    
    loading_ring = ft.Container(content=ft.Column([ft.ProgressRing(stroke_width=4), ft.Text("الذكاء الاصطناعي يحلل...", weight=ft.FontWeight.BOLD)], horizontal_alignment="center"), alignment=ft.Alignment(0.0, 0.0), visible=False)
    
    ai_details_card_content = ft.Column(spacing=10)
    ai_details_card = ft.Container(border_radius=20, padding=20, visible=False, content=ai_details_card_content)

    result_card_content = ft.Column(spacing=10)
    result_card = ft.Container(border_radius=20, padding=20, visible=False, content=result_card_content)
    final_dose_state = {"dose": 0.0, "bg": 0.0}

    def update_images_ui():
        images_row.controls.clear()
        for path in selected_images_paths: 
            images_row.controls.append(ft.Image(src=path, width=70, height=70, fit=ft.ImageFit.COVER, border_radius=10))
        page.update()

    def on_file_picked(e: ft.FilePickerResultEvent):
        if e.files:
            selected_images_paths.clear()
            for f in e.files: selected_images_paths.append(f.path)
            update_images_ui()

    # استخدام ft.FilePicker صراحة ليقرأها محرك البناء ويدمج معرض الصور
    file_picker = ft.FilePicker()
    file_picker.on_result = on_file_picked
    page.overlay.append(file_picker)

    upload_zone = ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.CLOUD_UPLOAD, size=40, color="teal"),
            ft.Text("اضغط لإضافة صور الوجبة أو الملصق", weight=ft.FontWeight.BOLD, size=15),
            ft.Text("يمكنك دمج أكثر من صورة للتحليل", size=11)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
        padding=ft.Padding(left=20, right=20, top=20, bottom=20),
        border=ft.Border(top=ft.BorderSide(width=2, color="teal"), bottom=ft.BorderSide(width=2, color="teal"), left=ft.BorderSide(width=2, color="teal"), right=ft.BorderSide(width=2, color="teal")),
        border_radius=20,
        ink=True, on_click=lambda _: file_picker.pick_files(allow_multiple=True)
    )

    def analyze_meal(e):
        if not selected_images_paths and not description_input.value:
            page.snack_bar = ft.SnackBar(ft.Text("الرجاء إرفاق صورة للوجبة أو كتابة وصفها!"), bgcolor="red")
            page.snack_bar.open = True; page.update(); return
        
        loading_ring.visible = True; ai_details_card.visible = False; result_card.visible = False; page.update()
        try:
            prompt_text = f"""أنت خبير تغذية سريرية لمرضى السكري. حلل الصور المرفقة إن وجدت، أو الوصف التالي: '{description_input.value}'.
            الرد **فقط** بتنسيق JSON: {{"net_carbs_grams": 0, "meal_description": "وصف دقيق", "impact_alert": "تأثير الوجبة", "items": [{{"name": "المكون", "weight_g": 0, "carbs_g": 0}}]}}"""
            
            parts = [prompt_text]
            for path in selected_images_paths:
                with open(path, "rb") as image_file: parts.append(types.Part.from_bytes(data=image_file.read(), mime_type='image/jpeg'))
            
            response = client.models.generate_content(model='gemini-3.6-flash', contents=parts)
            raw_text = response.text.strip()
            if raw_text.startswith("```json"): raw_text = raw_text[7:-3]
            elif raw_text.startswith("```"): raw_text = raw_text[3:-3]
            data = json.loads(raw_text)
            
            extracted_carbs_input.value = str(data.get("net_carbs_grams", 0))
            
            ai_details_card_content.controls.clear()
            ai_details_card_content.controls.append(ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME, color="teal"), ft.Text("تحليل الذكاء الاصطناعي", weight=ft.FontWeight.BOLD, size=18)]))
            ai_details_card_content.controls.append(ft.Text(data.get("meal_description", "تم التحليل بنجاح."), size=14))
            
            items_wrap = ft.Row(wrap=True, spacing=8)
            for item in data.get("items", []):
                items_wrap.controls.append(
                    ft.Container(content=ft.Row([ft.Icon(ft.Icons.RESTAURANT, size=12), ft.Text(f"{item['name']} ({item['weight_g']}ج)", weight=ft.FontWeight.BOLD, size=12)], spacing=4), bgcolor="bluegrey200", padding=ft.Padding(left=10, right=10, top=6, bottom=6), border_radius=15)
                )
            ai_details_card_content.controls.append(items_wrap)
            
            impact = data.get("impact_alert", "")
            if impact: ai_details_card_content.controls.append(ft.Container(content=ft.Row([ft.Icon(ft.Icons.WARNING_AMBER, color="orange"), ft.Text(impact, weight=ft.FontWeight.BOLD, size=12, expand=True)]), bgcolor="orange100", padding=12, border_radius=10, margin=ft.Margin(left=0, right=0, top=5, bottom=0)))
            ai_details_card.visible = True
        except Exception as ex: 
            page.snack_bar = ft.SnackBar(ft.Text(f"حدث خطأ أثناء تحليل الصور"), bgcolor="red"); page.snack_bar.open = True
        finally: loading_ring.visible = False; page.update()

    def calculate_final_dose(e):
        try:
            carbs = float(extracted_carbs_input.value) if extracted_carbs_input.value else 0.0
            bg = float(current_bg_input.value) if current_bg_input.value else float(get_storage("target_bg", 100.0))
            icr = float(get_storage("icr", 10.0))
            isf = float(get_storage("isf", 50.0))
            target = float(get_storage("target_bg", 100.0))
            
            iob = calculate_iob()
            meal_dose = carbs / icr
            correction_dose = (bg - target) / isf
            total_dose = max(0.0, meal_dose + correction_dose - iob)
            
            final_dose_state["dose"] = total_dose; final_dose_state["bg"] = bg
            result_card_content.controls.clear()
            
            result_card_content.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text("الجرعة النهائية المقترحة", color="white", size=12),
                        ft.Row([ft.Text(f"{round(total_dose, 1)}", weight=ft.FontWeight.BOLD, size=36, color="white"), ft.Text("وحدة", size=18, color="white")], alignment=ft.MainAxisAlignment.CENTER)
                    ], horizontal_alignment="center", spacing=0),
                    bgcolor="teal", padding=20, border_radius=15, alignment=ft.Alignment(0.0, 0.0)
                )
            )
            
            breakdown = ft.Container(
                content=ft.Column([
                    ft.Row([ft.Icon(ft.Icons.FASTFOOD, size=18), ft.Text(f"جرعة الطعام: {round(meal_dose, 1)} وحدة", weight=ft.FontWeight.BOLD, size=14)]),
                    ft.Row([ft.Icon(ft.Icons.HEALING, size=18), ft.Text(f"تصحيح السكر: {round(correction_dose, 1)} وحدة", weight=ft.FontWeight.BOLD, size=14)]),
                    ft.Row([ft.Icon(ft.Icons.WATER_DROP, size=18, color="red"), ft.Text(f"أنسولين متبقي (يُخصم): -{round(iob, 1)} وحدة", weight=ft.FontWeight.BOLD, size=14, color="red")]),
                ], spacing=8), padding=10
            )
            result_card_content.controls.append(breakdown)
            result_card_content.controls.append(ft.ElevatedButton("اعتماد وتسجيل في السجل الطبي", icon=ft.Icons.CHECK_CIRCLE, on_click=lambda _: log_dose(final_dose_state["dose"], final_dose_state["bg"]), style=ft.ButtonStyle(bgcolor="green", color="white", padding=15), width=400))
            result_card.visible = True; page.update()
        except: 
            page.snack_bar = ft.SnackBar(ft.Text("يرجى التأكد من الأرقام المدخلة!"), bgcolor="red"); page.snack_bar.open = True; page.update()

    calculator_view = ft.Container(
        padding=20,
        content=ft.Column([
            ft.Divider(height=10, color="transparent"),
            current_bg_input, 
            upload_zone, 
            images_row,
            description_input,
            ft.ElevatedButton("(الخطوة الأولى) تحليل الذكاء الاصطناعي", icon=ft.Icons.AUTO_AWESOME, on_click=analyze_meal, style=ft.ButtonStyle(bgcolor="teal", color="white", padding=18, shape=ft.RoundedRectangleBorder(radius=15)), width=400),
            loading_ring, ai_details_card,
            ft.Divider(color="grey"),
            extracted_carbs_input,
            ft.ElevatedButton("(الخطوة الثانية) حساب الجرعة", icon=ft.Icons.CALCULATE, on_click=calculate_final_dose, style=ft.ButtonStyle(bgcolor="blue", color="white", padding=18, shape=ft.RoundedRectangleBorder(radius=15)), width=400),
            result_card
        ], horizontal_alignment="center", spacing=12, scroll="auto")
    )

    # ========================================================
    # --- 6. قسم مركز التنبيهات ---
    # ========================================================
    filter_state = {"current": "all"}
    
    reminders_list = ft.Column(spacing=15, scroll="hidden", expand=True)
    filters_row = ft.Row(scroll="hidden", spacing=10)

    def update_filters_ui():
        filters_row.controls.clear()
        curr = filter_state["current"]
        def create_chip(label, f_type, is_active):
            return ft.Container(content=ft.Text(label, weight=ft.FontWeight.BOLD, color="white" if is_active else "black", size=13), bgcolor="teal" if is_active else "grey200", padding=ft.Padding(left=16, right=16, top=8, bottom=8), border_radius=20, on_click=lambda e, ft_type=f_type: apply_filter(ft_type))
        filters_row.controls.extend([create_chip("الكل 📋", "all", curr == "all"), create_chip("أدوية 💊", "med", curr == "med"), create_chip("مواعيد 📅", "appt", curr == "appt"), create_chip("صرف 🔄", "refill", curr == "refill")])
        page.update()

    def apply_filter(f_type): 
        filter_state["current"] = f_type
        update_filters_ui()
        refresh_rems()

    rem_type = ft.Dropdown(label="نوع التنبيه", options=[ft.dropdown.Option("med", "💊 تذكير دواء"), ft.dropdown.Option("appt", "📅 موعد طبي"), ft.dropdown.Option("refill", "🔄 إعادة صرف")], value="med", border_radius=15, filled=True, border_color="transparent", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD))
    med_freq = ft.Dropdown(label="التكرار", options=[ft.dropdown.Option("مرة يومياً", "مرة واحدة يومياً"), ft.dropdown.Option("مرتين يومياً", "مرتين يومياً"), ft.dropdown.Option("عند الحاجة", "عند الحاجة")], value="مرة يومياً", border_radius=15, filled=True, border_color="transparent", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD), visible=True)
    appt_day_before = ft.Checkbox(label="تذكير قبل الموعد بيوم", value=False, label_style=ft.TextStyle(weight=ft.FontWeight.BOLD), visible=False)

    rem_title = custom_textfield("عنوان التنبيه", ft.Icons.TITLE)
    
    rem_time_field_1 = custom_textfield("وقت التنبيه (يومياً)", ft.Icons.ACCESS_TIME, disabled=True)
    rem_time_field_2 = custom_textfield("الوقت الثاني (يومياً)", ft.Icons.ACCESS_TIME, disabled=True)
    rem_time_field_2.visible = False

    selected_dt = {}

    def handle_time1_click(e):
        if rem_type.value == "med" and med_freq.value in ["مرة يومياً", "مرتين يومياً"]:
            time_picker_1.pick_time()
        else:
            date_picker_1.pick_date()

    rem_time_container_1 = ft.Container(content=rem_time_field_1, on_click=handle_time1_click)
    rem_time_container_2 = ft.Container(content=rem_time_field_2, on_click=lambda e: time_picker_2.pick_time(), visible=False)

    def on_rem_type_change(e):
        rem_time_field_1.value = ""
        rem_time_field_2.value = ""
        if rem_type.value == "med":
            med_freq.visible = True
            appt_day_before.visible = False
            if med_freq.value == "مرة يومياً":
                rem_time_field_1.label = "وقت التنبيه (يومياً)"
                rem_time_field_1.prefix_icon = ft.Icons.ACCESS_TIME
                rem_time_container_2.visible = False; rem_time_field_2.visible = False
            elif med_freq.value == "مرتين يومياً":
                rem_time_field_1.label = "الوقت الأول (يومياً)"
                rem_time_field_1.prefix_icon = ft.Icons.ACCESS_TIME
                rem_time_container_2.visible = True; rem_time_field_2.visible = True
            else:
                rem_time_field_1.label = "الوقت والتاريخ"
                rem_time_field_1.prefix_icon = ft.Icons.CALENDAR_MONTH
                rem_time_container_2.visible = False; rem_time_field_2.visible = False
        else:
            med_freq.visible = False
            appt_day_before.visible = True
            rem_time_field_1.label = "الوقت والتاريخ"
            rem_time_field_1.prefix_icon = ft.Icons.CALENDAR_MONTH
            rem_time_container_2.visible = False; rem_time_field_2.visible = False
        page.update()

    rem_type.on_change = on_rem_type_change
    med_freq.on_change = on_rem_type_change

    def on_time1_picked(e):
        if time_picker_1.value:
            if rem_type.value == "med" and med_freq.value in ["مرة يومياً", "مرتين يومياً"]:
                rem_time_field_1.value = time_picker_1.value.strftime("%H:%M")
            else:
                selected_dt["time"] = time_picker_1.value
                rem_time_field_1.value = datetime.datetime.combine(selected_dt["date"], selected_dt["time"]).strftime("%Y-%m-%d %H:%M")
            page.update()

    def on_date1_picked(e):
        if date_picker_1.value: selected_dt["date"] = date_picker_1.value; time_picker_1.pick_time()

    def on_time2_picked(e):
        if time_picker_2.value:
            rem_time_field_2.value = time_picker_2.value.strftime("%H:%M")
            page.update()

    date_picker_1 = ft.DatePicker(on_change=on_date1_picked)
    time_picker_1 = ft.TimePicker(on_change=on_time1_picked)
    time_picker_2 = ft.TimePicker(on_change=on_time2_picked)
    page.overlay.extend([date_picker_1, time_picker_1, time_picker_2])

    def load_rems(): return get_storage("user_rems", [])
    def save_rems(data): set_storage("user_rems", data)
    
    def delete_rem(rem_id): 
        save_rems([d for d in load_rems() if d['id'] != rem_id])
        page.snack_bar = ft.SnackBar(ft.Text("تم الإنجاز!", weight=ft.FontWeight.BOLD), bgcolor="green")
        page.snack_bar.open = True
        refresh_rems()
    
    def add_rem_click(e):
        if not rem_title.value or not rem_time_field_1.value: 
            page.snack_bar = ft.SnackBar(ft.Text("أكمل الحقول الأساسية!"), bgcolor="red"); page.snack_bar.open = True; page.update(); return
        if rem_time_field_2.visible and not rem_time_field_2.value:
            page.snack_bar = ft.SnackBar(ft.Text("أكمل حقل الوقت الثاني!"), bgcolor="red"); page.snack_bar.open = True; page.update(); return
            
        times = [rem_time_field_1.value]
        if rem_time_field_2.visible: times.append(rem_time_field_2.value)
        final_time_str = " & ".join(times)

        data = load_rems()
        data.append({"id": max([d.get('id', 0) for d in data] + [0]) + 1, "type": rem_type.value, "title": rem_title.value, "time": final_time_str, "freq": med_freq.value if rem_type.value == "med" else None, "day_before": appt_day_before.value if rem_type.value in ["appt", "refill"] else False})
        save_rems(data); rem_title.value = ""; rem_time_field_1.value = ""; rem_time_field_2.value = ""; add_rem_dialog.open = False; refresh_rems()

    add_rem_dialog = ft.AlertDialog(
        title=ft.Row([ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE, color="teal"), ft.Text("إضافة تنبيه", weight=ft.FontWeight.BOLD, color="teal")]),
        content=ft.Column([rem_type, med_freq, appt_day_before, rem_title, rem_time_container_1, rem_time_container_2], tight=True, spacing=15),
        actions=[ft.TextButton("إلغاء", on_click=lambda e: setattr(add_rem_dialog, 'open', False) or page.update()), ft.ElevatedButton("حفظ", icon=ft.Icons.SAVE, on_click=add_rem_click, bgcolor="teal", color="white")],
        shape=ft.RoundedRectangleBorder(radius=20)
    )
    page.overlay.append(add_rem_dialog)

    def refresh_rems():
        reminders_list.controls.clear()
        all_data = load_rems()
        curr = filter_state["current"]
        data = all_data if curr == "all" else [d for d in all_data if d['type'] == curr]

        if not data: reminders_list.controls.append(ft.Container(content=ft.Column([ft.Icon(ft.Icons.NOTIFICATIONS_NONE, size=70, color="grey"), ft.Text("لا توجد تنبيهات", weight=ft.FontWeight.BOLD, size=18)], horizontal_alignment="center"), alignment=ft.Alignment(0.0, 0.0), padding=60))
        else:
            for item in data:
                icon = ft.Icons.MEDICATION if item['type'] == 'med' else (ft.Icons.CALENDAR_MONTH if item['type'] == 'appt' else ft.Icons.REPEAT)
                color = "blue" if item['type'] == 'med' else ("green" if item['type'] == 'appt' else "orange")
                type_str = f"{'دواء' if item['type']=='med' else 'موعد' if item['type']=='appt' else 'صرف'}"
                
                card = ft.Container(
                    content=ft.Column([
                        ft.Row([ft.Icon(icon, color=color, size=20), ft.Text(type_str, weight=ft.FontWeight.BOLD, size=12, color=color), ft.Container(expand=True), ft.Icon(ft.Icons.ACCESS_TIME, size=14), ft.Text(item['time'].replace(" & ", " | "), weight=ft.FontWeight.BOLD, size=12)]),
                        ft.Row([ft.Text(item['title'], weight=ft.FontWeight.BOLD, size=16), ft.Container(expand=True), ft.IconButton(icon=ft.Icons.CHECK_CIRCLE, icon_color="teal", icon_size=32, on_click=lambda e, i=item['id']: delete_rem(i))])
                    ], spacing=10),
                    bgcolor="grey100", padding=15, border_radius=15, border=ft.Border(left=ft.BorderSide(width=6, color=color))
                )
                reminders_list.controls.append(card)
        page.update()

    reminders_view = ft.Container(padding=20, content=ft.Column([ft.Row([ft.Text("مركز التنبيهات", size=24, weight=ft.FontWeight.BOLD), ft.IconButton(icon=ft.Icons.ADD_ALARM, bgcolor="teal", icon_color="white", on_click=lambda e: setattr(add_rem_dialog, 'open', True) or page.update())], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), filters_row, reminders_list], expand=True, scroll="hidden"))

    def alarm_background_loop():
        while True:
            try:
                now = datetime.datetime.now()
                current_full = now.strftime("%Y-%m-%d %H:%M"); current_time = now.strftime("%H:%M")
                five_mins_full = (now + datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M"); five_mins_time = (now + datetime.timedelta(minutes=5)).strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")
                
                data = load_rems(); needs_save = False

                for item in data:
                    targets = item.get("time", "").split(" & ")
                    for target_time in targets:
                        is_daily = len(target_time) == 5
                        cmp_current = current_time if is_daily else current_full
                        cmp_five = five_mins_time if is_daily else five_mins_full

                        notif_5m_key = f"notified_5m_{target_time}_{current_date}" if is_daily else f"notified_5m_{target_time}"
                        if target_time == cmp_five and item.get("last_5m") != notif_5m_key:
                            item["last_5m"] = notif_5m_key; needs_save = True
                            page.snack_bar = ft.SnackBar(ft.Text(f"⏳ اقترب: {item['title']} بعد 5 دقائق!", weight=ft.FontWeight.BOLD)); page.snack_bar.open = True; page.update()

                        notif_now_key = f"notified_now_{target_time}_{current_date}" if is_daily else f"notified_now_{target_time}"
                        if target_time == cmp_current and item.get("last_now") != notif_now_key:
                            item["last_now"] = notif_now_key; needs_save = True
                            alarm_dialog.content.value = item['title']; alarm_dialog.open = True; page.update()

                        if item.get("day_before") and not is_daily:
                            try:
                                dt_target = datetime.datetime.strptime(target_time, "%Y-%m-%d %H:%M")
                                day_before_str = (dt_target - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
                                if day_before_str == current_full and item.get("last_day") != target_time:
                                    item["last_day"] = target_time; needs_save = True
                                    page.snack_bar = ft.SnackBar(ft.Text(f"📅 تذكير غداً: {item['title']}!", weight=ft.FontWeight.BOLD)); page.snack_bar.open = True; page.update()
                            except: pass
                if needs_save: save_rems(data)
            except: pass
            time.sleep(20)

    threading.Thread(target=alarm_background_loop, daemon=True).start()

    # --- 7. قسم المؤشرات الصحية ---
    dash_content = ft.Column(spacing=15, scroll="auto", expand=True)
    
    def delete_history_record(record_time):
        history = load_history()
        history = [r for r in history if r["time"] != record_time]
        save_history(history)
        page.snack_bar = ft.SnackBar(ft.Text("تم حذف الجرعة من السجل", weight=ft.FontWeight.BOLD), bgcolor="red")
        page.snack_bar.open = True
        refresh_dashboard()

    def refresh_dashboard():
        dash_content.controls.clear()
        history = load_history()
        if not history:
            dash_content.controls.append(ft.Container(content=ft.Column([ft.Icon(ft.Icons.INSERT_CHART, size=60, color="grey"), ft.Text("لا توجد بيانات مسجلة", weight=ft.FontWeight.BOLD)], horizontal_alignment="center"), alignment=ft.Alignment(0.0, 0.0), padding=50))
            page.update(); return
        
        valid_bgs = [r["bg"] for r in history if r["bg"] > 0]
        avg_bg = sum(valid_bgs) / len(valid_bgs) if valid_bgs else 0
        iob_now = calculate_iob()

        stats_row = ft.Row([
            ft.Container(content=ft.Column([ft.Icon(ft.Icons.WATER_DROP, color="white"), ft.Text("متوسط السكر", size=11, color="white"), ft.Text(f"{round(avg_bg)}", weight=ft.FontWeight.BOLD, size=18, color="white")]), bgcolor="orange", padding=10, border_radius=15, expand=True),
            ft.Container(content=ft.Column([ft.Icon(ft.Icons.TIMER, color="white"), ft.Text("أنسولين نشط", size=11, color="white"), ft.Text(f"{round(iob_now, 1)}u", weight=ft.FontWeight.BOLD, size=18, color="white")]), bgcolor="blue", padding=10, border_radius=15, expand=True),
        ])
        dash_content.controls.append(stats_row)
        dash_content.controls.append(ft.Row([ft.Icon(ft.Icons.HISTORY, color="teal"), ft.Text("السجل الطبي للجرعات:", weight=ft.FontWeight.BOLD)]))
        
        for r in reversed(history[-15:]): 
            dash_content.controls.append(
                ft.Container(
                    content=ft.ListTile(
                        leading=ft.Icon(ft.Icons.VACCINES, color="blue"), 
                        title=ft.Text(f"الجرعة: {round(r['dose'],1)} وحدة", weight=ft.FontWeight.BOLD), 
                        subtitle=ft.Text(f"السكر: {r['bg']} | {r['time']}", size=11),
                        trailing=ft.IconButton(icon=ft.Icons.DELETE, icon_color="red", on_click=lambda e, t=r['time']: delete_history_record(t))
                    ),
                    bgcolor="grey100", border_radius=10
                )
            )
        page.update()

    dashboard_view = ft.Container(padding=20, content=ft.Column([ft.Text("المؤشرات والتقارير", size=24, weight=ft.FontWeight.BOLD), dash_content], expand=True))

    # --- 8. قسم الإعدادات ---
    def get_setting(key, default): 
        val = get_storage(key)
        return float(val) if val is not None else default

    icr_input = custom_textfield("معامل الكارب (ICR)", ft.Icons.RESTAURANT, str(get_setting("icr", 10.0)), helper_text="جرامات الكارب لكل وحدة")
    isf_input = custom_textfield("معامل الحساسية (ISF)", ft.Icons.HEALING, str(get_setting("isf", 50.0)), helper_text="انخفاض السكر لكل وحدة")
    target_bg_input = custom_textfield("السكر المستهدف", ft.Icons.TRACK_CHANGES, str(get_setting("target_bg", 100.0)), helper_text="السكر المثالي")
    
    def save_settings(e):
        try:
            set_storage("icr", float(icr_input.value))
            set_storage("isf", float(isf_input.value))
            set_storage("target_bg", float(target_bg_input.value))
            page.snack_bar = ft.SnackBar(ft.Text("تم الحفظ بنجاح"), bgcolor="green"); page.snack_bar.open = True; page.update()
        except: pass

    settings_view = ft.Container(padding=20, content=ft.Column([ft.Row([ft.Icon(ft.Icons.SETTINGS, color="teal"), ft.Text("الإعدادات الطبية", size=24, weight=ft.FontWeight.BOLD)]), icr_input, isf_input, target_bg_input, ft.ElevatedButton("حفظ التحديثات", icon=ft.Icons.SAVE, on_click=save_settings, style=ft.ButtonStyle(bgcolor="teal", color="white", padding=18, shape=ft.RoundedRectangleBorder(radius=15)), width=400)], spacing=15))

    # --- 9. إدارة شريط التنقل ---
    main_content = ft.AnimatedSwitcher(content=calculator_view, transition=ft.AnimatedSwitcherTransition.FADE, duration=400)
    
    def on_nav_change(e):
        idx = e.control.selected_index
        if idx == 0: main_content.content = calculator_view
        elif idx == 1: update_filters_ui(); refresh_rems(); main_content.content = reminders_view
        elif idx == 2: refresh_dashboard(); main_content.content = dashboard_view
        else: main_content.content = settings_view
        page.update()

    page.navigation_bar = ft.NavigationBar(
        selected_index=0, on_change=on_nav_change,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.CALCULATE, selected_icon=ft.Icons.CALCULATE, label="الحاسبة"),
            ft.NavigationBarDestination(icon=ft.Icons.NOTIFICATIONS, selected_icon=ft.Icons.NOTIFICATIONS, label="التنبيهات"),
            ft.NavigationBarDestination(icon=ft.Icons.INSERT_CHART, selected_icon=ft.Icons.INSERT_CHART, label="التقارير"),
            ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, selected_icon=ft.Icons.SETTINGS, label="الإعدادات"),
        ]
    )

    page.add(ft.Column([app_header, ft.Container(content=main_content, expand=True)], expand=True, spacing=0))

ft.app(main)

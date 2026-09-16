import flet as ft
import json
import datetime
import asyncio
import os
import base64
import re
import mimetypes
import urllib.request
import urllib.error
import traceback
import logging

# ========================================================
# --- التسجيل ---
# ========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("carbapp")

# ========================================================
# ✅ مفتاح Gemini API (صيغة AQ. الجديدة)
#    يتم إرساله عبر الترويسة x-goog-api-key
# ========================================================
API_KEY = "AQ.Ab8RN6JXvDR4UnUiZgnCxt48cfiKZZWu3v-avW1CdHEQoKkMeg"

# ✅ الرابط بدون ?key= لأننا سنستخدم الترويسة
# ✅ الموديل الأحدث: gemini-2.5-flash
API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.5-flash:generateContent"
)
API_TIMEOUT_SEC = 45
MAX_IMAGE_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_BOLUS = 15.0


# ========================================================
# --- محرك التخزين الهجين ---
# ========================================================
fallback_db = {}


def get_storage(page, key, default=None):
    try:
        if page.client_storage is not None:
            val = page.client_storage.get(key)
            if val is not None:
                return val
    except Exception as ex:
        logger.warning("client_storage.get(%s) failed: %s", key, ex)
    return fallback_db.get(key, default)


def set_storage(page, key, value):
    fallback_db[key] = value
    try:
        if page.client_storage is not None:
            page.client_storage.set(key, value)
    except Exception as ex:
        logger.warning("client_storage.set(%s) failed: %s", key, ex)


def safe_float(val, default=0.0):
    try:
        if val is None or val == "" or val == "None":
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def parse_gemini_json(raw_text):
    raw_text = (raw_text or "").strip()
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as ex:
            logger.error("JSON parse fallback failed: %s", ex)
    raise ValueError("تعذر تحويل رد الذكاء الاصطناعي إلى JSON")


# ========================================================
# --- التطبيق الرئيسي ---
# ========================================================
def main(page: ft.Page):
    page.title = "نظام إدارة السكري"
    page.rtl = True
    page.theme = ft.Theme(color_scheme_seed="teal", use_material3=True)
    page.theme_mode = ft.ThemeMode.LIGHT
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.padding = 0

    try:
        logger.info("Building UI...")
        _build_ui(page)
        logger.info("UI build completed")
    except Exception:
        err_msg = traceback.format_exc()
        logger.exception("UI build failed")
        try:
            page.clean()
            page.add(
                ft.SafeArea(
                    ft.Column(
                        [
                            ft.Text(
                                "⚠️ حدث خطأ أثناء تشغيل التطبيق:",
                                color="red",
                                weight=ft.FontWeight.BOLD,
                                size=18,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    err_msg,
                                    color="white",
                                    size=11,
                                    selectable=True,
                                    rtl=False,
                                ),
                                bgcolor="black",
                                padding=10,
                                border_radius=10,
                                expand=True,
                            ),
                        ],
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                    )
                )
            )
            page.update()
        except Exception:
            logger.exception("Failed to render error screen")


# ========================================================
# --- دالة بناء الواجهة ---
# ========================================================
def _build_ui(page: ft.Page):
    def get_setting(key, default):
        val = get_storage(page, key)
        return safe_float(val, default)

    # -------- Header --------
    def toggle_theme(e):
        page.theme_mode = (
            ft.ThemeMode.DARK
            if page.theme_mode == ft.ThemeMode.LIGHT
            else ft.ThemeMode.LIGHT
        )
        theme_icon.icon = (
            ft.Icons.DARK_MODE
            if page.theme_mode == ft.ThemeMode.LIGHT
            else ft.Icons.LIGHT_MODE
        )
        page.update()

    theme_icon = ft.IconButton(
        icon=ft.Icons.DARK_MODE,
        icon_color="white",
        on_click=toggle_theme,
    )

    app_header = ft.Container(
        content=ft.Row(
            [
                ft.Container(width=40),
                ft.Text(
                    "نظام إدارة السكري",
                    size=22,
                    color="white",
                    weight=ft.FontWeight.BOLD,
                    text_align=ft.TextAlign.CENTER,
                    expand=True,
                ),
                theme_icon,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1.0, -1.0),
            end=ft.Alignment(1.0, 1.0),
            colors=["#0F766E", "#0284C7"],
        ),
        padding=ft.padding.only(left=20, top=50, right=20, bottom=20),
        border_radius=ft.border_radius.only(
            bottom_left=30, bottom_right=30
        ),
        shadow=ft.BoxShadow(
            spread_radius=1,
            blur_radius=10,
            color="black26",
            offset=ft.Offset(0, 5),
        ),
    )

    # -------- السجل و IOB --------
    def load_history():
        return get_storage(page, "user_history") or []

    def save_history(data):
        set_storage(page, "user_history", data)

    def log_dose(dose, bg):
        if dose <= 0:
            return
        history = load_history()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        history.append({"time": now_str, "dose": dose, "bg": bg})
        save_history(history)
        page.snack_bar = ft.SnackBar(
            ft.Text("تم تسجيل الجرعة بنجاح! 💉", weight=ft.FontWeight.BOLD),
            bgcolor="green",
        )
        page.snack_bar.open = True
        page.update()

    def calculate_iob():
        history = load_history()
        now = datetime.datetime.now()
        iob = 0.0
        active_time_mins = 240
        for record in history:
            try:
                dt = datetime.datetime.strptime(
                    record["time"], "%Y-%m-%d %H:%M"
                )
                diff_mins = (now - dt).total_seconds() / 60
                if 0 <= diff_mins < active_time_mins:
                    iob += record["dose"] * (1 - (diff_mins / active_time_mins))
            except Exception as ex:
                logger.warning("IOB skip record: %s", ex)
        return max(0.0, iob)

    # -------- حوار المنبّه --------
    def dismiss_alarm(e):
        alarm_dialog.open = False
        page.update()

    alarm_dialog = ft.AlertDialog(
        title=ft.Row(
            [
                ft.Icon(ft.Icons.ALARM, color="red"),
                ft.Text(
                    "حان وقت التنبيه!",
                    weight=ft.FontWeight.BOLD,
                    color="red",
                ),
            ]
        ),
        content=ft.Text(
            "", size=18, text_align=ft.TextAlign.CENTER,
            weight=ft.FontWeight.BOLD,
        ),
        actions=[
            ft.ElevatedButton(
                "حسناً، تم",
                on_click=dismiss_alarm,
                bgcolor="red",
                color="white",
                icon=ft.Icons.CHECK_CIRCLE,
            )
        ],
        shape=ft.RoundedRectangleBorder(radius=20),
        modal=True,
    )
    page.overlay.append(alarm_dialog)

    # -------- حقل نص مخصص --------
    def custom_textfield(
        label,
        icon,
        value="",
        multiline=False,
        helper_text=None,
        disabled=False,
    ):
        return ft.TextField(
            label=label,
            value=value,
            prefix_icon=icon,
            border_radius=15,
            filled=True,
            border_color="transparent",
            multiline=multiline,
            keyboard_type=(
                ft.KeyboardType.TEXT
                if multiline
                else ft.KeyboardType.NUMBER
            ),
            disabled=disabled,
            text_style=ft.TextStyle(
                weight=ft.FontWeight.BOLD, color="black"
            ),
            label_style=ft.TextStyle(color="grey700"),
            hint_text=helper_text,
        )

    # ====================================================
    # --- قسم الحاسبة الذكية ---
    # ====================================================
    selected_images = []

    images_row = ft.Row(
        wrap=True, spacing=10, alignment=ft.MainAxisAlignment.CENTER
    )
    images_debug = ft.Text("", size=10, color="grey600")

    current_bg_input = custom_textfield(
        "مستوى السكر الحالي", ft.Icons.MONITOR_HEART
    )
    description_input = custom_textfield(
        "ملاحظة إضافية للذكاء الاصطناعي (اختياري)",
        ft.Icons.EDIT_NOTE,
        multiline=True,
    )
    extracted_carbs_input = custom_textfield(
        "صافي الكارب (جم)",
        ft.Icons.CALCULATE,
        helper_text="الرقم المستخرج من الذكاء الاصطناعي",
    )

    loading_ring = ft.Container(
        content=ft.Column(
            [
                ft.ProgressRing(stroke_width=4),
                ft.Text(
                    "الذكاء الاصطناعي يحلل...", weight=ft.FontWeight.BOLD
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        alignment=ft.Alignment(0.0, 0.0),
        visible=False,
    )

    ai_details_card_content = ft.Column(spacing=10)
    ai_details_card = ft.Container(
        border_radius=20,
        padding=20,
        visible=False,
        content=ai_details_card_content,
    )

    result_card_content = ft.Column(spacing=10)
    result_card = ft.Container(
        border_radius=20,
        padding=20,
        visible=False,
        content=result_card_content,
    )
    final_dose_state = {"dose": 0.0, "bg": 0.0}

    def remove_image(idx):
        if 0 <= idx < len(selected_images):
            selected_images.pop(idx)
            update_images_ui()

    def update_images_ui():
        images_row.controls.clear()
        for i, item in enumerate(selected_images):
            # ✅ استخدام src_base64 مع البيانات المحملة مسبقاً
            img = ft.Image(
                src_base64=item.get("base64"),
                width=70,
                height=70,
                fit=ft.BoxFit.COVER,
                border_radius=10,
            )
            # إذا لم تكن base64 متاحة، جرّب المسار المباشر
            if not item.get("base64"):
                img.src = item.get("path")

            images_row.controls.append(
                ft.Stack(
                    [
                        img,
                        ft.Container(
                            content=ft.Icon(
                                ft.Icons.CLOSE, size=14, color="white"
                            ),
                            bgcolor="red",
                            border_radius=10,
                            padding=2,
                            right=0,
                            top=0,
                            on_click=lambda e, idx=i: remove_image(idx),
                        ),
                    ],
                    width=70,
                    height=70,
                )
            )
        if selected_images:
            info = " | ".join(
                f"{it['name']} ({it.get('size_kb', 0)}KB)"
                for it in selected_images
            )
            images_debug.value = f"✅ محمّلة: {info}"
            images_debug.color = "green"
        else:
            images_debug.value = ""
        page.update()

    def on_file_picked(e: ft.FilePickerResultEvent):
        logger.info("on_file_picked: %s", e.files)
        if e.files:
            selected_images.clear()
            for f in e.files:
                path = f.path
                if not path:
                    logger.warning("ملف بدون مسار: %s", f)
                    continue
                try:
                    raw = None
                    read_error = None
                    try:
                        with open(path, "rb") as img_file:
                            raw = img_file.read()
                    except Exception as ex1:
                        read_error = str(ex1)
                        try:
                            if path.startswith("file://"):
                                with open(path[7:], "rb") as img_file:
                                    raw = img_file.read()
                        except Exception as ex2:
                            logger.warning(
                                "فشل فتح الملف: %s | %s", ex1, ex2
                            )

                    if raw is None or len(raw) == 0:
                        logger.warning("الملف فارغ: %s", path)
                        page.snack_bar = ft.SnackBar(
                            ft.Text(f"⚠️ تعذر قراءة الصورة: {read_error}"),
                            bgcolor="orange",
                        )
                        page.snack_bar.open = True
                        continue

                    if len(raw) > MAX_IMAGE_BYTES:
                        logger.warning("الصورة كبيرة: %d بايت", len(raw))
                        page.snack_bar = ft.SnackBar(
                            ft.Text("⚠️ الصورة كبيرة جداً (الحد 4 ميجا)"),
                            bgcolor="orange",
                        )
                        page.snack_bar.open = True
                        continue

                    b64 = base64.b64encode(raw).decode("utf-8")
                    mime, _ = mimetypes.guess_type(path)
                    mime = mime or "image/jpeg"

                    selected_images.append(
                        {
                            "name": f.name or "image",
                            "path": path,
                            "base64": b64,
                            "mime": mime,
                            "size_kb": len(raw) // 1024,
                        }
                    )
                    logger.info(
                        "تم تحميل: %s (%d KB, %s)",
                        f.name,
                        len(raw) // 1024,
                        mime,
                    )
                except Exception as ex:
                    logger.exception("خطأ في قراءة الصورة: %s", ex)
                    page.snack_bar = ft.SnackBar(
                        ft.Text(f"❌ خطأ: {str(ex)[:80]}"), bgcolor="red"
                    )
                    page.snack_bar.open = True
            update_images_ui()

    file_picker = ft.FilePicker()
    file_picker.on_result = on_file_picked
    page.overlay.append(file_picker)

    upload_zone = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.CAMERA_ALT, size=40, color="teal"),
                ft.Text(
                    "اضغط لاختيار صورة من الاستوديو",
                    weight=ft.FontWeight.BOLD,
                    size=15,
                ),
                ft.Text(
                    "💡 لالتقاط صورة جديدة: افتح تطبيق الكاميرا ثم "
                    "اختر الصورة من الاستوديو",
                    size=11,
                    color="grey700",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        ),
        padding=ft.padding.all(20),
        border=ft.border.all(width=2, color="teal"),
        border_radius=20,
        ink=True,
        on_click=lambda _: file_picker.pick_files(
            allow_multiple=True,
            file_type=ft.FilePickerFileType.IMAGE,
        ),
    )

    def _build_gemini_parts():
        prompt_text = (
            "أنت خبير تغذية سريرية لمرضى السكري. حلل الصور المرفقة إن "
            "وجدت، أو الوصف التالي: '"
            f"{description_input.value}'.\n"
            "الرد **فقط** بتنسيق JSON: "
            '{"net_carbs_grams": 0, "meal_description": "وصف دقيق", '
            '"impact_alert": "تأثير الوجبة", '
            '"items": [{"name": "المكون", "weight_g": 0, "carbs_g": 0}]}'
        )
        parts = [{"text": prompt_text}]
        for item in selected_images:
            if item.get("base64"):
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": item["mime"],
                            "data": item["base64"],
                        }
                    }
                )
        return parts

    def _call_gemini(parts):
        """✅ إرسال المفتاح عبر الترويسة x-goog-api-key (للصيغة الجديدة AQ.)."""
        payload = {"contents": [{"parts": parts}]}
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": API_KEY,
            },
        )
        with urllib.request.urlopen(req, timeout=API_TIMEOUT_SEC) as response:
            return response.read().decode("utf-8")

    async def analyze_meal(e):
        # ✅ فحص بسيط للمفتاح (لا يشترط بدء AIza مع الصيغة الجديدة)
        if not API_KEY or len(API_KEY) < 20:
            page.snack_bar = ft.SnackBar(
                ft.Text("⚠️ مفتاح API غير موجود أو غير صالح."),
                bgcolor="red",
            )
            page.snack_bar.open = True
            page.update()
            return

        if not selected_images and not description_input.value:
            page.snack_bar = ft.SnackBar(
                ft.Text("الرجاء إرفاق صورة للوجبة أو كتابة وصفها!"),
                bgcolor="red",
            )
            page.snack_bar.open = True
            page.update()
            return

        loading_ring.visible = True
        ai_details_card.visible = False
        result_card.visible = False
        page.update()

        try:
            parts = _build_gemini_parts()
            logger.info("إرسال %d جزء للتحليل", len(parts))
            res_body = await asyncio.to_thread(_call_gemini, parts)
            res_json = json.loads(res_body)
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
            result_data = parse_gemini_json(raw_text)

            carbs_val = safe_float(result_data.get("net_carbs_grams", 0), 0.0)
            extracted_carbs_input.value = str(carbs_val)

            ai_details_card_content.controls.clear()
            ai_details_card_content.controls.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.AUTO_AWESOME, color="teal"),
                        ft.Text(
                            "تحليل الذكاء الاصطناعي",
                            weight=ft.FontWeight.BOLD,
                            size=18,
                            color="black",
                        ),
                    ]
                )
            )
            ai_details_card_content.controls.append(
                ft.Text(
                    result_data.get("meal_description", "تم التحليل بنجاح."),
                    size=14,
                    color="black",
                )
            )

            items_wrap = ft.Row(wrap=True, spacing=8)
            for item in result_data.get("items", []) or []:
                try:
                    name = item.get("name", "?")
                    weight_g = item.get("weight_g", 0)
                    items_wrap.controls.append(
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Icon(
                                        ft.Icons.RESTAURANT,
                                        size=12,
                                        color="black",
                                    ),
                                    ft.Text(
                                        f"{name} ({weight_g}ج)",
                                        weight=ft.FontWeight.BOLD,
                                        size=12,
                                        color="black",
                                    ),
                                ],
                                spacing=4,
                            ),
                            bgcolor="bluegrey200",
                            padding=ft.padding.symmetric(
                                horizontal=10, vertical=6
                            ),
                            border_radius=15,
                        )
                    )
                except Exception as ex:
                    logger.warning("item parse skipped: %s", ex)
            ai_details_card_content.controls.append(items_wrap)

            impact = result_data.get("impact_alert", "")
            if impact:
                ai_details_card_content.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.WARNING_AMBER, color="orange"
                                ),
                                ft.Text(
                                    impact,
                                    weight=ft.FontWeight.BOLD,
                                    size=12,
                                    expand=True,
                                    color="black",
                                ),
                            ]
                        ),
                        bgcolor="orange100",
                        padding=12,
                        border_radius=10,
                        margin=ft.margin.only(top=5),
                    )
                )
            ai_details_card.visible = True

        except urllib.error.HTTPError as ex:
            logger.error("Gemini HTTP error: %s", ex)
            err_body = ""
            try:
                err_body = ex.read().decode("utf-8")[:300]
            except Exception:
                pass
            logger.error("Response body: %s", err_body)

            if ex.code == 401:
                msg = (
                    "❌ مفتاح API غير صالح (401).\n"
                    "تحقق من المفتاح في aistudio.google.com/apikey"
                )
            elif ex.code == 403:
                msg = "❌ المفتاح لا يملك صلاحية للوصول (403)"
            elif ex.code == 404:
                msg = f"❌ الموديل غير متوفر ({ex.code})"
            elif ex.code == 429:
                msg = "⚠️ تجاوزت الحصة المسموحة. حاول لاحقاً"
            else:
                msg = f"خطأ من الخدمة ({ex.code})"
            page.snack_bar = ft.SnackBar(ft.Text(msg), bgcolor="red")
            page.snack_bar.open = True
        except urllib.error.URLError as ex:
            logger.error("Gemini URL error: %s", ex)
            page.snack_bar = ft.SnackBar(
                ft.Text("لا يوجد اتصال بالإنترنت"), bgcolor="red"
            )
            page.snack_bar.open = True
        except asyncio.TimeoutError:
            page.snack_bar = ft.SnackBar(
                ft.Text("انتهت مهلة الاتصال بالذكاء الاصطناعي"),
                bgcolor="red",
            )
            page.snack_bar.open = True
        except Exception as ex:
            logger.exception("analyze_meal failed: %s", ex)
            page.snack_bar = ft.SnackBar(
                ft.Text(f"تعذر تحليل الوجبة: {str(ex)[:80]}"),
                bgcolor="red",
            )
            page.snack_bar.open = True
        finally:
            loading_ring.visible = False
            page.update()

    def calculate_final_dose(e):
        try:
            carbs = safe_float(extracted_carbs_input.value, 0.0)
            bg = safe_float(
                current_bg_input.value, get_setting("target_bg", 100.0)
            )
            icr = get_setting("icr", 10.0)
            isf = get_setting("isf", 50.0)
            target = get_setting("target_bg", 100.0)
            max_bolus = get_setting("max_bolus", DEFAULT_MAX_BOLUS)

            if icr <= 0 or isf <= 0:
                page.snack_bar = ft.SnackBar(
                    ft.Text("تحقق من الإعدادات: ICR و ISF يجب أن يكونا > 0"),
                    bgcolor="red",
                )
                page.snack_bar.open = True
                page.update()
                return

            if carbs < 0 or bg < 0:
                page.snack_bar = ft.SnackBar(
                    ft.Text("لا يُقبل بأرقام سالبة"), bgcolor="red"
                )
                page.snack_bar.open = True
                page.update()
                return

            iob = calculate_iob()
            meal_dose = carbs / icr
            correction_dose = (bg - target) / isf
            raw_total = max(0.0, meal_dose + correction_dose - iob)

            capped = False
            total_dose = raw_total
            if total_dose > max_bolus:
                total_dose = max_bolus
                capped = True

            final_dose_state["dose"] = total_dose
            final_dose_state["bg"] = bg
            result_card_content.controls.clear()

            result_card_content.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "الجرعة النهائية المقترحة",
                                color="white",
                                size=12,
                            ),
                            ft.Row(
                                [
                                    ft.Text(
                                        f"{round(total_dose, 1)}",
                                        weight=ft.FontWeight.BOLD,
                                        size=36,
                                        color="white",
                                    ),
                                    ft.Text("وحدة", size=18, color="white"),
                                ],
                                alignment=ft.MainAxisAlignment.CENTER,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=0,
                    ),
                    bgcolor="teal",
                    padding=20,
                    border_radius=15,
                    alignment=ft.Alignment(0.0, 0.0),
                )
            )

            if capped:
                result_card_content.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.WARNING_AMBER, color="red"),
                                ft.Text(
                                    f"الجرعة المحسوبة ({round(raw_total, 1)}u) "
                                    f"تجاوزت الحد الآمن ({max_bolus}u). "
                                    "راجع الطبيب.",
                                    weight=ft.FontWeight.BOLD,
                                    size=12,
                                    color="red",
                                    expand=True,
                                ),
                            ]
                        ),
                        bgcolor="red100",
                        padding=12,
                        border_radius=10,
                    )
                )

            breakdown = ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.FASTFOOD, size=18, color="black"
                                ),
                                ft.Text(
                                    f"جرعة الطعام: {round(meal_dose, 1)} وحدة",
                                    weight=ft.FontWeight.BOLD,
                                    size=14,
                                    color="black",
                                ),
                            ]
                        ),
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.HEALING, size=18, color="black"
                                ),
                                ft.Text(
                                    f"تصحيح السكر: {round(correction_dose, 1)} وحدة",
                                    weight=ft.FontWeight.BOLD,
                                    size=14,
                                    color="black",
                                ),
                            ]
                        ),
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.WATER_DROP, size=18, color="red"
                                ),
                                ft.Text(
                                    f"أنسولين متبقي (يُخصم): -{round(iob, 1)} وحدة",
                                    weight=ft.FontWeight.BOLD,
                                    size=14,
                                    color="red",
                                ),
                            ]
                        ),
                    ],
                    spacing=8,
                ),
                padding=10,
            )
            result_card_content.controls.append(breakdown)
            result_card_content.controls.append(
                ft.ElevatedButton(
                    "اعتماد وتسجيل في السجل الطبي",
                    icon=ft.Icons.CHECK_CIRCLE,
                    on_click=lambda _: log_dose(
                        final_dose_state["dose"], final_dose_state["bg"]
                    ),
                    style=ft.ButtonStyle(
                        bgcolor="green", color="white", padding=15
                    ),
                )
            )
            result_card.visible = True
            page.update()
        except Exception as ex:
            logger.exception("calculate_final_dose failed: %s", ex)
            page.snack_bar = ft.SnackBar(
                ft.Text("يرجى التأكد من الأرقام المدخلة!"), bgcolor="red"
            )
            page.snack_bar.open = True
            page.update()

    calculator_view = ft.Container(
        padding=20,
        content=ft.Column(
            [
                ft.Divider(height=10, color="transparent"),
                current_bg_input,
                upload_zone,
                images_row,
                images_debug,
                description_input,
                ft.ElevatedButton(
                    "(الخطوة الأولى) تحليل الذكاء الاصطناعي",
                    icon=ft.Icons.AUTO_AWESOME,
                    on_click=analyze_meal,
                    style=ft.ButtonStyle(
                        bgcolor="teal",
                        color="white",
                        padding=18,
                        shape=ft.RoundedRectangleBorder(radius=15),
                    ),
                ),
                loading_ring,
                ai_details_card,
                ft.Divider(color="grey"),
                extracted_carbs_input,
                ft.ElevatedButton(
                    "(الخطوة الثانية) حساب الجرعة",
                    icon=ft.Icons.CALCULATE,
                    on_click=calculate_final_dose,
                    style=ft.ButtonStyle(
                        bgcolor="blue",
                        color="white",
                        padding=18,
                        shape=ft.RoundedRectangleBorder(radius=15),
                    ),
                ),
                result_card,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    # ====================================================
    # --- مركز التنبيهات ---
    # ====================================================
    filter_state = {"current": "all"}
    reminders_list = ft.Column(
        spacing=15, scroll=ft.ScrollMode.HIDDEN, expand=True
    )
    filters_row = ft.Row(scroll=ft.ScrollMode.HIDDEN, spacing=10)

    def update_filters_ui():
        filters_row.controls.clear()
        curr = filter_state["current"]

        def create_chip(label, f_type, is_active):
            return ft.Container(
                content=ft.Text(
                    label,
                    weight=ft.FontWeight.BOLD,
                    color="white" if is_active else "black",
                    size=13,
                ),
                bgcolor="teal" if is_active else "grey200",
                padding=ft.padding.symmetric(horizontal=16, vertical=8),
                border_radius=20,
                on_click=lambda e, ft_type=f_type: apply_filter(ft_type),
            )

        filters_row.controls.extend(
            [
                create_chip("الكل 📋", "all", curr == "all"),
                create_chip("أدوية 💊", "med", curr == "med"),
                create_chip("مواعيد 📅", "appt", curr == "appt"),
                create_chip("صرف 🔄", "refill", curr == "refill"),
            ]
        )
        page.update()

    def apply_filter(f_type):
        filter_state["current"] = f_type
        update_filters_ui()
        refresh_rems()

    rem_type = ft.Dropdown(
        label="نوع التنبيه",
        label_style=ft.TextStyle(color="black", weight=ft.FontWeight.BOLD),
        options=[
            ft.dropdown.Option(
                key="med",
                content=ft.Text("💊 تذكير دواء", color="black", size=14),
            ),
            ft.dropdown.Option(
                key="appt",
                content=ft.Text("📅 موعد طبي", color="black", size=14),
            ),
            ft.dropdown.Option(
                key="refill",
                content=ft.Text("🔄 إعادة صرف", color="black", size=14),
            ),
        ],
        value="med",
        border_radius=15,
        filled=True,
        fill_color="white",
        bgcolor="white",
        border_color="grey400",
    )

    med_freq = ft.Dropdown(
        label="التكرار",
        label_style=ft.TextStyle(color="black", weight=ft.FontWeight.BOLD),
        options=[
            ft.dropdown.Option(
                key="مرة يومياً",
                content=ft.Text("مرة واحدة يومياً", color="black", size=14),
            ),
            ft.dropdown.Option(
                key="مرتين يومياً",
                content=ft.Text("مرتين يومياً", color="black", size=14),
            ),
            ft.dropdown.Option(
                key="عند الحاجة",
                content=ft.Text("عند الحاجة", color="black", size=14),
            ),
        ],
        value="مرة يومياً",
        border_radius=15,
        filled=True,
        fill_color="white",
        bgcolor="white",
        border_color="grey400",
        visible=True,
    )

    appt_day_before = ft.Checkbox(
        label="تذكير قبل الموعد بيوم",
        value=False,
        label_style=ft.TextStyle(
            weight=ft.FontWeight.BOLD, color="black"
        ),
        visible=False,
    )

    rem_title = custom_textfield("عنوان التنبيه", ft.Icons.TITLE)
    rem_time_field_1 = custom_textfield(
        "وقت التنبيه (يومياً)", ft.Icons.ACCESS_TIME, disabled=True
    )
    rem_time_field_2 = custom_textfield(
        "الوقت الثاني (يومياً)", ft.Icons.ACCESS_TIME, disabled=True
    )
    rem_time_field_2.visible = False

    selected_dt = {}

    def handle_time1_click(e):
        if rem_type.value == "med" and med_freq.value in [
            "مرة يومياً",
            "مرتين يومياً",
        ]:
            time_picker_1.pick_time()
        else:
            date_picker_1.pick_date()

    rem_time_container_1 = ft.Container(
        content=rem_time_field_1, on_click=handle_time1_click
    )
    rem_time_container_2 = ft.Container(
        content=rem_time_field_2,
        on_click=lambda e: time_picker_2.pick_time(),
        visible=False,
    )

    def on_rem_type_change(e):
        rem_time_field_1.value = ""
        rem_time_field_2.value = ""
        if rem_type.value == "med":
            med_freq.visible = True
            appt_day_before.visible = False
            if med_freq.value == "مرة يومياً":
                rem_time_field_1.label = "وقت التنبيه (يومياً)"
                rem_time_field_1.prefix_icon = ft.Icons.ACCESS_TIME
                rem_time_container_2.visible = False
                rem_time_field_2.visible = False
            elif med_freq.value == "مرتين يومياً":
                rem_time_field_1.label = "الوقت الأول (يومياً)"
                rem_time_field_1.prefix_icon = ft.Icons.ACCESS_TIME
                rem_time_container_2.visible = True
                rem_time_field_2.visible = True
            else:
                rem_time_field_1.label = "الوقت والتاريخ"
                rem_time_field_1.prefix_icon = ft.Icons.CALENDAR_MONTH
                rem_time_container_2.visible = False
                rem_time_field_2.visible = False
        else:
            med_freq.visible = False
            appt_day_before.visible = True
            rem_time_field_1.label = "الوقت والتاريخ"
            rem_time_field_1.prefix_icon = ft.Icons.CALENDAR_MONTH
            rem_time_container_2.visible = False
            rem_time_field_2.visible = False
        page.update()

    rem_type.on_change = on_rem_type_change
    med_freq.on_change = on_rem_type_change

    def on_time1_picked(e):
        if time_picker_1.value:
            if rem_type.value == "med" and med_freq.value in [
                "مرة يومياً",
                "مرتين يومياً",
            ]:
                rem_time_field_1.value = time_picker_1.value.strftime("%H:%M")
            else:
                selected_dt["time"] = time_picker_1.value
                if "date" in selected_dt:
                    rem_time_field_1.value = datetime.datetime.combine(
                        selected_dt["date"], selected_dt["time"]
                    ).strftime("%Y-%m-%d %H:%M")
            page.update()

    def on_date1_picked(e):
        if date_picker_1.value:
            selected_dt["date"] = date_picker_1.value
            time_picker_1.pick_time()

    def on_time2_picked(e):
        if time_picker_2.value:
            rem_time_field_2.value = time_picker_2.value.strftime("%H:%M")
            page.update()

    _now = datetime.datetime.now()
    date_picker_1 = ft.DatePicker(
        on_change=on_date1_picked,
        first_date=_now - datetime.timedelta(days=365),
        last_date=_now + datetime.timedelta(days=365 * 10),
        value=_now,
    )
    time_picker_1 = ft.TimePicker(on_change=on_time1_picked)
    time_picker_2 = ft.TimePicker(on_change=on_time2_picked)
    page.overlay.extend([date_picker_1, time_picker_1, time_picker_2])

    def load_rems():
        return get_storage(page, "user_rems") or []

    def save_rems(data):
        set_storage(page, "user_rems", data)

    def delete_rem(rem_id):
        save_rems([d for d in load_rems() if d["id"] != rem_id])
        page.snack_bar = ft.SnackBar(
            ft.Text("تم الإنجاز!", weight=ft.FontWeight.BOLD),
            bgcolor="green",
        )
        page.snack_bar.open = True
        refresh_rems()

    def close_add_dialog(e=None):
        add_rem_dialog.open = False
        page.update()

    def add_rem_click(e):
        if not rem_title.value or not rem_time_field_1.value:
            page.snack_bar = ft.SnackBar(
                ft.Text("أكمل الحقول الأساسية!"), bgcolor="red"
            )
            page.snack_bar.open = True
            page.update()
            return
        if rem_time_field_2.visible and not rem_time_field_2.value:
            page.snack_bar = ft.SnackBar(
                ft.Text("أكمل حقل الوقت الثاني!"), bgcolor="red"
            )
            page.snack_bar.open = True
            page.update()
            return

        times = [rem_time_field_1.value]
        if rem_time_field_2.visible:
            times.append(rem_time_field_2.value)
        final_time_str = " & ".join(times)

        data = load_rems()
        data.append(
            {
                "id": max([d.get("id", 0) for d in data] + [0]) + 1,
                "type": rem_type.value,
                "title": rem_title.value,
                "time": final_time_str,
                "freq": med_freq.value if rem_type.value == "med" else None,
                "day_before": (
                    appt_day_before.value
                    if rem_type.value in ["appt", "refill"]
                    else False
                ),
            }
        )
        save_rems(data)
        rem_title.value = ""
        rem_time_field_1.value = ""
        rem_time_field_2.value = ""
        close_add_dialog()
        refresh_rems()

    add_rem_dialog = ft.AlertDialog(
        title=ft.Row(
            [
                ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE, color="teal"),
                ft.Text(
                    "إضافة تنبيه",
                    weight=ft.FontWeight.BOLD,
                    color="teal",
                ),
            ]
        ),
        content=ft.Column(
            [
                rem_type,
                med_freq,
                appt_day_before,
                rem_title,
                rem_time_container_1,
                rem_time_container_2,
            ],
            tight=True,
            spacing=15,
        ),
        actions=[
            ft.TextButton(
                "إلغاء",
                on_click=close_add_dialog,
                style=ft.ButtonStyle(color="black"),
            ),
            ft.ElevatedButton(
                "حفظ",
                icon=ft.Icons.SAVE,
                on_click=add_rem_click,
                bgcolor="teal",
                color="white",
            ),
        ],
        shape=ft.RoundedRectangleBorder(radius=20),
    )
    page.overlay.append(add_rem_dialog)

    def refresh_rems():
        reminders_list.controls.clear()
        all_data = load_rems()
        curr = filter_state["current"]
        data = (
            all_data
            if curr == "all"
            else [d for d in all_data if d["type"] == curr]
        )

        if not data:
            reminders_list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(
                                ft.Icons.NOTIFICATIONS_NONE,
                                size=70,
                                color="grey",
                            ),
                            ft.Text(
                                "لا توجد تنبيهات",
                                weight=ft.FontWeight.BOLD,
                                size=18,
                                color="black",
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    alignment=ft.Alignment(0.0, 0.0),
                    padding=60,
                )
            )
        else:
            for item in data:
                icon = (
                    ft.Icons.MEDICATION
                    if item["type"] == "med"
                    else (
                        ft.Icons.CALENDAR_MONTH
                        if item["type"] == "appt"
                        else ft.Icons.REPEAT
                    )
                )
                color = (
                    "blue"
                    if item["type"] == "med"
                    else ("green" if item["type"] == "appt" else "orange")
                )
                type_str = (
                    "دواء"
                    if item["type"] == "med"
                    else "موعد" if item["type"] == "appt" else "صرف"
                )

                card = ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(icon, color=color, size=20),
                                    ft.Text(
                                        type_str,
                                        weight=ft.FontWeight.BOLD,
                                        size=12,
                                        color=color,
                                    ),
                                    ft.Container(expand=True),
                                    ft.Icon(
                                        ft.Icons.ACCESS_TIME,
                                        size=14,
                                        color="black",
                                    ),
                                    ft.Text(
                                        item["time"].replace(" & ", " | "),
                                        weight=ft.FontWeight.BOLD,
                                        size=12,
                                        color="black",
                                    ),
                                ]
                            ),
                            ft.Row(
                                [
                                    ft.Text(
                                        item["title"],
                                        weight=ft.FontWeight.BOLD,
                                        size=16,
                                        color="black",
                                    ),
                                    ft.Container(expand=True),
                                    ft.IconButton(
                                        icon=ft.Icons.CHECK_CIRCLE,
                                        icon_color="teal",
                                        icon_size=32,
                                        on_click=lambda e, i=item["id"]: delete_rem(
                                            i
                                        ),
                                    ),
                                ]
                            ),
                        ],
                        spacing=10,
                    ),
                    bgcolor="grey100",
                    padding=15,
                    border_radius=15,
                    border=ft.border.only(
                        left=ft.BorderSide(width=6, color=color)
                    ),
                )
                reminders_list.controls.append(card)
        page.update()

    reminders_view = ft.Container(
        padding=20,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(
                            "مركز التنبيهات",
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            color="black",
                        ),
                        ft.IconButton(
                            icon=ft.Icons.ADD_ALARM,
                            bgcolor="teal",
                            icon_color="white",
                            on_click=lambda e: (
                                setattr(add_rem_dialog, "open", True)
                                or page.update()
                            ),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                filters_row,
                reminders_list,
            ],
            expand=True,
            scroll=ft.ScrollMode.HIDDEN,
        ),
    )

    async def alarm_background_loop():
        while True:
            try:
                now = datetime.datetime.now()
                current_full = now.strftime("%Y-%m-%d %H:%M")
                current_time = now.strftime("%H:%M")
                five_mins_full = (
                    now + datetime.timedelta(minutes=5)
                ).strftime("%Y-%m-%d %H:%M")
                five_mins_time = (now + datetime.timedelta(minutes=5)).strftime(
                    "%H:%M"
                )
                current_date = now.strftime("%Y-%m-%d")

                data = load_rems()
                needs_save = False

                for item in data:
                    targets = item.get("time", "").split(" & ")
                    for target_time in targets:
                        is_daily = len(target_time) == 5
                        cmp_current = (
                            current_time if is_daily else current_full
                        )
                        cmp_five = (
                            five_mins_time if is_daily else five_mins_full
                        )

                        notif_5m_key = (
                            f"notified_5m_{target_time}_{current_date}"
                            if is_daily
                            else f"notified_5m_{target_time}"
                        )
                        if (
                            target_time == cmp_five
                            and item.get("last_5m") != notif_5m_key
                        ):
                            item["last_5m"] = notif_5m_key
                            needs_save = True
                            page.snack_bar = ft.SnackBar(
                                ft.Text(
                                    f"⏳ اقترب: {item['title']} بعد 5 دقائق!",
                                    weight=ft.FontWeight.BOLD,
                                )
                            )
                            page.snack_bar.open = True
                            page.update()

                        notif_now_key = (
                            f"notified_now_{target_time}_{current_date}"
                            if is_daily
                            else f"notified_now_{target_time}"
                        )
                        if (
                            target_time == cmp_current
                            and item.get("last_now") != notif_now_key
                        ):
                            item["last_now"] = notif_now_key
                            needs_save = True
                            alarm_dialog.content.value = item["title"]
                            alarm_dialog.open = True
                            page.update()

                        if item.get("day_before") and not is_daily:
                            try:
                                dt_target = datetime.datetime.strptime(
                                    target_time, "%Y-%m-%d %H:%M"
                                )
                                day_before_str = (
                                    dt_target - datetime.timedelta(days=1)
                                ).strftime("%Y-%m-%d %H:%M")
                                if (
                                    day_before_str == current_full
                                    and item.get("last_day") != target_time
                                ):
                                    item["last_day"] = target_time
                                    needs_save = True
                                    page.snack_bar = ft.SnackBar(
                                        ft.Text(
                                            f"📅 تذكير غداً: {item['title']}!",
                                            weight=ft.FontWeight.BOLD,
                                        )
                                    )
                                    page.snack_bar.open = True
                                    page.update()
                            except Exception as ex:
                                logger.warning("day-before check: %s", ex)
                if needs_save:
                    save_rems(data)
            except Exception as ex:
                logger.exception("alarm loop error: %s", ex)
            await asyncio.sleep(20)

    page.run_task(alarm_background_loop)

    # ====================================================
    # --- المؤشرات الصحية ---
    # ====================================================
    dash_content = ft.Column(
        spacing=15, scroll=ft.ScrollMode.AUTO, expand=True
    )

    def delete_history_record(record_time):
        history = load_history()
        history = [r for r in history if r["time"] != record_time]
        save_history(history)
        page.snack_bar = ft.SnackBar(
            ft.Text("تم حذف الجرعة من السجل", weight=ft.FontWeight.BOLD),
            bgcolor="red",
        )
        page.snack_bar.open = True
        refresh_dashboard()

    def refresh_dashboard():
        dash_content.controls.clear()
        history = load_history()
        if not history:
            dash_content.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(
                                ft.Icons.INSERT_CHART, size=60, color="grey"
                            ),
                            ft.Text(
                                "لا توجد بيانات مسجلة",
                                weight=ft.FontWeight.BOLD,
                                color="black",
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    alignment=ft.Alignment(0.0, 0.0),
                    padding=50,
                )
            )
            page.update()
            return

        valid_bgs = [r["bg"] for r in history if r["bg"] > 0]
        avg_bg = sum(valid_bgs) / len(valid_bgs) if valid_bgs else 0
        iob_now = calculate_iob()

        stats_row = ft.Row(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.WATER_DROP, color="white"),
                            ft.Text("متوسط السكر", size=11, color="white"),
                            ft.Text(
                                f"{round(avg_bg)}",
                                weight=ft.FontWeight.BOLD,
                                size=18,
                                color="white",
                            ),
                        ]
                    ),
                    bgcolor="orange",
                    padding=10,
                    border_radius=15,
                    expand=True,
                ),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.TIMER, color="white"),
                            ft.Text(
                                "أنسولين نشط", size=11, color="white"
                            ),
                            ft.Text(
                                f"{round(iob_now, 1)}u",
                                weight=ft.FontWeight.BOLD,
                                size=18,
                                color="white",
                            ),
                        ]
                    ),
                    bgcolor="blue",
                    padding=10,
                    border_radius=15,
                    expand=True,
                ),
            ]
        )
        dash_content.controls.append(stats_row)
        dash_content.controls.append(
            ft.Row(
                [
                    ft.Icon(ft.Icons.HISTORY, color="teal"),
                    ft.Text(
                        "السجل الطبي للجرعات:",
                        weight=ft.FontWeight.BOLD,
                        color="black",
                    ),
                ]
            )
        )

        for r in reversed(history[-15:]):
            dash_content.controls.append(
                ft.Container(
                    content=ft.ListTile(
                        leading=ft.Icon(ft.Icons.VACCINES, color="blue"),
                        title=ft.Text(
                            f"الجرعة: {round(r['dose'], 1)} وحدة",
                            weight=ft.FontWeight.BOLD,
                            color="black",
                        ),
                        subtitle=ft.Text(
                            f"السكر: {r['bg']} | {r['time']}",
                            size=11,
                            color="grey700",
                        ),
                        trailing=ft.IconButton(
                            icon=ft.Icons.DELETE,
                            icon_color="red",
                            on_click=lambda e, t=r["time"]: delete_history_record(
                                t
                            ),
                        ),
                    ),
                    bgcolor="grey100",
                    border_radius=10,
                )
            )
        page.update()

    dashboard_view = ft.Container(
        padding=20,
        content=ft.Column(
            [
                ft.Text(
                    "المؤشرات والتقارير",
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color="black",
                ),
                dash_content,
            ],
            expand=True,
        ),
    )

    # ====================================================
    # --- الإعدادات ---
    # ====================================================
    icr_input = custom_textfield(
        "معامل الكارب (ICR)",
        ft.Icons.RESTAURANT,
        str(get_setting("icr", 10.0)),
        helper_text="جرامات الكارب لكل وحدة",
    )
    isf_input = custom_textfield(
        "معامل الحساسية (ISF)",
        ft.Icons.HEALING,
        str(get_setting("isf", 50.0)),
        helper_text="انخفاض السكر لكل وحدة",
    )
    target_bg_input = custom_textfield(
        "السكر المستهدف",
        ft.Icons.TRACK_CHANGES,
        str(get_setting("target_bg", 100.0)),
        helper_text="السكر المثالي",
    )
    max_bolus_input = custom_textfield(
        "الجرعة القصوى (وحدة)",
        ft.Icons.SHIELD,
        str(get_setting("max_bolus", DEFAULT_MAX_BOLUS)),
        helper_text="حد أمان لجرعة واحدة",
    )

    def save_settings(e):
        try:
            icr_v = safe_float(icr_input.value, 10.0)
            isf_v = safe_float(isf_input.value, 50.0)
            target_v = safe_float(target_bg_input.value, 100.0)
            maxb_v = safe_float(max_bolus_input.value, DEFAULT_MAX_BOLUS)

            if icr_v <= 0 or isf_v <= 0 or maxb_v <= 0:
                raise ValueError("القيم يجب أن تكون أكبر من صفر")

            set_storage(page, "icr", icr_v)
            set_storage(page, "isf", isf_v)
            set_storage(page, "target_bg", target_v)
            set_storage(page, "max_bolus", maxb_v)

            page.snack_bar = ft.SnackBar(
                ft.Text("تم الحفظ بنجاح"), bgcolor="green"
            )
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            logger.warning("save_settings: %s", ex)
            page.snack_bar = ft.SnackBar(
                ft.Text("قيم غير صحيحة، تحقق من المدخلات"), bgcolor="red"
            )
            page.snack_bar.open = True
            page.update()

    settings_view = ft.Container(
        padding=20,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.SETTINGS, color="teal"),
                        ft.Text(
                            "الإعدادات الطبية",
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            color="black",
                        ),
                    ]
                ),
                icr_input,
                isf_input,
                target_bg_input,
                max_bolus_input,
                ft.ElevatedButton(
                    "حفظ التحديثات",
                    icon=ft.Icons.SAVE,
                    on_click=save_settings,
                    style=ft.ButtonStyle(
                        bgcolor="teal",
                        color="white",
                        padding=18,
                        shape=ft.RoundedRectangleBorder(radius=15),
                    ),
                ),
                ft.Container(
                    content=ft.Text(
                        "⚠️ تنبيه: هذا التطبيق أداة مساعدة فقط ولا يُغني "
                        "عن استشارة الطبيب. راجع مختص الرعاية الصحية قبل "
                        "تعديل جرعاتك.",
                        size=12,
                        color="red",
                        weight=ft.FontWeight.BOLD,
                    ),
                    padding=10,
                    bgcolor="red50",
                    border_radius=10,
                ),
            ],
            spacing=15,
        ),
    )

    # ====================================================
    # --- التنقل ---
    # ====================================================
    main_content = ft.AnimatedSwitcher(
        content=calculator_view,
        transition=ft.AnimatedSwitcherTransition.FADE,
        duration=400,
    )

    def on_nav_change(e):
        idx = e.control.selected_index
        if idx == 0:
            main_content.content = calculator_view
        elif idx == 1:
            update_filters_ui()
            refresh_rems()
            main_content.content = reminders_view
        elif idx == 2:
            refresh_dashboard()
            main_content.content = dashboard_view
        else:
            main_content.content = settings_view
        page.update()

    page.navigation_bar = ft.NavigationBar(
        selected_index=0,
        on_change=on_nav_change,
        destinations=[
            ft.NavigationBarDestination(
                icon=ft.Icons.CALCULATE,
                selected_icon=ft.Icons.CALCULATE,
                label="الحاسبة",
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.NOTIFICATIONS,
                selected_icon=ft.Icons.NOTIFICATIONS,
                label="التنبيهات",
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.INSERT_CHART,
                selected_icon=ft.Icons.INSERT_CHART,
                label="التقارير",
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.SETTINGS,
                selected_icon=ft.Icons.SETTINGS,
                label="الإعدادات",
            ),
        ],
    )

    page.add(
        ft.Column(
            [
                app_header,
                ft.Container(content=main_content, expand=True),
            ],
            expand=True,
            spacing=0,
        )
    )
    page.update()


# ========================================================
# ✅ نقطة الدخول الصحيحة لـ Flet 0.25.2
# ========================================================
if __name__ == "__main__":
    ft.app(target=main)

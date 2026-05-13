import streamlit as st
import requests
import json
from datetime import date, timedelta, datetime


# ─────────────────────────────────────────────────────────────────────────────
# CLASSES  (Module 4 – OOP)
# ─────────────────────────────────────────────────────────────────────────────

class Subject:
    """Represents an academic subject with a display name and colour."""

    def __init__(self, name, color="#378ADD"):
        self.name = name
        self.color = color


class Task:
    """Represents a single academic task (assignment, exam, or study session)."""

    PRIORITIES = ["High", "Medium", "Low"]
    TYPES = ["Assignment", "Exam", "Study session"]

    def __init__(self, title, subject_name, deadline, priority, task_type, estimated_hours=1, notes=""):
        self.title = title
        self.subject_name = subject_name
        self.deadline = deadline
        self.priority = priority
        self.task_type = task_type
        self.estimated_hours = estimated_hours
        self.notes = notes
        self.completed = False
        self.created_on = date.today()
        self.pomodoro_sessions = 0

    def days_until_due(self):
        return (self.deadline - date.today()).days

    def is_overdue(self):
        return not self.completed and self.days_until_due() < 0

    def urgency_score(self):
        """Higher score = needs attention sooner."""
        weight = {"High": 3, "Medium": 2, "Low": 1}
        days = self.days_until_due()
        if days <= 0:
            return 100.0
        return (weight[self.priority] * 10) / days

    def deadline_label(self):
        days = self.days_until_due()
        if self.completed:
            return f"Done · was due {self.deadline.strftime('%d %b')}"
        if self.is_overdue():
            n = abs(days)
            return f"Overdue by {n} day{'s' if n != 1 else ''}"
        if days == 0:
            return "Due today"
        return f"Due in {days} day{'s' if days != 1 else ''}"


class Planner:
    """
    Orchestrates tasks and subjects.
    Provides statistics, weekly planning, and validation.
    """

    def __init__(self, tasks, subjects):
        self.tasks = tasks
        self.subjects = subjects

    def get_subject(self, name):
        for s in self.subjects:
            if s.name == name:
                return s
        return None

    def subject_names(self):
        names = []
        for s in self.subjects:
            names.append(s.name)
        return names

    def subject_exists(self, name):
        for s in self.subjects:
            if s.name == name:
                return True
        return False

    def get_stats(self):
        total = len(self.tasks)
        completed = 0
        overdue = 0
        due_this_week = 0
        for t in self.tasks:
            if t.completed:
                completed = completed + 1
            if t.is_overdue():
                overdue = overdue + 1
            if not t.completed and 0 <= t.days_until_due() <= 7:
                due_this_week = due_this_week + 1
        pct = round(completed / total * 100) if total > 0 else 0
        return {
            "total": total,
            "completed": completed,
            "overdue": overdue,
            "due_this_week": due_this_week,
            "completion_pct": pct,
        }

    def get_stats_by_subject(self):
        result = {}
        for s in self.subjects:
            subject_tasks = []
            for t in self.tasks:
                if t.subject_name == s.name:
                    subject_tasks.append(t)
            total = len(subject_tasks)
            completed = 0
            for t in subject_tasks:
                if t.completed:
                    completed = completed + 1
            pct = round(completed / total * 100) if total > 0 else 0
            result[s.name] = {"total": total, "completed": completed, "pct": pct}
        return result

    def generate_study_plan(self, session_hours, blocked_dates):
        """
        Generates a smart study plan that spreads task work across available days.

        For each pending task:
        - Calculates how many sessions are needed (estimated_hours / session_hours)
        - Works BACKWARDS from the deadline, filling free days
        - Respects blocked_dates (e.g. imported exam days)
        - Never puts more than 2 sessions on one day
        - Adds a buffer day before the deadline

        Returns {date: [{"task": task, "hours": float, "session": int}]}
        for the next 14 days.
        """
        plan = {}
        for i in range(14):
            day = date.today() + timedelta(days=i)
            plan[day] = []

        # track hours already scheduled per day
        hours_per_day = {}
        for day in plan:
            hours_per_day[day] = 0

        # sort tasks by deadline, soonest first
        pending = []
        for t in self.tasks:
            if not t.completed:
                pending.append(t)
        for i in range(1, len(pending)):
            current = pending[i]
            j = i - 1
            while j >= 0 and pending[j].deadline > current.deadline:
                pending[j + 1] = pending[j]
                j = j - 1
            pending[j + 1] = current

        max_hours_per_day = session_hours * 2  # max 2 sessions per day

        for task in pending:
            hours_left = task.estimated_hours
            days_until = task.days_until_due()

            if days_until < 0:
                # overdue — show on today
                if date.today() in plan:
                    plan[date.today()].append({
                        "task": task, "hours": hours_left, "session": 1
                    })
                continue

            # work backwards from deadline (with 1 day buffer)
            deadline_day = task.deadline
            buffer_day = deadline_day - timedelta(days=1)

            # collect available days before deadline in reverse order
            available_days = []
            for i in range(days_until):
                candidate = date.today() + timedelta(days=i)
                if candidate >= deadline_day:
                    break
                if candidate == buffer_day:
                    continue  # skip buffer day
                if candidate.isoformat() in blocked_dates:
                    continue  # skip blocked/exam days
                if candidate in plan:
                    available_days.append(candidate)

            # reverse so we fill from furthest to closest
            available_days.reverse()

            session_num = 1
            for day in available_days:
                if hours_left <= 0:
                    break
                room = max_hours_per_day - hours_per_day[day]
                if room <= 0:
                    continue
                scheduled = min(session_hours, hours_left, room)
                if scheduled <= 0:
                    continue
                plan[day].append({
                    "task": task, "hours": scheduled, "session": session_num
                })
                hours_per_day[day] = hours_per_day[day] + scheduled
                hours_left = hours_left - scheduled
                session_num = session_num + 1

            # if hours remain and deadline is within plan window, put on deadline day
            if hours_left > 0 and deadline_day in plan:
                plan[deadline_day].append({
                    "task": task, "hours": hours_left, "session": session_num
                })

        return plan

    def get_weekly_plan(self):
        """Returns {date: [tasks]} for the next 7 days — deadline view."""
        plan = {}
        for i in range(7):
            day = date.today() + timedelta(days=i)
            plan[day] = []

        days_list = list(plan.keys())
        last_day  = days_list[-1]

        pending = []
        for t in self.tasks:
            if not t.completed:
                pending.append(t)

        for i in range(1, len(pending)):
            current = pending[i]
            j = i - 1
            while j >= 0 and pending[j].urgency_score() < current.urgency_score():
                pending[j + 1] = pending[j]
                j = j - 1
            pending[j + 1] = current

        for task in pending:
            if task.deadline in plan:
                plan[task.deadline].append(task)
            elif task.days_until_due() > 0:
                plan[last_day].append(task)
        return plan

    def holiday_collisions(self, holidays):
        """Returns {task: holiday_name} for tasks whose deadline falls on a holiday."""
        holiday_map = {}
        for h in holidays:
            holiday_map[h["date"]] = h["name"]
        collisions = {}
        for task in self.tasks:
            if not task.completed:
                key = task.deadline.isoformat()
                if key in holiday_map:
                    collisions[task] = holiday_map[key]
        return collisions


# ─────────────────────────────────────────────────────────────────────────────
# API FUNCTIONS  (Module 5 – APIs)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_weather(lat=38.72, lon=-9.14):
    """Fetches current weather from open-meteo.com. Returns None if request fails."""
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,weather_code,wind_speed_10m"
            "&timezone=auto"
        )
        response = requests.get(url, timeout=5)
        data = response.json()

        code = data["current"]["weather_code"]
        temp = round(data["current"]["temperature_2m"])
        wind = round(data["current"]["wind_speed_10m"])

        if code == 0:
            condition = "Clear sky"
            emoji     = "☀️"
            tip       = "Perfect weather. Consider heading outside or to the library to study."
            card_bg   = "#fffbeb"
            card_border = "#fcd34d"
            tip_color = "#92400e"
        elif code <= 3:
            condition = "Partly cloudy"
            emoji     = "⛅"
            tip       = "Nice day. A good time to study outside or find a quiet cafe."
            card_bg   = "#f0f9ff"
            card_border = "#7dd3fc"
            tip_color = "#0c4a6e"
        elif code <= 48:
            condition = "Foggy"
            emoji     = "🌫️"
            tip       = "Grey and foggy. Perfect conditions for deep focus indoors."
            card_bg   = "#f9fafb"
            card_border = "#d1d5db"
            tip_color = "#374151"
        elif code <= 67:
            condition = "Rainy"
            emoji     = "🌧️"
            tip       = "Raining outside. Stay in, make coffee, and clear your task list."
            card_bg   = "#eff6ff"
            card_border = "#93c5fd"
            tip_color = "#1e3a5f"
        elif code <= 77:
            condition = "Snowy"
            emoji     = "❄️"
            tip       = "Snowing. Best day to stay in and get ahead on your assignments."
            card_bg   = "#f0f9ff"
            card_border = "#bae6fd"
            tip_color = "#0c4a6e"
        else:
            condition = "Stormy"
            emoji     = "⛈️"
            tip       = "Storm outside. Ideal day to power through your most urgent tasks."
            card_bg   = "#faf5ff"
            card_border = "#c4b5fd"
            tip_color = "#3b0764"

        return {
            "temp": temp, "wind": wind, "condition": condition,
            "emoji": emoji, "tip": tip,
            "card_bg": card_bg, "card_border": card_border, "tip_color": tip_color,
        }
    except Exception:
        return None


def fetch_holidays(country_code="PT"):
    """
    Fetches public holidays from date.nager.at (no API key required).
    Returns [] if the request fails.
    """
    try:
        year = date.today().year
        url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country_code}"
        response = requests.get(url, timeout=5)
        data = response.json()
        today_str = date.today().isoformat()
        upcoming = []
        for h in data:
            if h["date"] >= today_str:
                upcoming.append({"date": h["date"], "name": h["localName"]})
        return upcoming
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# DATA PERSISTENCE  (save/load to a local JSON file)
# ─────────────────────────────────────────────────────────────────────────────

DATA_FILE = "planner_data.json"


def save_data():
    """Saves all subjects and tasks to a local JSON file."""
    subjects_data = []
    for s in st.session_state.subjects:
        subjects_data.append({
            "name": s.name,
            "color": s.color,
        })

    tasks_data = []
    for t in st.session_state.tasks:
        tasks_data.append({
            "title": t.title,
            "subject_name": t.subject_name,
            "deadline": t.deadline.isoformat(),
            "priority": t.priority,
            "task_type": t.task_type,
            "estimated_hours": t.estimated_hours,
            "notes": t.notes,
            "completed": t.completed,
            "pomodoro_sessions": t.pomodoro_sessions,
        })

    data = {"subjects": subjects_data, "tasks": tasks_data}

    file = open(DATA_FILE, "w")
    json.dump(data, file)
    file.close()


def load_data():
    """
    Loads subjects and tasks from the local JSON file.
    Returns (subjects, tasks).
    Returns empty defaults if no file exists.
    """
    try:
        file = open(DATA_FILE, "r")
        data = json.load(file)
        file.close()
    except Exception:
        return [], []

    subjects = []
    for s in data.get("subjects", []):
        subjects.append(Subject(s["name"], s["color"]))

    tasks = []
    for t in data.get("tasks", []):
        task = Task(
            t["title"],
            t["subject_name"],
            date.fromisoformat(t["deadline"]),
            t["priority"],
            t["task_type"],
            t.get("estimated_hours", 1),
            t.get("notes", ""),
        )
        task.completed = t["completed"]
        task.pomodoro_sessions = t.get("pomodoro_sessions", 0)
        tasks.append(task)

    return subjects, tasks


# ─────────────────────────────────────────────────────────────────────────────
# CALENDAR IMPORT  (.ics file parser)
# ─────────────────────────────────────────────────────────────────────────────

SUBJECT_COLORS = [
    "#378ADD", "#1D9E75", "#D4537E", "#BA7517",
    "#7F77DD", "#D85A30", "#639922", "#2D9CDB",
]


def parse_ics(content):
    """
    Parses a .ics file content string and returns a list of dicts with:
    title, subject_name, deadline, task_type
    Extracts course name from SUMMARY field, strips code like (TXA).
    """
    import re
    events = []
    current = {}
    lines = content.splitlines()

    # join folded lines (lines starting with space are continuations)
    unfolded = []
    for line in lines:
        if line.startswith(" ") or line.startswith("\t"):
            if unfolded:
                unfolded[-1] = unfolded[-1] + line.strip()
        else:
            unfolded.append(line)

    for line in unfolded:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if "SUMMARY" in current and "DTSTART" in current:
                events.append(current)
            current = {}
        elif line.startswith("SUMMARY:"):
            current["SUMMARY"] = line[8:].strip()
        elif line.startswith("DTSTART:"):
            current["DTSTART"] = line[8:].strip()

    results = []
    for event in events:
        summary = event["SUMMARY"]
        dtstart = event["DTSTART"]

        # parse date from DTSTART (handles YYYYMMDD and YYYYMMDDTHHmmss)
        try:
            if "T" in dtstart:
                event_date = datetime.strptime(dtstart[:8], "%Y%m%d").date()
            else:
                event_date = datetime.strptime(dtstart[:8], "%Y%m%d").date()
        except Exception:
            continue

        # extract clean course name from summary
        # e.g. "Banking (TXA) - Regular Exam Period_MSc" -> "Banking"
        # remove " - Regular Exam Period_MSc" and similar suffixes
        name = summary
        if " - " in name:
            name = name.split(" - ")[0].strip()

        # remove trailing code like (TXA), (TXG), (TXC) etc.
        name = re.sub(r"\s*\([A-Z0-9]+\)\s*$", "", name).strip()

        # determine task type from summary
        task_type = "Exam"
        if "assignment" in summary.lower():
            task_type = "Assignment"
        elif "lecture" in summary.lower() or "class" in summary.lower():
            task_type = "Study session"

        results.append({
            "title": name + " exam",
            "subject_name": name,
            "deadline": event_date,
            "task_type": task_type,
        })

    return results


def import_from_ics(content, existing_subjects):
    """
    Takes parsed .ics content and returns new subjects and tasks to add.
    Skips tasks that already exist (same title + deadline).
    Auto-assigns colors to new subjects.
    """
    parsed = parse_ics(content)

    existing_subject_names = []
    for s in existing_subjects:
        existing_subject_names.append(s.name)

    new_subjects = []
    new_tasks = []
    color_index = len(existing_subjects) % len(SUBJECT_COLORS)

    for item in parsed:
        subject_name = item["subject_name"]

        # create subject if it doesn't exist yet
        already_exists = False
        for s in existing_subjects:
            if s.name == subject_name:
                already_exists = True
                break
        for s in new_subjects:
            if s.name == subject_name:
                already_exists = True
                break

        if not already_exists:
            color = SUBJECT_COLORS[color_index % len(SUBJECT_COLORS)]
            new_subjects.append(Subject(subject_name, color))
            color_index = color_index + 1

        # create task, skip duplicates
        duplicate = False
        for t in st.session_state.tasks:
            if t.title == item["title"] and t.deadline == item["deadline"]:
                duplicate = True
                break

        if not duplicate:
            task = Task(
                item["title"],
                subject_name,
                item["deadline"],
                "High",
                item["task_type"],
                3,
                "",
            )
            new_tasks.append(task)

    return new_subjects, new_tasks


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────

def init_state():
    if "subjects" not in st.session_state or "tasks" not in st.session_state:
        saved_subjects, saved_tasks = load_data()
        st.session_state.subjects = saved_subjects
        st.session_state.tasks    = saved_tasks

    if "weather" not in st.session_state:
        st.session_state.weather = fetch_weather()

    if "holidays" not in st.session_state:
        st.session_state.holidays = fetch_holidays()

    if "api_fetched_at" not in st.session_state:
        st.session_state.api_fetched_at = datetime.now().strftime("%H:%M")

    if "confirm_delete_task" not in st.session_state:
        st.session_state.confirm_delete_task = None

    if "confirm_delete_subject" not in st.session_state:
        st.session_state.confirm_delete_subject = None

    if "editing_task" not in st.session_state:
        st.session_state.editing_task = None

    if "pomodoro_task_id" not in st.session_state:
        st.session_state.pomodoro_task_id = None

    if "pomodoro_start" not in st.session_state:
        st.session_state.pomodoro_start = None

    if "pomodoro_paused_remaining" not in st.session_state:
        st.session_state.pomodoro_paused_remaining = None


# ─────────────────────────────────────────────────────────────────────────────
# STYLING
# ─────────────────────────────────────────────────────────────────────────────

def apply_styles():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

        html, body, [class*="css"], * {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
            -webkit-font-smoothing: antialiased;
        }
        [data-testid="stAppViewContainer"] { background: #ffffff; }
        [data-testid="stMainBlockContainer"] { padding: 3rem 3rem; max-width: 860px; }

        p, span, div, label, li, td, th { color: #1a1a1a; }
        h1 { font-size: 28px !important; font-weight: 600 !important; letter-spacing: -0.5px; color: #1a1a1a !important; }
        h2 { font-size: 22px !important; font-weight: 600 !important; letter-spacing: -0.3px; color: #1a1a1a !important; margin-bottom: 1.5rem !important; }
        h3 { font-size: 16px !important; font-weight: 500 !important; color: #1a1a1a !important; }

        [data-testid="stSidebar"] { background: #f9f9f8; border-right: 1px solid #ebebea; }
        [data-testid="stSidebar"] > div { padding: 1.5rem 1rem; }
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] div { color: #37352f !important; font-size: 14px; }
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2 { color: #1a1a1a !important; font-size: 15px !important; font-weight: 600 !important; }
        [data-testid="stSidebar"] [data-testid="stRadio"] label {
            font-size: 14px !important;
            color: #37352f !important;
            padding: 5px 10px !important;
            border-radius: 6px !important;
            display: block;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background: #ebebea !important; }

        [data-testid="stMetric"] {
            background: #f9f9f8;
            border-radius: 10px;
            padding: 20px 22px;
            border: 1px solid #ebebea;
        }
        [data-testid="stMetricLabel"] p {
            font-size: 11px !important;
            font-weight: 500 !important;
            color: #9b9a97 !important;
            text-transform: uppercase;
            letter-spacing: 0.07em;
        }
        [data-testid="stMetricValue"] {
            font-size: 32px !important;
            font-weight: 600 !important;
            color: #1a1a1a !important;
            letter-spacing: -1px;
        }

        .task-card {
            background: #ffffff;
            border-radius: 8px;
            padding: 13px 16px;
            margin-bottom: 5px;
            border: 1px solid #ebebea;
            border-left: 3px solid #1a1a1a;
        }
        .task-card:hover { background: #fafafa; }
        .task-title { font-weight: 500; font-size: 14px; color: #1a1a1a; line-height: 1.4; }
        .task-meta  { font-size: 12px; color: #9b9a97; margin-top: 5px; }

        .badge {
            display: inline-block;
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
            margin-right: 6px;
        }
        .badge-High   { background: #fef0ee; color: #c4320a; }
        .badge-Medium { background: #fef8ee; color: #a56123; }
        .badge-Low    { background: #f0faf0; color: #2d7a3a; }

        .section-label {
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            color: #9b9a97;
            margin: 28px 0 12px;
        }

        [data-testid="stExpander"] {
            background: #ffffff !important;
            border-radius: 8px !important;
            border: 1px solid #ebebea !important;
            margin-bottom: 5px;
        }
        [data-testid="stExpander"] summary {
            font-size: 14px !important;
            font-weight: 500 !important;
            color: #1a1a1a !important;
            padding: 12px 16px !important;
        }
        [data-testid="stExpander"] summary:hover { background: #f9f9f8 !important; border-radius: 8px; }

        /* ── all text inputs, date, number ── */
        [data-testid="stTextInput"] input,
        [data-testid="stDateInput"] input,
        [data-testid="stNumberInput"] input {
            background: #ffffff !important;
            border: 1px solid #ebebea !important;
            border-radius: 7px !important;
            color: #1a1a1a !important;
            font-size: 14px !important;
            padding: 9px 12px !important;
        }
        [data-testid="stTextInput"] input:focus,
        [data-testid="stDateInput"] input:focus,
        [data-testid="stNumberInput"] input:focus {
            border-color: #9b9a97 !important;
        }

        /* ── selectbox ── */
        [data-testid="stSelectbox"] > div > div {
            background: #ffffff !important;
            border: 1px solid #ebebea !important;
            border-radius: 7px !important;
            color: #1a1a1a !important;
            font-size: 14px !important;
        }
        [data-testid="stSelectbox"] span,
        [data-testid="stSelectbox"] p,
        [data-testid="stSelectbox"] div { color: #1a1a1a !important; }
        ul[data-testid="stSelectboxVirtualDropdown"],
        ul[data-testid="stSelectboxVirtualDropdown"] li { background: #ffffff !important; }
        ul[data-testid="stSelectboxVirtualDropdown"] span { color: #1a1a1a !important; }

        /* ── date picker popup — force light theme ── */
        [data-testid="stDateInput"] div,
        [data-testid="stDateInput"] span,
        [data-testid="stDateInput"] p { color: #1a1a1a !important; }
        [data-testid="stDateInput"] button { color: #1a1a1a !important; background: transparent !important; }
        /* the calendar popup itself */
        div[class*="datepicker"],
        div[class*="DatePicker"],
        div[class*="calendar"] {
            background: #ffffff !important;
            color: #1a1a1a !important;
        }
        /* override dark calendar popup that Streamlit renders */
        [data-baseweb="calendar"] {
            background: #ffffff !important;
        }
        [data-baseweb="calendar"] * {
            color: #1a1a1a !important;
            background-color: #ffffff !important;
        }
        [data-baseweb="calendar"] [aria-selected="true"] > div,
        [data-baseweb="calendar"] [aria-selected="true"] {
            background-color: #1a1a1a !important;
            color: #ffffff !important;
        }
        [data-baseweb="calendar"] button:hover > div {
            background-color: #f0f0f0 !important;
        }

        /* ── number input stepper buttons ── */
        [data-testid="stNumberInput"] button {
            background: #f9f9f8 !important;
            color: #1a1a1a !important;
            border-color: #ebebea !important;
        }
        [data-testid="stNumberInput"] div { color: #1a1a1a !important; }

        /* ── form labels ── */
        [data-testid="stForm"] label p,
        [data-testid="stForm"] label span,
        label p, label span { color: #1a1a1a !important; }

        /* ── color picker ── */
        [data-testid="stColorPicker"] label p { color: #1a1a1a !important; }

        /* ── all regular buttons: white bg, dark text ── */
        [data-testid="stButton"] button {
            background: #ffffff !important;
            border: 1px solid #ebebea !important;
            border-radius: 7px !important;
            color: #1a1a1a !important;
            font-size: 12px !important;
            font-weight: 500 !important;
            padding: 6px 10px !important;
            white-space: nowrap !important;
            overflow: hidden !important;
        }
        [data-testid="stButton"] button:hover {
            background: #f9f9f8 !important;
            border-color: #c7c6c3 !important;
        }
        [data-testid="stButton"] button[kind="primary"],
        [data-testid="stButton"] button[kind="primary"] p,
        [data-testid="stButton"] button[kind="primary"] span,
        [data-testid="stButton"] button[kind="primary"] div {
            background: #1a1a1a !important;
            color: #ffffff !important;
            border-color: #1a1a1a !important;
        }
        [data-testid="stButton"] button[kind="primary"]:hover { background: #2d2d2d !important; }

        /* ── form submit buttons: always white text on dark bg ── */
        [data-testid="stFormSubmitButton"] button,
        [data-testid="stFormSubmitButton"] button p,
        [data-testid="stFormSubmitButton"] button span,
        [data-testid="stFormSubmitButton"] > button {
            background: #1a1a1a !important;
            color: #ffffff !important;
            border-color: #1a1a1a !important;
            border-radius: 7px !important;
            font-size: 13px !important;
            font-weight: 500 !important;
        }
        [data-testid="stFormSubmitButton"] button:hover,
        [data-testid="stFormSubmitButton"] > button:hover {
            background: #2d2d2d !important;
            color: #ffffff !important;
        }

        /* ── progress bar ── */
        [data-testid="stProgress"] > div {
            background: #ebebea !important;
            border-radius: 99px !important;
            height: 5px !important;
        }
        [data-testid="stProgress"] > div > div {
            background: #1a1a1a !important;
            border-radius: 99px !important;
            height: 5px !important;
        }
        [data-testid="stProgress"] p { display: none !important; }

        /* ── hide only the radio circle dot, keep the label text ── */
        [data-testid="stRadio"] input[type="radio"] { display: none !important; }
        div[role="radiogroup"] > label > div:first-child { display: none !important; }

        /* ── hide streamlit collapse button top left ── */
        [data-testid="stSidebarCollapseButton"] { display: none !important; }
        [data-testid="collapsedControl"] { display: none !important; }

        [data-testid="stAlert"] {
            border-radius: 8px !important;
            border: 1px solid #ebebea !important;
            font-size: 13px !important;
        }
        [data-testid="stAlert"] p { color: inherit !important; }

        [data-testid="stCaptionContainer"] p {
            color: #9b9a97 !important;
            font-size: 12px !important;
        }

        hr { border: none !important; border-top: 1px solid #ebebea !important; margin: 1.5rem 0 !important; }

        /* ── file uploader ── */
        [data-testid="stFileUploader"] {
            background: #ffffff !important;
        }
        [data-testid="stFileUploader"] section {
            background: #ffffff !important;
            border: 1.5px dashed #ebebea !important;
            border-radius: 10px !important;
            padding: 28px 24px !important;
            min-height: 100px !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            text-align: center !important;
        }
        [data-testid="stFileUploader"] section:hover {
            border-color: #9b9a97 !important;
            background: #f9f9f8 !important;
        }
        [data-testid="stFileUploader"] p,
        [data-testid="stFileUploader"] span,
        [data-testid="stFileUploader"] small { color: #1a1a1a !important; }
        [data-testid="stFileUploader"] label {
            color: #1a1a1a !important;
            font-weight: 500 !important;
        }
        /* Upload button inside file uploader — keep it visible and separate */
        [data-testid="stFileUploader"] button {
            background: #ffffff !important;
            color: #1a1a1a !important;
            border: 1px solid #c7c6c3 !important;
            border-radius: 7px !important;
            margin-bottom: 8px !important;
            display: block !important;
        }
        /* hide the duplicate instructional text that overlaps */
        [data-testid="stFileUploaderDropzoneInstructions"] > div > span:last-child {
            display: none !important;
        }

        /* catch-all: any button that still has dark background needs white text */
        button[style*="background-color: rgb(49, 51, 63)"],
        button[style*="background: rgb(49, 51, 63)"] {
            color: #ffffff !important;
        }

        #MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
        [data-testid="stDecoration"] { display: none; }
    </style>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────────────────────────────────────

TYPE_ICONS = {"Assignment": "📄", "Exam": "📝", "Study session": "📖"}
DAY_NAMES  = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def task_card_html(task, color):
    strike = "text-decoration:line-through;opacity:0.55;" if task.completed else ""
    badge  = f'<span class="badge badge-{task.priority}">{task.priority}</span>'
    icon   = TYPE_ICONS[task.task_type]
    label  = task.deadline_label()
    overdue_style = "color:#dc2626;" if task.is_overdue() else ""
    hours  = f'<span style="color:#9b9a97;font-size:11px;margin-left:8px">{task.estimated_hours}h estimated</span>'
    pomodoro = ""
    if task.pomodoro_sessions > 0:
        pomodoro = (
            f'<span style="color:#9b9a97;font-size:11px;margin-left:8px">'
            f'🍅 {task.pomodoro_sessions} session{"s" if task.pomodoro_sessions != 1 else ""}</span>'
        )
    notes_html = ""
    if task.notes:
        notes_html = (
            f"<div style='margin-top:7px;padding:8px 10px;background:#f9f9f8;"
            f"border-radius:5px;font-size:12px;color:#787774;line-height:1.5'>"
            f"{task.notes}</div>"
        )
    return (
        f'<div class="task-card" style="border-left-color:{color};">'
        f'  <div class="task-title" style="{strike}">{icon} {task.title}</div>'
        f'  <div class="task-meta">{badge}'
        f'    <span style="{overdue_style}">{label}</span>'
        f'    &nbsp;·&nbsp; {task.subject_name}'
        f'    {hours}{pomodoro}'
        f'  </div>'
        f'  {notes_html}'
        f'</div>'
    )


def empty_state(heading, hint=""):
    st.markdown(
        f'<div style="text-align:center;padding:52px 24px;">'
        f'  <div style="font-size:17px;font-weight:600;color:#787774;">{heading}</div>'
        f'  <div style="font-size:13px;color:#9ca3af;margin-top:6px;">{hint}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def motivational_message(pct):
    if pct == 100: return "Everything is done. Great work!"
    if pct >= 75:  return "Almost there, keep going!"
    if pct >= 50:  return "Good progress. Over halfway!"
    if pct >= 25:  return "You have started. Keep building momentum."
    return "Lots to do. Start with the highest priority task."


def section_label(text):
    st.markdown(f'<div class="section-label">{text}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

def page_dashboard(planner):
    st.markdown("## Dashboard")

    # ── onboarding: show welcome if no subjects yet ───────────────────────────
    if not st.session_state.subjects:
        st.markdown(
            """
            <div style="border:1px solid #e8e8e4;border-radius:8px;padding:32px 36px;margin:24px 0;background:#fafafa;">
                <div style="font-size:18px;font-weight:600;color:#1a1a1a;margin-bottom:8px;">Welcome to Student Planner</div>
                <div style="font-size:14px;color:#787774;line-height:1.7;">
                    Get started in two steps:<br><br>
                    <b>1.</b> Go to <b>Subjects</b> in the sidebar and add your courses.<br>
                    <b>2.</b> Go to <b>Tasks</b> and add your assignments, exams, and study sessions.<br><br>
                    The planner will then track your deadlines, rank tasks by urgency, and build your weekly plan automatically.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

    stats = planner.get_stats()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total tasks",    stats["total"])
    c2.metric("Completed",      stats["completed"])
    c3.metric("Due this week",  stats["due_this_week"])
    c4.metric("Overdue",        stats["overdue"],
              delta=f"-{stats['overdue']}" if stats["overdue"] > 0 else None,
              delta_color="inverse")

    section_label("Overall progress")
    pct = stats["completion_pct"]
    st.progress(pct / 100)
    st.caption(f"{pct}% complete. {motivational_message(pct)}")

    st.divider()

    col_w, col_h = st.columns(2)

    with col_w:
        weather = st.session_state.weather
        if weather:
            weather_content = (
                f"<div style='font-size:28px;margin-bottom:8px'>{weather['emoji']}</div>"
                f"<div style='font-size:22px;font-weight:600;color:{weather['tip_color']};letter-spacing:-0.5px'>"
                f"{weather['tip']}</div>"
                f"<div style='font-size:13px;color:{weather['tip_color']};opacity:0.75;margin-top:6px'>"
                f"{weather['temp']}°C · {weather['condition']} · wind {weather['wind']} km/h</div>"
            )
            card_bg     = weather['card_bg']
            card_border = weather['card_border']
        else:
            weather_content = "<div style='font-size:13px;color:#9b9a97'>Weather data unavailable.</div>"
            card_bg     = "#ffffff"
            card_border = "#ebebea"

        st.markdown(
            f"<div style='border:1px solid {card_border};background:{card_bg};"
            f"border-radius:10px;padding:18px 20px;'>"
            f"<div style='font-size:11px;font-weight:600;letter-spacing:0.07em;"
            f"text-transform:uppercase;color:#9b9a97;margin-bottom:10px'>☁️ Today's weather</div>"
            f"{weather_content}"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_h:
        holidays = st.session_state.holidays
        if holidays:
            rows = ""
            for h in holidays[:5]:
                d = date.fromisoformat(h["date"])
                rows += (
                    f"<div style='font-size:13px;margin-bottom:7px;color:#1a1a1a;'>"
                    f"<span style='font-weight:500'>{h['name']}</span>"
                    f"<span style='color:#9b9a97;margin-left:8px;font-size:12px'>{d.strftime('%d %b %Y')}</span>"
                    f"</div>"
                )
        else:
            rows = "<div style='font-size:13px;color:#9b9a97'>No holiday data available.</div>"

        st.markdown(
            f"<div style='border:1px solid #ebebea;border-radius:10px;padding:18px 20px;'>"
            f"<div style='font-size:11px;font-weight:600;letter-spacing:0.07em;"
            f"text-transform:uppercase;color:#9b9a97;margin-bottom:10px'>🗓️ Upcoming holidays (Portugal)</div>"
            f"{rows}"
            f"</div>",
            unsafe_allow_html=True,
        )



    # ── holiday collision warnings ─────────────────────────────────────────
    collisions = planner.holiday_collisions(st.session_state.holidays)
    if collisions:
        st.divider()
        section_label("Holiday deadline conflicts")
        for task, holiday_name in collisions.items():
            st.warning(
                f"**{task.title}** is due on **{task.deadline.strftime('%d %b')}** "
                f"which is a public holiday (*{holiday_name}*). "
                f"Consider submitting earlier."
            )

    st.divider()
    section_label("Most urgent")

    pending = []
    for t in planner.tasks:
        if not t.completed:
            pending.append(t)
    # sort by urgency score, highest first
    for i in range(1, len(pending)):
        current = pending[i]
        j = i - 1
        while j >= 0 and pending[j].urgency_score() < current.urgency_score():
            pending[j + 1] = pending[j]
            j = j - 1
        pending[j + 1] = current

    if not pending:
        empty_state("All caught up!", "No pending tasks.")
    else:
        for task in pending[:5]:
            subj = planner.get_subject(task.subject_name)
            st.markdown(task_card_html(task, subj.color if subj else "#888"),
                        unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: TASKS
# ─────────────────────────────────────────────────────────────────────────────

def page_tasks(planner):
    st.markdown("## Tasks")

    subject_names = planner.subject_names()

    if "task_rows" not in st.session_state:
        st.session_state.task_rows = []

    if "add_mode" not in st.session_state:
        st.session_state.add_mode = None

    # ── two toggle buttons ────────────────────────────────────────────────────
    btn_a, btn_b = st.columns([1, 2])

    if btn_a.button("New task", use_container_width=True):
        if st.session_state.add_mode == "manual":
            st.session_state.add_mode = None
        else:
            st.session_state.add_mode = "manual"
            # seed one empty row if needed
            if not st.session_state.task_rows and subject_names:
                st.session_state.task_rows = [{
                    "title": "", "subject": subject_names[0],
                    "tasktype": Task.TYPES[0],
                    "deadline": date.today() + timedelta(days=7),
                    "priority": "Medium", "hours": 2, "notes": "",
                }]
        st.rerun()

    if btn_b.button("Import from calendar (.ics)", use_container_width=True):
        st.session_state.add_mode = None if st.session_state.add_mode == "calendar" else "calendar"
        st.rerun()

    # ── guard shown after buttons so buttons are always visible ──────────────
    if not subject_names and st.session_state.add_mode == "manual":
        st.warning("You need to add at least one subject before creating tasks. "
                   "Go to Subjects first.")

    # ── manual add form ───────────────────────────────────────────────────────
    if st.session_state.add_mode == "manual" and subject_names:
        st.markdown(
            "<div style='background:#f9f9f8;border:1px solid #ebebea;"
            "border-radius:10px;padding:20px 24px;margin:8px 0 16px;'>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div style='font-size:13px;font-weight:500;color:#1a1a1a;margin-bottom:14px'>"
            "Add tasks</div>",
            unsafe_allow_html=True,
        )

        rows_to_delete = []
        for idx, row in enumerate(st.session_state.task_rows):
            st.markdown(
                "<div style='border:1px solid #ebebea;border-radius:8px;"
                "padding:14px 16px;margin-bottom:10px;background:#ffffff'>",
                unsafe_allow_html=True,
            )
            col_title, col_del = st.columns([8, 1])
            row["title"] = col_title.text_input(
                "Task title", value=row["title"],
                placeholder="e.g. Assignment 4",
                key=f"title_{idx}", label_visibility="collapsed",
            )
            if col_del.button("x", key=f"delrow_{idx}", help="Remove"):
                rows_to_delete.append(idx)

            c1, c2, c3, c4 = st.columns(4)
            c1.caption("Subject")
            c2.caption("Type")
            c3.caption("Priority")
            c4.caption("Deadline")
            subj_idx = subject_names.index(row["subject"]) if row["subject"] in subject_names else 0
            row["subject"]  = c1.selectbox("Subject",  subject_names,   index=subj_idx,                              key=f"subj_{idx}", label_visibility="collapsed")
            row["tasktype"] = c2.selectbox("Type",     Task.TYPES,      index=Task.TYPES.index(row["tasktype"]),      key=f"type_{idx}", label_visibility="collapsed")
            row["priority"] = c3.selectbox("Priority", Task.PRIORITIES, index=Task.PRIORITIES.index(row["priority"]), key=f"prio_{idx}", label_visibility="collapsed")
            row["deadline"] = c4.date_input("Deadline", value=row["deadline"], min_value=date.today(), key=f"dead_{idx}", label_visibility="collapsed")

            h_col, n_col = st.columns([1, 3])
            h_col.caption("Estimated hours")
            n_col.caption("Notes (optional)")
            row["hours"] = h_col.number_input("Hours", min_value=1, max_value=100, value=row["hours"], step=1, key=f"hrs_{idx}", label_visibility="collapsed")
            row["notes"] = n_col.text_input("Notes", value=row["notes"], placeholder="e.g. check lecture slides first", key=f"notes_{idx}", label_visibility="collapsed")
            st.markdown("</div>", unsafe_allow_html=True)

        for idx in sorted(rows_to_delete, reverse=True):
            st.session_state.task_rows.pop(idx)
        if rows_to_delete:
            st.rerun()

        add_col, save_col, cancel_col = st.columns([1, 1, 1])
        if add_col.button("+ Add another row", use_container_width=True):
            last = st.session_state.task_rows[-1] if st.session_state.task_rows else {}
            st.session_state.task_rows.append({
                "title": "",
                "subject":  last.get("subject",  subject_names[0]),
                "tasktype": last.get("tasktype", Task.TYPES[0]),
                "deadline": last.get("deadline", date.today() + timedelta(days=7)),
                "priority": last.get("priority", "Medium"),
                "hours":    last.get("hours",    2),
                "notes":    "",
            })
            st.rerun()

        if save_col.button("Save all tasks", type="primary", use_container_width=True):
            errors = []
            for idx, row in enumerate(st.session_state.task_rows):
                if not row["title"].strip():
                    errors.append(f"Row {idx + 1} is missing a title.")
                    continue
                st.session_state.tasks.append(
                    Task(row["title"].strip(), row["subject"], row["deadline"],
                         row["priority"], row["tasktype"], row["hours"], row["notes"].strip())
                )
            if errors:
                for e in errors:
                    st.error(e)
            else:
                save_data()
                st.session_state.task_rows = []
                st.session_state.add_mode  = None
                st.rerun()

        if cancel_col.button("Cancel", use_container_width=True):
            st.session_state.task_rows = []
            st.session_state.add_mode  = None
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    # ── calendar import ───────────────────────────────────────────────────────
    if st.session_state.add_mode == "calendar":
        st.markdown(
            "<div style='background:#f9f9f8;border:1px solid #ebebea;"
            "border-radius:10px;padding:20px 24px;margin:8px 0 16px;'>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div style='font-size:13px;font-weight:500;color:#1a1a1a;margin-bottom:4px'>"
            "Import from calendar</div>"
            "<div style='font-size:13px;color:#787774;margin-bottom:14px'>"
            "Upload a .ics file from Nova SBE, Google Calendar, Apple Calendar, or Outlook. "
            "Subjects and tasks are created automatically."
            "</div>",
            unsafe_allow_html=True,
        )
        uploaded_file = st.file_uploader(
            "ics", type=["ics"], label_visibility="collapsed",
        )
        if uploaded_file is not None:
            content = uploaded_file.read().decode("utf-8")
            new_subjects, new_tasks = import_from_ics(content, st.session_state.subjects)
            if not new_subjects and not new_tasks:
                st.info("Nothing new to import. All events already exist.")
            else:
                st.markdown(
                    f"<div style='font-size:13px;color:#1a1a1a;margin-bottom:10px'>"
                    f"Found <b>{len(new_subjects)}</b> new subject{'s' if len(new_subjects) != 1 else ''} "
                    f"and <b>{len(new_tasks)}</b> new task{'s' if len(new_tasks) != 1 else ''}.</div>",
                    unsafe_allow_html=True,
                )
                for s in new_subjects:
                    st.markdown(
                        f"<div style='font-size:12px;color:#9b9a97;margin-bottom:3px'>"
                        f"New subject: <span style='color:#1a1a1a;font-weight:500'>{s.name}</span></div>",
                        unsafe_allow_html=True,
                    )
                for t in new_tasks[:8]:
                    st.markdown(
                        f"<div style='font-size:12px;color:#9b9a97;margin-bottom:3px'>"
                        f"New task: <span style='color:#1a1a1a;font-weight:500'>{t.title}</span> "
                        f"<span style='color:#9b9a97'>due {t.deadline.strftime('%d %b %Y')}</span></div>",
                        unsafe_allow_html=True,
                    )
                if len(new_tasks) > 8:
                    st.caption(f"...and {len(new_tasks) - 8} more tasks.")
                if st.button("Confirm import", type="primary"):
                    for s in new_subjects:
                        st.session_state.subjects.append(s)
                    for t in new_tasks:
                        st.session_state.tasks.append(t)
                    save_data()
                    st.session_state.add_mode = None
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    editing = st.session_state.editing_task
    if editing is not None:
        st.markdown("---")
        st.markdown("**Edit task**")
        with st.form("edit_task_form"):
            new_title = st.text_input("Title", value=editing.title)
            col1, col2 = st.columns(2)
            idx_subj = subject_names.index(editing.subject_name) if editing.subject_name in subject_names else 0
            new_subject  = col1.selectbox("Subject", subject_names, index=idx_subj)
            new_type     = col2.selectbox("Type", Task.TYPES, index=Task.TYPES.index(editing.task_type))
            col3, col4   = st.columns(2)
            new_deadline = col3.date_input("Deadline", value=editing.deadline)
            new_priority = col4.selectbox("Priority", Task.PRIORITIES,
                                          index=Task.PRIORITIES.index(editing.priority))
            new_hours = st.number_input("Estimated hours", min_value=1, max_value=100,
                                        value=editing.estimated_hours, step=1)
            new_notes = st.text_area("Notes", value=editing.notes, height=80)

            cs, cc = st.columns(2)
            if cs.form_submit_button("Save changes", use_container_width=True):
                if not new_title.strip():
                    st.error("Title cannot be empty.")
                else:
                    editing.title           = new_title.strip()
                    editing.subject_name    = new_subject
                    editing.task_type       = new_type
                    editing.deadline        = new_deadline
                    editing.priority        = new_priority
                    editing.estimated_hours = new_hours
                    editing.notes          = new_notes.strip()
                    save_data()
                    st.session_state.editing_task = None
                    st.success("Task updated.")
                    st.rerun()
            if cc.form_submit_button("Cancel", use_container_width=True):
                st.session_state.editing_task = None
                st.rerun()

    # ── delete confirmation ───────────────────────────────────────────────────
    to_delete = st.session_state.confirm_delete_task
    if to_delete is not None:
        st.warning(f"Delete **{to_delete.title}**? This cannot be undone.")
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("Yes, delete", type="primary"):
            st.session_state.tasks.remove(to_delete)
            save_data()
            st.session_state.confirm_delete_task = None
            st.rerun()
        if c2.button("Cancel"):
            st.session_state.confirm_delete_task = None
            st.rerun()

    st.divider()
    section_label("Search and filter")
    col_s, col_st, col_sub, col_ty = st.columns([2, 1, 1, 1])
    search         = col_s.text_input("Search", placeholder="Search tasks...",
                                      label_visibility="collapsed")
    filter_status  = col_st.selectbox("Status",  ["All", "Pending", "Completed", "Overdue"],
                                      label_visibility="collapsed")
    filter_subject = col_sub.selectbox("Subject", ["All subjects"] + subject_names,
                                       label_visibility="collapsed")
    filter_type    = col_ty.selectbox("Type",    ["All types"] + Task.TYPES,
                                      label_visibility="collapsed")

    def matches(t):
        if search and search.lower() not in t.title.lower():
            return False
        if filter_status == "Pending"   and t.completed:        return False
        if filter_status == "Completed" and not t.completed:    return False
        if filter_status == "Overdue"   and not t.is_overdue(): return False
        if filter_subject != "All subjects" and t.subject_name != filter_subject:
            return False
        if filter_type != "All types" and t.task_type != filter_type:
            return False
        return True

    # build the visible list using a regular for loop, then sort it.
    # completed tasks go to the bottom; within each group, higher urgency first.
    visible = []
    for t in st.session_state.tasks:
        if matches(t):
            visible.append(t)

    # sort: incomplete before complete, then by urgency score descending
    for i in range(1, len(visible)):
        current = visible[i]
        j = i - 1
        while j >= 0:
            a = visible[j]
            # a should come after current if: a is complete and current is not,
            # OR both have same completion and a has lower urgency
            if (a.completed and not current.completed) or \
               (a.completed == current.completed and
                    a.urgency_score() < current.urgency_score()):
                visible[j + 1] = visible[j]
                j = j - 1
            else:
                break
        visible[j + 1] = current

    # ── task list ─────────────────────────────────────────────────────────────
    if not st.session_state.tasks:
        empty_state("No tasks yet", "Use the form above to add your first task.")
    elif not visible:
        empty_state("No tasks match your filters",
                    "Try adjusting the search or filter options.")
    else:
        # ── pomodoro timer panel ──────────────────────────────────────────────
        pom_task_id = st.session_state.pomodoro_task_id
        pom_start   = st.session_state.pomodoro_start
        pom_paused  = st.session_state.pomodoro_paused_remaining
        POMODORO_MINS = 25

        if pom_task_id is not None:
            # find the active task
            active_task = None
            for t in st.session_state.tasks:
                if id(t) == pom_task_id:
                    active_task = t
                    break

            if active_task:
                if pom_paused is not None:
                    # paused state
                    remaining_secs = pom_paused
                else:
                    elapsed = (datetime.now() - pom_start).total_seconds()
                    remaining_secs = max(0, POMODORO_MINS * 60 - elapsed)

                mins_left = int(remaining_secs // 60)
                secs_left = int(remaining_secs % 60)
                is_done   = remaining_secs <= 0

                if is_done:
                    active_task.pomodoro_sessions = active_task.pomodoro_sessions + 1
                    save_data()
                    st.session_state.pomodoro_task_id = None
                    st.session_state.pomodoro_start   = None
                    st.session_state.pomodoro_paused_remaining = None
                    st.success(f"Session complete! Take a 5 minute break. Total sessions on this task: {active_task.pomodoro_sessions}")
                    st.rerun()
                else:
                    bar_pct = int(((POMODORO_MINS * 60 - remaining_secs) / (POMODORO_MINS * 60)) * 100)
                    paused_label = "Paused" if pom_paused is not None else "Focusing"
                    st.markdown(
                        f"<div style='border:1px solid #ebebea;border-radius:10px;"
                        f"padding:16px 20px;margin-bottom:16px;background:#fafafa'>"
                        f"<div style='font-size:11px;font-weight:600;letter-spacing:0.07em;"
                        f"text-transform:uppercase;color:#9b9a97;margin-bottom:6px'>"
                        f"🍅 {paused_label}</div>"
                        f"<div style='font-size:13px;font-weight:500;color:#1a1a1a;margin-bottom:10px'>"
                        f"{active_task.title}</div>"
                        f"<div style='font-size:36px;font-weight:600;color:#1a1a1a;letter-spacing:-1px;margin-bottom:10px'>"
                        f"{mins_left:02d}:{secs_left:02d}</div>"
                        f"<div style='background:#ebebea;border-radius:99px;height:4px;margin-bottom:12px'>"
                        f"<div style='width:{bar_pct}%;background:#1a1a1a;border-radius:99px;height:4px'></div>"
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )
                    pc1, pc2, pc3 = st.columns([1, 1, 1])
                    if pom_paused is not None:
                        if pc1.button("Resume", use_container_width=True):
                            st.session_state.pomodoro_start = datetime.now() - timedelta(seconds=POMODORO_MINS * 60 - pom_paused)
                            st.session_state.pomodoro_paused_remaining = None
                            st.rerun()
                    else:
                        if pc1.button("Pause", use_container_width=True):
                            st.session_state.pomodoro_paused_remaining = remaining_secs
                            st.rerun()
                    if pc2.button("Reset", use_container_width=True):
                        st.session_state.pomodoro_start = datetime.now()
                        st.session_state.pomodoro_paused_remaining = None
                        st.rerun()
                    if pc3.button("Stop session", use_container_width=True):
                        st.session_state.pomodoro_task_id = None
                        st.session_state.pomodoro_start   = None
                        st.session_state.pomodoro_paused_remaining = None
                        st.rerun()

        st.caption(f"Showing {len(visible)} task{'s' if len(visible) != 1 else ''}")
        for task in visible:
            subj  = planner.get_subject(task.subject_name)
            color = subj.color if subj else "#888"

            col_chk, col_card, col_focus, col_edit, col_del = st.columns([0.4, 5, 1.2, 1.2, 1.2])

            new_val = col_chk.checkbox("done", value=task.completed,
                                       key=f"chk_{id(task)}",
                                       label_visibility="collapsed")
            if new_val != task.completed:
                task.completed = new_val
                save_data()
                st.rerun()

            col_card.markdown(task_card_html(task, color), unsafe_allow_html=True)

            is_active = st.session_state.pomodoro_task_id == id(task)
            focus_label = "🍅 Active" if is_active else "🍅 Focus"
            if col_focus.button(focus_label, key=f"pom_{id(task)}", use_container_width=True):
                if is_active:
                    st.session_state.pomodoro_task_id = None
                    st.session_state.pomodoro_start   = None
                    st.session_state.pomodoro_paused_remaining = None
                else:
                    st.session_state.pomodoro_task_id = id(task)
                    st.session_state.pomodoro_start   = datetime.now()
                    st.session_state.pomodoro_paused_remaining = None
                st.rerun()

            if col_edit.button("Edit", key=f"edit_{id(task)}", use_container_width=True):
                st.session_state.editing_task = task
                st.rerun()

            if col_del.button("Delete", key=f"del_{id(task)}", use_container_width=True):
                st.session_state.confirm_delete_task = task
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: WEEKLY PLAN
# ─────────────────────────────────────────────────────────────────────────────

def page_weekly_plan(planner):
    st.markdown("## Weekly plan")

    if not st.session_state.tasks:
        empty_state("No tasks to plan", "Add some tasks first.")
        return

    # ── view toggle ───────────────────────────────────────────────────────────
    view_col, pref_col = st.columns([2, 2])
    view_mode = view_col.radio(
        "View",
        ["Study plan", "Deadline view"],
        horizontal=True,
        label_visibility="collapsed",
    )

    weather = st.session_state.weather
    if weather:
        st.caption(f"{weather['condition']}, {weather['temp']}C. {weather['tip']}")

    holiday_dates = {}
    for h in st.session_state.holidays:
        holiday_dates[h["date"]] = h["name"]

    # ── deadline view (original) ──────────────────────────────────────────────
    if view_mode == "Deadline view":
        st.caption("Tasks shown on their deadline day.")
        plan = planner.get_weekly_plan()
        days_list = list(plan.keys())
        last_day  = days_list[-1]

        for day, day_tasks in plan.items():
            is_today     = day == date.today()
            is_last      = day == last_day
            holiday_name = holiday_dates.get(day.isoformat())

            due_today_tasks = []
            reminder_tasks  = []
            if is_last:
                for t in day_tasks:
                    if t.deadline == day:
                        due_today_tasks.append(t)
                    else:
                        reminder_tasks.append(t)
                all_display = due_today_tasks
            else:
                all_display = day_tasks

            total_hours = 0
            for t in all_display:
                total_hours = total_hours + t.estimated_hours

            count_str = f"{len(all_display)} task{'s' if len(all_display) != 1 else ''}" if all_display else "free"
            hours_str = f"  {total_hours}h" if all_display else ""
            day_label = f"{DAY_NAMES[day.weekday()]} {day.strftime('%d %b')}"
            if is_today:
                day_label = "Today   " + day_label

            bg     = "#f9f9f8" if is_today else "#ffffff"
            border = "#1a1a1a" if is_today else "#ebebea"

            st.markdown(
                f"<div style='background:{bg};border:1px solid {border};"
                f"border-radius:8px;padding:14px 18px;margin-bottom:6px;'>"
                f"<div style='font-size:13px;font-weight:500;color:#1a1a1a;"
                f"margin-bottom:{'10px' if all_display or holiday_name or reminder_tasks else '0'}'>"
                f"{day_label}"
                f"<span style='font-size:12px;font-weight:400;color:#9b9a97;margin-left:10px'>"
                f"{count_str}{hours_str}</span></div>",
                unsafe_allow_html=True,
            )
            if holiday_name:
                st.markdown(
                    f"<div style='font-size:12px;color:#a56123;margin-bottom:8px'>Public holiday. Libraries may be closed.</div>",
                    unsafe_allow_html=True,
                )
            if not all_display and not reminder_tasks:
                st.markdown("<div style='font-size:12px;color:#9b9a97'>Nothing scheduled.</div>", unsafe_allow_html=True)
            else:
                for task in all_display:
                    subj  = planner.get_subject(task.subject_name)
                    st.markdown(task_card_html(task, subj.color if subj else "#888"), unsafe_allow_html=True)
                if reminder_tasks:
                    st.markdown("<div style='font-size:11px;color:#9b9a97;margin-top:10px;margin-bottom:4px'>Coming up after this week</div>", unsafe_allow_html=True)
                    for task in reminder_tasks:
                        subj = planner.get_subject(task.subject_name)
                        st.markdown(task_card_html(task, subj.color if subj else "#888"), unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    # ── smart study plan ──────────────────────────────────────────────────────
    else:
        session_hours = pref_col.slider(
            "Preferred session length (hours)",
            min_value=1, max_value=6, value=2, step=1,
        )

        st.caption(
            f"Work is spread across available days before each deadline, "
            f"in {session_hours}h sessions. Exam days from your calendar are treated as blocked."
        )

        # blocked dates = imported exam tasks
        blocked = {}
        for t in planner.tasks:
            if t.task_type == "Exam" and not t.completed:
                blocked[t.deadline.isoformat()] = t.title

        study_plan = planner.generate_study_plan(session_hours, blocked)

        has_anything = False
        for sessions in study_plan.values():
            if sessions:
                has_anything = True
                break

        if not has_anything:
            empty_state("Nothing to plan", "Add tasks with estimated hours to generate a study plan.")
            return

        for day, sessions in study_plan.items():
            is_today     = day == date.today()
            holiday_name = holiday_dates.get(day.isoformat())
            is_blocked   = day.isoformat() in blocked

            total_h = 0
            for s in sessions:
                total_h = total_h + s["hours"]

            if not sessions and not holiday_name and not is_today:
                continue  # skip empty days in study plan view

            day_label = f"{DAY_NAMES[day.weekday()]} {day.strftime('%d %b')}"
            if is_today:
                day_label = "Today   " + day_label

            if is_blocked:
                status_str = f"Exam day: {blocked[day.isoformat()]}"
                bg     = "#fffbf0"
                border = "#f0c060"
            elif sessions:
                status_str = f"{total_h}h of study"
                bg     = "#f9f9f8" if is_today else "#ffffff"
                border = "#1a1a1a" if is_today else "#ebebea"
            else:
                status_str = "free"
                bg     = "#f9f9f8" if is_today else "#ffffff"
                border = "#1a1a1a" if is_today else "#ebebea"

            if holiday_name:
                status_str = f"Holiday: {holiday_name}"
                bg     = "#fffbf0"
                border = "#f0c060"

            st.markdown(
                f"<div style='background:{bg};border:1px solid {border};"
                f"border-radius:8px;padding:14px 18px;margin-bottom:6px;'>"
                f"<div style='font-size:13px;font-weight:500;color:#1a1a1a;"
                f"margin-bottom:{'10px' if sessions else '0'}'>"
                f"{day_label}"
                f"<span style='font-size:12px;font-weight:400;color:#9b9a97;margin-left:10px'>"
                f"{status_str}</span></div>",
                unsafe_allow_html=True,
            )

            for session in sessions:
                task  = session["task"]
                hours = session["hours"]
                snum  = session["session"]
                subj  = planner.get_subject(task.subject_name)
                color = subj.color if subj else "#888"
                deadline_str = task.deadline.strftime("%d %b")
                days_left = task.days_until_due()
                urgency_color = "#dc2626" if days_left <= 2 else "#a56123" if days_left <= 5 else "#9b9a97"

                st.markdown(
                    f"<div style='background:#ffffff;border:1px solid #ebebea;"
                    f"border-left:3px solid {color};border-radius:6px;"
                    f"padding:10px 14px;margin-bottom:5px;'>"
                    f"<div style='font-size:14px;font-weight:500;color:#1a1a1a'>"
                    f"{task.title}</div>"
                    f"<div style='font-size:12px;color:#9b9a97;margin-top:4px;display:flex;gap:12px;flex-wrap:wrap'>"
                    f"<span>{hours}h session {snum}</span>"
                    f"<span>{task.subject_name}</span>"
                    f"<span style='color:{urgency_color}'>Due {deadline_str} ({days_left}d)</span>"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )

            st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: SUBJECTS
# ─────────────────────────────────────────────────────────────────────────────

def page_subjects(planner):
    st.markdown("## Subjects")

    if "show_add_subject" not in st.session_state:
        st.session_state.show_add_subject = False

    if st.button("New subject", use_container_width=False):
        st.session_state.show_add_subject = not st.session_state.show_add_subject
        st.rerun()

    if st.session_state.show_add_subject:
        st.markdown(
            "<div style='background:#f9f9f8;border:1px solid #ebebea;"
            "border-radius:10px;padding:20px 24px;margin:8px 0 16px;'>",
            unsafe_allow_html=True,
        )
        with st.form("add_subject_form", clear_on_submit=True):
            name  = st.text_input("Subject name", placeholder="e.g. Data Structures")
            color = st.color_picker("Display colour", value="#7F77DD")
            if st.form_submit_button("Add subject", use_container_width=True):
                if not name.strip():
                    st.error("Subject name is required.")
                elif planner.subject_exists(name.strip()):
                    st.error(f"A subject called {name.strip()} already exists.")
                else:
                    st.session_state.subjects.append(Subject(name.strip(), color))
                    save_data()
                    st.session_state.show_add_subject = False
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # ── delete confirmation ───────────────────────────────────────────────────
    to_delete = st.session_state.confirm_delete_subject
    if to_delete is not None:
        count = 0
        for t in st.session_state.tasks:
            if t.subject_name == to_delete.name:
                count = count + 1
        st.warning(
            f"Delete **{to_delete.name}**? "
            f"This will also remove {count} associated task{'s' if count != 1 else ''}."
        )
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("Yes, delete", type="primary"):
            new_subjects = []
            for s in st.session_state.subjects:
                if s.name != to_delete.name:
                    new_subjects.append(s)
            st.session_state.subjects = new_subjects
            new_tasks = []
            for t in st.session_state.tasks:
                if t.subject_name != to_delete.name:
                    new_tasks.append(t)
            st.session_state.tasks = new_tasks
            save_data()
            st.session_state.confirm_delete_subject = None
            st.rerun()
        if c2.button("Cancel"):
            st.session_state.confirm_delete_subject = None
            st.rerun()

    st.divider()

    if not st.session_state.subjects:
        empty_state("No subjects yet", "Add your first subject above.")
        return

    stats_by_subject = planner.get_stats_by_subject()

    for subject in st.session_state.subjects:
        s = stats_by_subject[subject.name]
        bar_pct = s["pct"]
        col_dot, col_name, col_bar, col_pct, col_del = st.columns([0.3, 2, 4, 1, 0.5])

        col_dot.markdown(
            f"<div style='width:12px;height:12px;border-radius:50%;"
            f"background:{subject.color};margin-top:6px'></div>",
            unsafe_allow_html=True,
        )
        col_name.markdown(f"**{subject.name}**")
        col_bar.markdown(
            f"<div style='margin-top:4px;background:#e8e8e4;border-radius:4px;height:8px;'>"
            f"<div style='width:{bar_pct}%;background:#1a1a1a;border-radius:4px;height:8px;'></div>"
            f"</div>"
            f"<div style='font-size:11px;color:#787774;margin-top:2px'>"
            f"{s['completed']}/{s['total']} tasks</div>",
            unsafe_allow_html=True,
        )
        col_pct.markdown(
            f"<div style='font-size:13px;font-weight:600;color:#1a1a1a;margin-top:2px'>"
            f"{bar_pct}%</div>",
            unsafe_allow_html=True,
        )
        if col_del.button("x", key=f"delsub_{subject.name}", help="Delete subject"):
            st.session_state.confirm_delete_subject = subject
            st.rerun()

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: PROGRESS REPORT
# ─────────────────────────────────────────────────────────────────────────────

def page_progress(planner):
    st.markdown("## Progress report")

    if not st.session_state.tasks:
        empty_state("No data yet",
                    "Add some tasks and complete them to see your progress.")
        return

    stats = planner.get_stats()
    pct   = stats["completion_pct"]

    # ── overall ──────────────────────────────────────────────────────────────
    section_label("Overall")
    c1, c2, c3 = st.columns(3)
    c1.metric("Tasks completed", f"{stats['completed']} / {stats['total']}")
    c2.metric("Completion rate",  f"{pct}%")
    c3.metric("Overdue",          stats["overdue"])
    st.progress(pct / 100)
    st.caption(f"{pct}% complete. {motivational_message(pct)}")

    st.divider()

    # ── by subject ────────────────────────────────────────────────────────────
    section_label("Completion by subject")
    stats_by_subject = planner.get_stats_by_subject()

    # ── by subject — HTML bar chart, always 0-100% ───────────────────────────
    section_label("Completion by subject")
    stats_by_subject = planner.get_stats_by_subject()

    has_any = False
    for name, data in stats_by_subject.items():
        if data["total"] > 0:
            has_any = True
            break

    if has_any:
        chart_html = "<div style='margin-bottom:16px'>"
        for name, data in stats_by_subject.items():
            if data["total"] == 0:
                continue
            subj  = planner.get_subject(name)
            color = subj.color if subj else "#888"
            pct_w = data["pct"]
            chart_html += (
                f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:14px'>"
                f"  <div style='width:12px;height:12px;border-radius:50%;background:{color};flex-shrink:0'></div>"
                f"  <div style='width:160px;font-size:13px;font-weight:500;color:#1a1a1a;flex-shrink:0'>{name}</div>"
                f"  <div style='flex:1;background:#ebebea;border-radius:99px;height:8px;min-width:80px'>"
                f"    <div style='width:{pct_w}%;background:{color};border-radius:99px;height:8px'></div>"
                f"  </div>"
                f"  <div style='width:40px;text-align:right;font-size:13px;font-weight:600;color:#1a1a1a;flex-shrink:0'>{pct_w}%</div>"
                f"  <div style='width:80px;font-size:12px;color:#9b9a97;flex-shrink:0'>{data['completed']}/{data['total']} tasks</div>"
                f"</div>"
            )
        chart_html += "</div>"
        st.markdown(chart_html, unsafe_allow_html=True)

    st.divider()

    # ── by task type ──────────────────────────────────────────────────────────
    section_label("Breakdown by task type")
    for task_type in Task.TYPES:
        type_tasks = []
        for t in planner.tasks:
            if t.task_type == task_type:
                type_tasks.append(t)
        if not type_tasks:
            continue
        done = 0
        for t in type_tasks:
            if t.completed:
                done = done + 1
        pct_type = round(done / len(type_tasks) * 100)
        st.markdown(f"{TYPE_ICONS[task_type]} **{task_type}s**: {done}/{len(type_tasks)} done")
        st.progress(pct_type / 100)

    st.divider()

    # ── upcoming deadlines ────────────────────────────────────────────────────
    section_label("Upcoming deadlines")
    upcoming = []
    for t in planner.tasks:
        if not t.completed and t.days_until_due() >= 0:
            upcoming.append(t)
    # sort by deadline, earliest first
    for i in range(1, len(upcoming)):
        current = upcoming[i]
        j = i - 1
        while j >= 0 and upcoming[j].deadline > current.deadline:
            upcoming[j + 1] = upcoming[j]
            j = j - 1
        upcoming[j + 1] = current

    if not upcoming:
        st.caption("No upcoming deadlines.")
    else:
        for task in upcoming[:10]:
            subj  = planner.get_subject(task.subject_name)
            color = subj.color if subj else "#888"
            st.markdown(task_card_html(task, color), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Student Planner Pro",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    apply_styles()
    init_state()

    planner = Planner(st.session_state.tasks, st.session_state.subjects)

    with st.sidebar:
        st.markdown("## 📚 Student Planner")
        st.markdown(
            f"<span style='font-size:12px;color:#9b9a97'>"
            f"{date.today().strftime('%A, %d %B %Y')}</span>",
            unsafe_allow_html=True,
        )
        st.divider()

        page = st.radio(
            "Navigation",
            ["🏠  Dashboard", "✅  Tasks", "📅  Weekly plan",
             "📚  Subjects", "📊  Progress report"],
            label_visibility="hidden",
        )

        st.divider()

        stats = planner.get_stats()
        pct   = stats["completion_pct"]
        st.markdown(
            f"<span style='font-size:12px;color:#9b9a97'>"
            f"{stats['completed']} of {stats['total']} tasks done</span>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='margin:6px 0 12px;background:#ebebea;border-radius:99px;height:4px;'>"
            f"<div style='width:{pct}%;background:#1a1a1a;border-radius:99px;height:4px;'></div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if stats["overdue"] > 0:
            st.markdown(
                f"<span style='font-size:12px;color:#c4320a;'>"
                f"⚠️ {stats['overdue']} overdue task{'s' if stats['overdue'] != 1 else ''}</span>",
                unsafe_allow_html=True,
            )

        st.divider()

        st.divider()
        if st.button("Refresh weather & holidays", use_container_width=True):
            st.session_state.weather  = fetch_weather()
            st.session_state.holidays = fetch_holidays()
            st.session_state.api_fetched_at = datetime.now().strftime("%H:%M")
            st.rerun()
        st.caption(f"Last fetched at {st.session_state.get('api_fetched_at', '--:--')}")
        st.caption("Weather: open-meteo.com")
        st.caption("Holidays: date.nager.at")

    if   "Dashboard"       in page: page_dashboard(planner)
    elif "Tasks"           in page: page_tasks(planner)
    elif "Weekly plan"     in page: page_weekly_plan(planner)
    elif "Subjects"        in page: page_subjects(planner)
    elif "Progress report" in page: page_progress(planner)


if __name__ == "__main__":
    main()

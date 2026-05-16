import streamlit as st
import requests
import json
import time
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
        self.task_id = f"{title[:8]}_{deadline.isoformat()}_{subject_name[:4]}_{int(time.time()*1000) % 100000}"
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
        self.last_pomodoro_date = None  # tracks streak

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
            return f"Done - was due {self.deadline.strftime('%d %b')}"
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

    def generate_study_plan(self, session_hours, blocked_dates, max_daily_hours=6):
        """
        Generates a smart study plan that spreads task work across available days.

        For each pending task:
        - Calculates how many sessions are needed (estimated_hours / session_hours)
        - Works BACKWARDS from the deadline, filling free days
        - Respects blocked_dates (e.g. imported exam days)
        - Never exceeds max_daily_hours per day
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

        for task in pending:
            # subtract hours already completed via Pomodoro (25 min = ~0.5h per session)
            pomodoro_hours_done = round(task.pomodoro_sessions * 0.5, 1)
            hours_left = task.estimated_hours - pomodoro_hours_done
            if hours_left <= 0:
                continue  # already done enough sessions, skip planning
            days_until = task.days_until_due()

            if days_until < 0:
                # overdue — show on today, but respect the daily cap
                today = date.today()
                if today in plan:
                    room = max_daily_hours - hours_per_day[today]
                    if room > 0:
                        scheduled = min(hours_left, room)
                        plan[today].append({
                            "task": task, "hours": scheduled, "session": 1
                        })
                        hours_per_day[today] = hours_per_day[today] + scheduled
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
                room = max_daily_hours - hours_per_day[day]
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
                room = max_daily_hours - hours_per_day[deadline_day]
                if room > 0:
                    scheduled = min(hours_left, room)
                    plan[deadline_day].append({
                        "task": task, "hours": scheduled, "session": session_num
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

    def get_next_deadline(self):
        """Returns the task with the nearest upcoming deadline, or None."""
        upcoming = []
        for t in self.tasks:
            if not t.completed and t.days_until_due() >= 0:
                upcoming.append(t)
        if not upcoming:
            return None
        nearest = upcoming[0]
        for t in upcoming[1:]:
            if t.deadline < nearest.deadline:
                nearest = t
        return nearest

    def get_weekly_summary(self):
        """
        Returns a dict summarising last week vs this week.
        last_completed: tasks completed in the last 7 days
        this_week_tasks: pending tasks due in the next 7 days
        this_week_hours: total estimated hours for those tasks
        """
        today     = date.today()
        week_ago  = today - timedelta(days=7)
        week_from = today + timedelta(days=7)

        last_completed = 0
        for t in self.tasks:
            if t.completed and t.created_on >= week_ago:
                last_completed = last_completed + 1

        this_week_tasks = 0
        this_week_hours = 0
        for t in self.tasks:
            if not t.completed and today <= t.deadline <= week_from:
                this_week_tasks = this_week_tasks + 1
                this_week_hours = this_week_hours + t.estimated_hours

        return {
            "last_completed": last_completed,
            "this_week_tasks": this_week_tasks,
            "this_week_hours": this_week_hours,
        }

    def get_study_streak(self):
        """
        Returns the current consecutive-day streak of Pomodoro sessions.
        A day counts if at least one task has last_pomodoro_date set to that day.
        Capped at 365 days to prevent unbounded iteration on corrupted data.
        """
        today = date.today()
        streak = 0
        check_day = today
        for _ in range(365):
            found = False
            for t in self.tasks:
                if t.last_pomodoro_date == check_day:
                    found = True
                    break
            if found:
                streak = streak + 1
                check_day = check_day - timedelta(days=1)
            else:
                break
        return streak


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

# ─────────────────────────────────────────────────────────────────────────────
# DATA PERSISTENCE  (one JSON file per user profile)
# ─────────────────────────────────────────────────────────────────────────────

PROFILES_FILE = "profiles.json"


def get_data_file(username):
    """Returns the data filename for a given username."""
    safe = username.lower().replace(" ", "_")
    return f"planner_{safe}.json"


PINS_FILE = "pins.json"


def load_pins():
    """Returns dict of {username: pin}."""
    try:
        f = open(PINS_FILE, "r")
        data = json.load(f)
        f.close()
        return data
    except Exception:
        return {}


def save_pins(pins):
    """Saves dict of {username: pin}."""
    f = open(PINS_FILE, "w")
    json.dump(pins, f)
    f.close()


def load_profiles():
    """Returns list of existing profile names."""
    try:
        f = open(PROFILES_FILE, "r")
        data = json.load(f)
        f.close()
        return data.get("profiles", [])
    except Exception:
        return []


def save_profiles(profiles):
    """Saves the list of profile names."""
    f = open(PROFILES_FILE, "w")
    json.dump({"profiles": profiles}, f)
    f.close()


def save_data():
    """Saves current user's subjects and tasks to their profile JSON file."""
    if "subjects" not in st.session_state or "tasks" not in st.session_state:
        return
    username = st.session_state.get("current_user", "default")
    subjects_data = []
    for s in st.session_state.subjects:
        subjects_data.append({"name": s.name, "color": s.color})

    tasks_data = []
    for t in st.session_state.tasks:
        tasks_data.append({
            "task_id": t.task_id,
            "title": t.title,
            "subject_name": t.subject_name,
            "deadline": t.deadline.isoformat(),
            "priority": t.priority,
            "task_type": t.task_type,
            "estimated_hours": t.estimated_hours,
            "notes": t.notes,
            "completed": t.completed,
            "created_on": t.created_on.isoformat(),
            "pomodoro_sessions": t.pomodoro_sessions,
            "last_pomodoro_date": t.last_pomodoro_date.isoformat() if t.last_pomodoro_date else None,
        })

    data = {"subjects": subjects_data, "tasks": tasks_data}
    f = open(get_data_file(username), "w")
    json.dump(data, f)
    f.close()


def load_data(username):
    """Loads subjects and tasks for a given username. Returns ([], []) if none."""
    try:
        f = open(get_data_file(username), "r")
        data = json.load(f)
        f.close()
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
        co = t.get("created_on")
        task.created_on = date.fromisoformat(co) if co else date.today()
        task.pomodoro_sessions = t.get("pomodoro_sessions", 0)
        lp = t.get("last_pomodoro_date")
        task.last_pomodoro_date = date.fromisoformat(lp) if lp else None
        if "task_id" in t:
            task.task_id = t["task_id"]
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

        # create task, skip duplicates (check both existing tasks and this import batch)
        duplicate = False
        for t in st.session_state.tasks:
            if t.title == item["title"] and t.deadline == item["deadline"]:
                duplicate = True
                break
        if not duplicate:
            for t in new_tasks:
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
    username = st.session_state.get("current_user", "default")
    if "subjects" not in st.session_state or "tasks" not in st.session_state:
        saved_subjects, saved_tasks = load_data(username)
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

    if "editing_subject" not in st.session_state:
        st.session_state.editing_subject = None

    if "add_mode" not in st.session_state:
        st.session_state.add_mode = None

    if "task_rows" not in st.session_state:
        st.session_state.task_rows = []

    if "show_add_task" not in st.session_state:
        st.session_state.show_add_task = False

    if "show_import" not in st.session_state:
        st.session_state.show_import = False

    if "pin_for" not in st.session_state:
        st.session_state.pin_for = None


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
        [data-testid="stMetricDelta"] svg { display: none !important; }
        [data-testid="stMetricDelta"] > div {
            font-size: 12px !important;
            font-weight: 500 !important;
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

        [data-testid="stButton"] button:focus,
        [data-testid="stButton"] button:active,
        [data-testid="stButton"] button:focus-visible {
            outline: none !important;
            box-shadow: none !important;
            border-color: #ebebea !important;
        }

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
        [data-testid="stProgress"] {
            height: 6px !important;
        }
        [data-testid="stProgress"] > div {
            background: #ebebea !important;
            border-radius: 99px !important;
            height: 6px !important;
            overflow: hidden !important;
        }
        [data-testid="stProgress"] > div > div {
            background: #1a1a1a !important;
            border-radius: 99px !important;
            height: 6px !important;
        }
        [data-testid="stProgress"] p { display: none !important; }

        /* ── hide only the radio circle dot, keep the label text ── */
        [data-testid="stRadio"] input[type="radio"] { display: none !important; }
        div[role="radiogroup"] > label > div:first-child { display: none !important; }
        /* highlight the selected radio option */
        div[role="radiogroup"] > label[data-selected="true"],
        div[role="radiogroup"] > label[aria-checked="true"] {
            font-weight: 600 !important;
            color: #1a1a1a !important;
        }

        /* ── mobile nav selectbox ── */
        /* on desktop: hide it entirely, sidebar handles nav */
        div[data-testid="stSelectbox"][data-key="mobile_nav"],
        div:has(> div[data-testid="stSelectbox"] label[data-testid*="mobile"]) {
            display: none !important;
        }

        /* on mobile: show it as a sticky top bar */
        @media (max-width: 768px) {
            div[data-testid="stSelectbox"][data-key="mobile_nav"] {
                display: block !important;
                position: sticky !important;
                top: 0 !important;
                z-index: 999 !important;
                background: #ffffff !important;
                padding: 8px 0 4px !important;
                border-bottom: 1px solid #ebebea !important;
                margin-bottom: 16px !important;
            }
        }
        [data-testid="stSidebarCollapseButton"] { display: none !important; }
        [data-testid="collapsedControl"]        { display: none !important; }

        @media (max-width: 768px) {
            /* show the toggle arrow on mobile and make it easy to tap */
            [data-testid="collapsedControl"] {
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                position: fixed !important;
                top: 12px !important;
                left: 12px !important;
                z-index: 9999 !important;
                width: 44px !important;
                height: 44px !important;
                background: #1a1a1a !important;
                border-radius: 10px !important;
                box-shadow: 0 2px 8px rgba(0,0,0,0.15) !important;
            }
            [data-testid="collapsedControl"] svg {
                color: #ffffff !important;
                fill: #ffffff !important;
                width: 20px !important;
                height: 20px !important;
            }
            /* push page content down so it doesn't hide under the button */
            .main .block-container {
                padding-top: 64px !important;
            }
        }

        [data-testid="stAlert"] {
            border-radius: 8px !important;
            font-size: 13px !important;
        }
        [data-testid="stAlert"] p { color: inherit !important; }

        [data-testid="stCaptionContainer"] p {
            color: #9b9a97 !important;
            font-size: 12px !important;
        }

        hr { border: none !important; border-top: 1px solid #ebebea !important; margin: 1.5rem 0 !important; }

        /* ── checkbox ── */
        [data-testid="stCheckbox"] label span {
            color: #1a1a1a !important;
            font-size: 14px !important;
        }
        [data-testid="stCheckbox"] input[type="checkbox"] + div {
            background: #ffffff !important;
            border-color: #c7c6c3 !important;
        }
        [data-testid="stCheckbox"] input[type="checkbox"]:checked + div {
            background: #1a1a1a !important;
            border-color: #1a1a1a !important;
        }
        [data-testid="stCheckbox"] input[type="checkbox"]:checked + div svg {
            color: #ffffff !important;
            fill: #ffffff !important;
        }

        /* ── tooltips — force light background ── */
        [data-testid="stTooltipContent"],
        div[data-baseweb="tooltip"],
        div[role="tooltip"] {
            background: #ffffff !important;
            color: #1a1a1a !important;
            border: 1px solid #ebebea !important;
            border-radius: 6px !important;
            font-size: 12px !important;
        }

        /* ── file uploader ── */
        [data-testid="stFileUploader"] {
            background: #ffffff !important;
        }
        /* ── file uploader ── */
        [data-testid="stFileUploader"] section {
            background: #f9f9f8 !important;
            border: 1.5px dashed #c7c6c3 !important;
            border-radius: 10px !important;
            padding: 16px 20px !important;
        }
        [data-testid="stFileUploader"] section:hover {
            border-color: #1a1a1a !important;
            background: #f4f4f2 !important;
        }
        [data-testid="stFileUploader"] label p {
            color: #1a1a1a !important;
            font-size: 13px !important;
            font-weight: 500 !important;
        }
        [data-testid="stFileUploader"] section span,
        [data-testid="stFileUploader"] section small,
        [data-testid="stFileUploader"] section p {
            color: #9b9a97 !important;
            font-size: 12px !important;
        }
        /* hide every text node inside the button including nested spans */
        [data-testid="stFileUploader"] section button span,
        [data-testid="stFileUploader"] section button p,
        [data-testid="stFileUploader"] section button div {
            visibility: hidden !important;
            font-size: 0 !important;
            width: 0 !important;
            overflow: hidden !important;
        }
        [data-testid="stFileUploader"] section button {
            background: #ffffff !important;
            border: 1px solid #c7c6c3 !important;
            border-radius: 7px !important;
            font-size: 0 !important;
            color: transparent !important;
            min-width: 110px !important;
            position: relative !important;
            overflow: visible !important;
        }
        [data-testid="stFileUploader"] section button::after {
            content: "Browse file" !important;
            color: #1a1a1a !important;
            font-size: 12px !important;
            font-weight: 500 !important;
            font-family: 'Inter', -apple-system, sans-serif !important;
            position: absolute !important;
            left: 50% !important;
            top: 50% !important;
            transform: translate(-50%, -50%) !important;
            white-space: nowrap !important;
        }

        [data-testid="stTextInput"] input:focus {
            border-color: #9b9a97 !important;
            box-shadow: none !important;
            outline: none !important;
        }
        [data-testid="stTextInput"] input[type="password"]:focus {
            border-color: #9b9a97 !important;
            box-shadow: none !important;
            outline: none !important;
        }
        /* eye toggle button — kill dark pill wrapper, force white */
        [data-baseweb="input"] {
            background: #ffffff !important;
        }
        [data-baseweb="input"] > div:last-child {
            background: #ffffff !important;
            border: none !important;
        }
        [data-baseweb="input"] button,
        [data-baseweb="input"] button:hover {
            background: #ffffff !important;
            border: none !important;
            color: #787774 !important;
            box-shadow: none !important;
        }
        [data-baseweb="input"] button svg {
            fill: #787774 !important;
            color: #787774 !important;
        }
        /* hide "Press Enter to submit" — overlaps with eye icon */
        [data-testid="InputInstructions"] {
            display: none !important;
        }
        /* hide the black Streamlit top header bar */
        [data-testid="stHeader"] {
            display: none !important;
        }

        /* ── uploaded file pill — override Streamlit's default dark pill ── */
        [data-testid="stFileUploaderFile"],
        [data-testid="stFileUploaderFile"] * {
            background: #f4f4f2 !important;
            color: #1a1a1a !important;
            border-color: #ebebea !important;
        }
        [data-testid="stFileUploaderFile"] button,
        [data-testid="stFileUploaderFile"] button * {
            color: #787774 !important;
            background: transparent !important;
            border: none !important;
        }
        [data-testid="stFileUploaderFile"] button:hover,
        [data-testid="stFileUploaderFile"] button:hover * {
            color: #c4320a !important;
            background: transparent !important;
        }

        /* catch-all: any button that still has dark background needs white text */
        button[style*="background-color: rgb(49, 51, 63)"],
        button[style*="background: rgb(49, 51, 63)"] {
            color: #ffffff !important;
        }

        /* ── slider ── */
        [data-testid="stSlider"] label p {
            color: #1a1a1a !important;
            font-size: 13px !important;
        }
        [data-testid="stSlider"] [data-testid="stTickBarMin"],
        [data-testid="stSlider"] [data-testid="stTickBarMax"] {
            color: #9b9a97 !important;
            font-size: 11px !important;
        }

        /* ═══════════════════════════════════════════════════════════════════
           MOBILE  (≤ 768px)
           ═══════════════════════════════════════════════════════════════════ */
        @media (max-width: 768px) {

            /* ── main content: remove side padding, use full width ── */
            .main .block-container {
                padding: 12px 12px 40px !important;
                max-width: 100% !important;
            }

            /* ── sidebar: full-width when open ── */
            [data-testid="stSidebar"] {
                width: 85vw !important;
                min-width: unset !important;
            }

            /* ── stack all columns vertically ── */
            [data-testid="stHorizontalBlock"] {
                flex-direction: column !important;
                gap: 8px !important;
            }
            [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
                width: 100% !important;
                min-width: 100% !important;
                flex: 1 1 100% !important;
            }

            /* ── buttons: bigger tap targets ── */
            [data-testid="stButton"] button,
            [data-testid="stFormSubmitButton"] button {
                min-height: 44px !important;
                font-size: 14px !important;
                width: 100% !important;
            }

            /* ── inputs: full width, 16px stops iOS auto-zoom ── */
            [data-testid="stTextInput"] input,
            [data-testid="stNumberInput"] input,
            [data-testid="stSelectbox"] div,
            [data-testid="stDateInput"] input {
                font-size: 16px !important;
                min-height: 44px !important;
            }

            /* ── headings scale down ── */
            h1 { font-size: 22px !important; }
            h2 { font-size: 18px !important; }
            h3 { font-size: 15px !important; }

            /* ── metrics: 2-column grid on mobile ── */
            [data-testid="stMetric"] {
                padding: 10px 12px !important;
            }
            [data-testid="stMetricValue"] {
                font-size: 26px !important;
            }

            /* ── expanders full width ── */
            [data-testid="stExpander"] {
                width: 100% !important;
            }

            /* ── slider: full width ── */
            [data-testid="stSlider"] {
                width: 100% !important;
            }

            /* ── task cards: let text wrap ── */
            [data-testid="stMarkdownContainer"] div {
                word-break: break-word !important;
                white-space: normal !important;
            }

            /* ── file uploader: full width ── */
            [data-testid="stFileUploader"] {
                width: 100% !important;
            }

            /* ── profile page: full width ── */
            div[style*="max-width:480px"] {
                max-width: 100% !important;
                margin: 20px auto 0 !important;
                padding: 0 4px !important;
            }
        }

        @media (max-width: 480px) {
            .main .block-container {
                padding: 8px 8px 40px !important;
            }
            [data-testid="stMetricValue"] {
                font-size: 22px !important;
            }
            h1 { font-size: 20px !important; }
            h2 { font-size: 16px !important; }
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
        f'    &nbsp;-&nbsp; {task.subject_name}'
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

    # ── deadline countdown + streak + weekly summary ───────────────────────
    if st.session_state.tasks:
        st.divider()
        col_a, col_b, col_c = st.columns(3)

        # next deadline countdown
        next_task = planner.get_next_deadline()
        with col_a:
            if next_task:
                days_left = next_task.days_until_due()
                if days_left == 0:
                    countdown_label = "Due today"
                    countdown_color = "#c4320a"
                elif days_left == 1:
                    countdown_label = "Due tomorrow"
                    countdown_color = "#a56123"
                else:
                    countdown_label = f"{days_left} days left"
                    countdown_color = "#1a1a1a"
                st.markdown(
                    f"<div style='border:1px solid #ebebea;border-radius:10px;padding:16px 18px;'>"
                    f"<div style='font-size:11px;font-weight:600;letter-spacing:0.07em;"
                    f"text-transform:uppercase;color:#9b9a97;margin-bottom:8px'>Next deadline</div>"
                    f"<div style='font-size:24px;font-weight:600;color:{countdown_color};"
                    f"letter-spacing:-0.5px;margin-bottom:4px'>{countdown_label}</div>"
                    f"<div style='font-size:12px;color:#9b9a97'>{next_task.title}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div style='border:1px solid #ebebea;border-radius:10px;padding:16px 18px;'>"
                    "<div style='font-size:11px;font-weight:600;letter-spacing:0.07em;"
                    "text-transform:uppercase;color:#9b9a97;margin-bottom:8px'>Next deadline</div>"
                    "<div style='font-size:14px;color:#9b9a97'>No upcoming deadlines</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )

        # study streak
        with col_b:
            streak = planner.get_study_streak()
            if streak > 0:
                streak_label = f"{streak} day{'s' if streak != 1 else ''}"
                streak_sub   = "Keep it up!" if streak < 3 else "Great consistency!" if streak < 7 else "Outstanding streak!"
            else:
                streak_label = "No streak yet"
                streak_sub   = "Complete a Pomodoro session to start one."
            st.markdown(
                f"<div style='border:1px solid #ebebea;border-radius:10px;padding:16px 18px;'>"
                f"<div style='font-size:11px;font-weight:600;letter-spacing:0.07em;"
                f"text-transform:uppercase;color:#9b9a97;margin-bottom:8px'>🍅 Study streak</div>"
                f"<div style='font-size:24px;font-weight:600;color:#1a1a1a;"
                f"letter-spacing:-0.5px;margin-bottom:4px'>{streak_label}</div>"
                f"<div style='font-size:12px;color:#9b9a97'>{streak_sub}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # weekly summary
        with col_c:
            summary = planner.get_weekly_summary()
            st.markdown(
                f"<div style='border:1px solid #ebebea;border-radius:10px;padding:16px 18px;'>"
                f"<div style='font-size:11px;font-weight:600;letter-spacing:0.07em;"
                f"text-transform:uppercase;color:#9b9a97;margin-bottom:8px'>This week</div>"
                f"<div style='font-size:24px;font-weight:600;color:#1a1a1a;"
                f"letter-spacing:-0.5px;margin-bottom:4px'>"
                f"{summary['this_week_tasks']} task{'s' if summary['this_week_tasks'] != 1 else ''}</div>"
                f"<div style='font-size:12px;color:#9b9a97'>"
                f"{summary['this_week_hours']}h estimated"
                + (f" · {summary['last_completed']} completed last week" if summary['last_completed'] > 0 else "")
                + "</div>"
                + "</div>",
                unsafe_allow_html=True,
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
        if not st.session_state.tasks:
            empty_state("No tasks yet", "Go to Tasks and add your first assignment, exam, or study session.")
        else:
            empty_state("All caught up", "Every task is completed. Add new ones when you are ready.")
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

    # ── success toast ─────────────────────────────────────────────────────────
    if st.session_state.get("save_toast"):
        st.success(st.session_state.save_toast)
        del st.session_state["save_toast"]

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
                f"<div style='border:1px solid #ebebea;border-radius:8px;"
                f"padding:14px 16px;margin-bottom:14px;background:#ffffff;"
                f"box-shadow:0 1px 3px rgba(0,0,0,0.04)'>"
                f"<div style='font-size:11px;font-weight:600;letter-spacing:0.06em;"
                f"text-transform:uppercase;color:#9b9a97;margin-bottom:10px'>"
                f"Task {idx + 1}</div>",
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
            row["tasktype"] = c2.selectbox("Type",     Task.TYPES,      index=Task.TYPES.index(row["tasktype"]),      key=f"type_{idx}", label_visibility="collapsed",
                                           help="Assignment: coursework or project\nExam: counts as a blocked day in the study plan\nStudy session: self-directed revision")
            row["priority"] = c3.selectbox("Priority", Task.PRIORITIES, index=Task.PRIORITIES.index(row["priority"]), key=f"prio_{idx}", label_visibility="collapsed",
                                           help="Affects urgency score.\nHigh (×3) · Medium (×2) · Low (×1)\nHigher priority tasks appear first on the dashboard and get scheduled earlier.")
            row["deadline"] = c4.date_input("Deadline", value=row["deadline"], min_value=date.today(), key=f"dead_{idx}", label_visibility="collapsed")

            h_col, n_col = st.columns([1, 3])
            h_col.caption("Estimated hours")
            n_col.caption("Notes (optional)")
            row["hours"] = h_col.number_input("Hours", min_value=1, max_value=100, value=row["hours"], step=1, key=f"hrs_{idx}", label_visibility="collapsed",
                                              help="How many hours you expect this task to take in total. The study plan uses this to spread sessions across days.")
            row["notes"] = n_col.text_input("Notes", value=row["notes"], placeholder="e.g. check lecture slides first", key=f"notes_{idx}", label_visibility="collapsed")
            st.markdown("</div>", unsafe_allow_html=True)

        for idx in sorted(rows_to_delete, reverse=True):
            st.session_state.task_rows.pop(idx)
        if rows_to_delete:
            st.rerun()

        add_col, save_col, cancel_col = st.columns([1, 1, 1])
        if add_col.button("+ Add another row", use_container_width=True):
            last = st.session_state.task_rows[-1] if st.session_state.task_rows else {}
            default_subject = subject_names[0] if subject_names else ""
            st.session_state.task_rows.append({
                "title": "",
                "subject":  last.get("subject",  default_subject),
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
            if errors:
                for e in errors:
                    st.error(e)
            else:
                saved_count = 0
                for row in st.session_state.task_rows:
                    st.session_state.tasks.append(
                        Task(row["title"].strip(), row["subject"], row["deadline"],
                             row["priority"], row["tasktype"], row["hours"], row["notes"].strip())
                    )
                    saved_count = saved_count + 1
                save_data()
                st.session_state.task_rows = []
                st.session_state.add_mode  = None
                st.session_state.save_toast = f"✓ {saved_count} task{'s' if saved_count != 1 else ''} saved."
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
            "📎 Click here to upload your .ics calendar file", type=["ics"],
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

                # import defaults
                col_p, col_h = st.columns(2)
                import_priority = col_p.selectbox("Default priority for imported tasks",
                                                  Task.PRIORITIES, index=0,
                                                  key="import_priority")
                import_hours    = col_h.number_input("Default estimated hours",
                                                     min_value=1, max_value=20,
                                                     value=3, step=1,
                                                     key="import_hours")

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
                        t.priority         = import_priority
                        t.estimated_hours  = import_hours
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
            new_type     = col2.selectbox("Type", Task.TYPES, index=Task.TYPES.index(editing.task_type),
                                          help="Assignment: coursework or project\nExam: counts as a blocked day in the study plan\nStudy session: self-directed revision")
            col3, col4   = st.columns(2)
            new_deadline = col3.date_input("Deadline", value=editing.deadline)
            new_priority = col4.selectbox("Priority", Task.PRIORITIES,
                                          index=Task.PRIORITIES.index(editing.priority),
                                          help="Affects urgency score.\nHigh (×3) · Medium (×2) · Low (×1)")
            new_hours = st.number_input("Estimated hours", min_value=1, max_value=100,
                                        value=editing.estimated_hours, step=1,
                                        help="Total hours expected. Used to spread study sessions across days in the study plan.")
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
    # completed tasks go to the archive section below; only pending shown here.
    visible = []
    for t in st.session_state.tasks:
        if matches(t) and not t.completed:
            visible.append(t)

    # sort by urgency score descending
    for i in range(1, len(visible)):
        current = visible[i]
        j = i - 1
        while j >= 0 and visible[j].urgency_score() < current.urgency_score():
            visible[j + 1] = visible[j]
            j = j - 1
        visible[j + 1] = current

    # ── task list ─────────────────────────────────────────────────────────────
    if not st.session_state.tasks:
        empty_state("No tasks yet", "Use the form above to add your first task.")
    elif not visible:
        completed_total = sum(1 for t in st.session_state.tasks if t.completed)
        if completed_total > 0:
            empty_state("All caught up!", f"All matching tasks are completed. Check the archive below.")
        else:
            empty_state("No tasks match your filters",
                        "Try adjusting the search or filter options.")
    else:
        # ── pomodoro timer panel ──────────────────────────────────────────────
        pom_task_id = st.session_state.pomodoro_task_id
        pom_start   = st.session_state.pomodoro_start
        pom_paused  = st.session_state.pomodoro_paused_remaining
        POMODORO_MINS = 25

        if pom_task_id is not None:
            # find the active task by task_id string (id() changes on every rerun)
            active_task = None
            for t in st.session_state.tasks:
                if t.task_id == pom_task_id:
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
                    active_task.last_pomodoro_date = date.today()
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
                                       key=f"chk_{task.task_id}",
                                       label_visibility="collapsed")
            if new_val != task.completed:
                task.completed = new_val
                save_data()
                st.rerun()

            col_card.markdown(task_card_html(task, color), unsafe_allow_html=True)

            is_active = st.session_state.pomodoro_task_id == task.task_id
            focus_label = "🍅 Active" if is_active else "🍅 Focus"
            if col_focus.button(focus_label, key=f"pom_{task.task_id}", use_container_width=True):
                if is_active:
                    st.session_state.pomodoro_task_id = None
                    st.session_state.pomodoro_start   = None
                    st.session_state.pomodoro_paused_remaining = None
                else:
                    st.session_state.pomodoro_task_id = task.task_id
                    st.session_state.pomodoro_start   = datetime.now()
                    st.session_state.pomodoro_paused_remaining = None
                st.rerun()

            if col_edit.button("Edit", key=f"edit_{task.task_id}", use_container_width=True):
                st.session_state.editing_task = task
                st.rerun()

            if col_del.button("Delete", key=f"del_{task.task_id}", use_container_width=True):
                st.session_state.confirm_delete_task = task
                st.rerun()

    # ── completed tasks archive ───────────────────────────────────────────────
    # Uses a separate filter that ignores status (archive is always completed)
    def matches_archive(t):
        if search and search.lower() not in t.title.lower():
            return False
        if filter_subject != "All subjects" and t.subject_name != filter_subject:
            return False
        if filter_type != "All types" and t.task_type != filter_type:
            return False
        return True

    completed_tasks = []
    for t in st.session_state.tasks:
        if t.completed and matches_archive(t):
            completed_tasks.append(t)

    if completed_tasks:
        st.divider()
        with st.expander(f"📦 Completed tasks ({len(completed_tasks)})"):
            st.markdown(
                "<div style='font-size:12px;color:#9b9a97;margin-bottom:10px'>"
                "These tasks are done. Mark them incomplete using the checkbox if needed.</div>",
                unsafe_allow_html=True,
            )
            for task in completed_tasks:
                subj  = planner.get_subject(task.subject_name)
                color = subj.color if subj else "#888"
                col_chk, col_card, _, col_del = st.columns([0.4, 6, 2.4, 1.2])
                new_val = col_chk.checkbox("done", value=task.completed,
                                           key=f"arch_chk_{task.task_id}",
                                           label_visibility="collapsed")
                if new_val != task.completed:
                    task.completed = new_val
                    save_data()
                    st.rerun()
                col_card.markdown(task_card_html(task, color), unsafe_allow_html=True)
                if col_del.button("Delete", key=f"arch_del_{task.task_id}", use_container_width=True):
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

    # ── view toggle + sliders — all in one column block, nothing else ────────
    view_col, pref_col = st.columns([2, 2])
    view_mode = view_col.radio(
        "View",
        ["Study plan", "Deadline view"],
        horizontal=True,
        label_visibility="collapsed",
    )

    # sliders only shown for study plan mode; read them here inside the column
    if view_mode == "Study plan":
        session_hours   = pref_col.slider("Session length (hours)",    min_value=1, max_value=4,  value=2, step=1)
        max_daily_hours = pref_col.slider("Max study hours per day",   min_value=2, max_value=12, value=6, step=1)
    else:
        session_hours   = 2
        max_daily_hours = 6

    # ── everything below is full-width — no more column context ──────────────
    weather = st.session_state.weather
    if weather:
        st.caption(f"{weather['condition']}, {weather['temp']}°C · {weather['tip']}")

    holiday_dates = {}
    for h in st.session_state.holidays:
        holiday_dates[h["date"]] = h["name"]

    # shared info expander — full width, no overlap
    with st.expander("ℹ️ How does the urgency score and study plan work?"):
        st.markdown(
            """
            <div style='font-size:13px;color:#37352f;line-height:1.8'>
            <b>Urgency score</b><br>
            Each task gets a score controlling how urgently it appears on the dashboard:<br><br>
            <code style='background:#f4f4f2;padding:2px 6px;border-radius:4px;font-size:12px'>
            score = (priority_weight × 10) ÷ days_until_deadline
            </code><br><br>
            Priority weights: <b>High = 3</b> · <b>Medium = 2</b> · <b>Low = 1</b> ·
            Overdue tasks always score <b>100</b>.<br><br>
            <b>Study plan scheduling</b><br>
            Work is spread <b>backwards from each deadline</b> across free days in sessions
            of your chosen length, capped at your daily maximum. Exam days are blocked.
            Completed Pomodoro sessions are subtracted from remaining hours automatically.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── deadline view ─────────────────────────────────────────────────────────
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
        st.caption(
            f"Sessions of {session_hours}h, max {max_daily_hours}h/day. "
            f"Exam days are blocked."
        )

        # blocked dates = imported exam tasks
        blocked = {}
        for t in planner.tasks:
            if t.task_type == "Exam" and not t.completed:
                blocked[t.deadline.isoformat()] = t.title

        study_plan = planner.generate_study_plan(session_hours, blocked, max_daily_hours)

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

    # edit subject form
    if "editing_subject" not in st.session_state:
        st.session_state.editing_subject = None

    if st.session_state.editing_subject is not None:
        editing_subj = st.session_state.editing_subject
        st.markdown("**Edit subject**")
        with st.form("edit_subject_form"):
            new_name  = st.text_input("Name",   value=editing_subj.name)
            new_color = st.color_picker("Colour", value=editing_subj.color)
            cs, cc    = st.columns(2)
            if cs.form_submit_button("Save", use_container_width=True):
                if not new_name.strip():
                    st.error("Name cannot be empty.")
                else:
                    # update tasks that reference old name
                    for t in st.session_state.tasks:
                        if t.subject_name == editing_subj.name:
                            t.subject_name = new_name.strip()
                    editing_subj.name  = new_name.strip()
                    editing_subj.color = new_color
                    save_data()
                    st.session_state.editing_subject = None
                    st.rerun()
            if cc.form_submit_button("Cancel", use_container_width=True):
                st.session_state.editing_subject = None
                st.rerun()
        st.divider()

    stats_by_subject = planner.get_stats_by_subject()

    for subject in st.session_state.subjects:
        s       = stats_by_subject[subject.name]
        bar_pct = s["pct"]
        is_done = s["total"] > 0 and s["pct"] == 100

        col_dot, col_name, col_bar, col_pct, col_edit, col_del = st.columns([0.3, 2, 4, 1, 0.5, 0.5])

        col_dot.markdown(
            f"<div style='width:12px;height:12px;border-radius:50%;"
            f"background:{subject.color};margin-top:6px'></div>",
            unsafe_allow_html=True,
        )
        done_badge = " <span style='font-size:11px;color:#2d7a3a;font-weight:500'>All done</span>" if is_done else ""
        col_name.markdown(f"**{subject.name}**{done_badge}", unsafe_allow_html=True)
        bar_color = "#2d7a3a" if is_done else "#1a1a1a"
        col_bar.markdown(
            f"<div style='margin-top:4px;background:#e8e8e4;border-radius:4px;height:8px;'>"
            f"<div style='width:{bar_pct}%;background:{bar_color};border-radius:4px;height:8px;'></div>"
            f"</div>"
            f"<div style='font-size:11px;color:#787774;margin-top:2px'>"
            f"{s['completed']}/{s['total']} tasks</div>",
            unsafe_allow_html=True,
        )
        col_pct.markdown(
            f"<div style='font-size:13px;font-weight:600;color:{bar_color};margin-top:2px'>"
            f"{bar_pct}%</div>",
            unsafe_allow_html=True,
        )
        if col_edit.button("✏️", key=f"editsub_{subject.name}", help="Edit subject"):
            st.session_state.editing_subject = subject
            st.rerun()
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

    if not stats_by_subject:
        st.caption("No subjects yet.")
    else:
        chart_html = "<div style='margin-bottom:16px'>"
        for name, data in stats_by_subject.items():
            subj  = planner.get_subject(name)
            color = subj.color if subj else "#888"
            pct_w = data["pct"]
            bar_color = "#2d7a3a" if pct_w == 100 else color
            chart_html += (
                f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:14px'>"
                f"  <div style='width:12px;height:12px;border-radius:50%;background:{color};flex-shrink:0'></div>"
                f"  <div style='width:160px;font-size:13px;font-weight:500;color:#1a1a1a;flex-shrink:0'>{name}</div>"
                f"  <div style='flex:1;background:#ebebea;border-radius:99px;height:8px;min-width:80px'>"
                f"    <div style='width:{pct_w}%;background:{bar_color};border-radius:99px;height:8px'></div>"
                f"  </div>"
                f"  <div style='width:40px;text-align:right;font-size:13px;font-weight:600;color:{bar_color};flex-shrink:0'>{pct_w}%</div>"
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
# PROFILE SCREEN
# ─────────────────────────────────────────────────────────────────────────────

def page_profile_select():
    """Shown before the app loads — lets user pick or create a profile."""
    st.markdown(
        "<div style='max-width:480px;margin:80px auto 0;padding:0 24px;'>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='font-size:32px;font-weight:600;letter-spacing:-0.5px;"
        "color:#1a1a1a;margin-bottom:6px'>📚 Student Planner</div>"
        "<div style='font-size:15px;color:#9b9a97;margin-bottom:40px'>"
        "Select a profile or create a new one to get started.</div>",
        unsafe_allow_html=True,
    )

    profiles = load_profiles()

    # ── existing profiles ─────────────────────────────────────────────────────
    if profiles:
        st.markdown(
            "<div style='font-size:11px;font-weight:600;letter-spacing:0.07em;"
            "text-transform:uppercase;color:#9b9a97;margin-bottom:12px'>"
            "Your profiles</div>",
            unsafe_allow_html=True,
        )

        if "pin_for" not in st.session_state:
            st.session_state.pin_for = None

        for name in profiles:
            initial = name[0].upper() if name else "?"
            is_selected = st.session_state.pin_for == name
            border = "2px solid #1a1a1a" if is_selected else "1px solid #ebebea"
            bg = "#f9f9f8" if is_selected else "#ffffff"

            # render avatar + name as pure HTML (no columns — mobile safe)
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:12px;"
                f"background:{bg};border:{border};border-radius:10px;"
                f"padding:12px 14px;margin-bottom:4px'>"
                f"<div style='width:36px;height:36px;min-width:36px;border-radius:50%;"
                f"background:#1a1a1a;color:#fff;display:flex;align-items:center;"
                f"justify-content:center;font-size:15px;font-weight:600'>{initial}</div>"
                f"<div style='font-size:14px;font-weight:500;color:#1a1a1a;flex:1'>{name}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button("Select →", key=f"profile_{name}", use_container_width=True):
                st.session_state.pin_for = name
                st.rerun()
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # PIN entry
        if st.session_state.pin_for is not None:
            target = st.session_state.pin_for
            st.markdown(
                f"<div style='font-size:13px;color:#9b9a97;margin:4px 0 8px'>"
                f"Enter PIN for <b style='color:#1a1a1a'>{target}</b></div>",
                unsafe_allow_html=True,
            )
            with st.form("pin_form"):
                pin_input = st.text_input("PIN", type="password",
                                          placeholder="4-digit PIN",
                                          label_visibility="collapsed")
                c1, c2 = st.columns(2)
                if c1.form_submit_button("Enter", use_container_width=True):
                    stored_pins = load_pins()
                    if stored_pins.get(target) == pin_input:
                        st.session_state.current_user = target
                        st.session_state.pin_for = None
                        saved_subjects, saved_tasks = load_data(target)
                        st.session_state.subjects = saved_subjects
                        st.session_state.tasks    = saved_tasks
                        st.rerun()
                    else:
                        st.error("Incorrect PIN.")
                if c2.form_submit_button("Cancel", use_container_width=True):
                    st.session_state.pin_for = None
                    st.rerun()

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── create new profile ────────────────────────────────────────────────────
    st.markdown(
        "<div style='font-size:11px;font-weight:600;letter-spacing:0.07em;"
        "text-transform:uppercase;color:#9b9a97;margin-bottom:12px'>"
        "New profile</div>",
        unsafe_allow_html=True,
    )

    with st.form("new_profile_form"):
        new_name = st.text_input("Your name", placeholder="e.g. Max")
        new_pin  = st.text_input("Choose a 4-digit PIN", type="password",
                                  placeholder="e.g. 1234")
        if st.form_submit_button("Create profile", use_container_width=True):
            if not new_name.strip():
                st.error("Please enter a name.")
            elif not new_pin.strip().isdigit() or len(new_pin.strip()) != 4:
                st.error("PIN must be exactly 4 digits.")
            elif new_name.strip() in profiles:
                st.error("A profile with that name already exists.")
            else:
                profiles.append(new_name.strip())
                save_profiles(profiles)
                pins = load_pins()
                pins[new_name.strip()] = new_pin.strip()
                save_pins(pins)
                st.session_state.current_user = new_name.strip()
                st.session_state.pin_for = None
                st.session_state.subjects = []
                st.session_state.tasks    = []
                st.rerun()


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

    # ── profile gate ──────────────────────────────────────────────────────────
    if "current_user" not in st.session_state:
        page_profile_select()
        return

    init_state()
    planner = Planner(st.session_state.tasks, st.session_state.subjects)

    with st.sidebar:
        st.markdown("## 📚 Student Planner")
        st.markdown(
            f"<span style='font-size:12px;color:#9b9a97'>"
            f"👤 {st.session_state.current_user}</span><br>"
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
        if st.button("Refresh weather & holidays", use_container_width=True):
            st.session_state.weather  = fetch_weather()
            st.session_state.holidays = fetch_holidays()
            st.session_state.api_fetched_at = datetime.now().strftime("%H:%M")
            st.rerun()
        st.caption(f"Last fetched at {st.session_state.get('api_fetched_at', '--:--')}")
        st.caption("Weather: open-meteo.com")
        st.caption("Holidays: date.nager.at")

        st.divider()
        if st.button("Switch profile", use_container_width=True):
            for key in ["current_user", "subjects", "tasks",
                        "weather", "holidays", "api_fetched_at",
                        "confirm_delete_task", "confirm_delete_subject",
                        "editing_task", "editing_subject",
                        "pomodoro_task_id", "pomodoro_start",
                        "pomodoro_paused_remaining", "add_mode",
                        "task_rows", "show_add_task", "show_import",
                        "show_add_subject", "save_toast", "pin_for"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    # ── mobile nav bar (hidden on desktop via CSS) ────────────────────────────
    st.markdown("<div class='mobile-nav-wrapper'>", unsafe_allow_html=True)
    mobile_page = st.selectbox(
        "📍 Go to page",
        ["🏠  Dashboard", "✅  Tasks", "📅  Weekly plan",
         "📚  Subjects", "📊  Progress report"],
        key="mobile_nav",
    )
    st.markdown("</div>", unsafe_allow_html=True)
    # sync: mobile selectbox drives the page when sidebar isn't visible
    page = mobile_page

    if   "Dashboard"       in page: page_dashboard(planner)
    elif "Tasks"           in page: page_tasks(planner)
    elif "Weekly plan"     in page: page_weekly_plan(planner)
    elif "Subjects"        in page: page_subjects(planner)
    elif "Progress report" in page: page_progress(planner)


if __name__ == "__main__":
    main()

import os
import subprocess
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo
import calendar

import streamlit as st
import streamlit.runtime as rt
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    func,
    select,
    text,
    update,
)


# Run with `python app.py` as well as `streamlit run app.py`.
if __name__ == "__main__" and not rt.exists():
    subprocess.run([sys.executable, "-m", "streamlit", "run", __file__], check=False)
    sys.exit()


APP_TIMEZONE = ZoneInfo("Asia/Seoul")
LOCAL_DB_NAME = "routine_app.db"


def get_database_url():
    """Use a cloud DB when configured, otherwise keep the local SQLite fallback."""
    database_url = None

    try:
        database_url = st.secrets.get("DATABASE_URL")
    except Exception:
        database_url = None

    database_url = database_url or os.getenv("DATABASE_URL")

    if database_url:
        # Supabase commonly provides postgresql:// URLs. pg8000 is pure Python and works well on Streamlit Cloud.
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+pg8000://", 1)
        elif database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+pg8000://", 1)
        return database_url

    return f"sqlite:///{LOCAL_DB_NAME}"


DATABASE_URL = get_database_url()
engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
metadata = MetaData()

routines = Table(
    "routines",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(200), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
)

routine_logs = Table(
    "routine_logs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("routine_id", Integer, ForeignKey("routines.id"), nullable=False),
    Column("log_date", Date, nullable=False),
    Column("checked", Boolean, nullable=False, default=False),
    UniqueConstraint("routine_id", "log_date", name="uq_routine_logs_routine_date"),
)


@st.cache_resource
def init_db():
    metadata.create_all(engine)
    return True


def today_korea():
    return datetime.now(APP_TIMEZONE).date()


def add_routine(name):
    clean_name = name.strip()
    if not clean_name:
        return

    with engine.begin() as conn:
        conn.execute(routines.insert().values(name=clean_name, active=True))


def get_active_routines():
    with engine.begin() as conn:
        rows = conn.execute(
            select(routines.c.id, routines.c.name)
            .where(routines.c.active.is_(True))
            .order_by(routines.c.id)
        ).mappings().all()
    return rows


def delete_routine(routine_id):
    with engine.begin() as conn:
        conn.execute(
            update(routines)
            .where(routines.c.id == routine_id)
            .values(active=False)
        )


def get_routine_logs(log_date):
    with engine.begin() as conn:
        rows = conn.execute(
            select(
                routines.c.id.label("routine_id"),
                routines.c.name.label("routine_name"),
                func.coalesce(routine_logs.c.checked, False).label("checked"),
            )
            .select_from(
                routines.outerjoin(
                    routine_logs,
                    (routines.c.id == routine_logs.c.routine_id)
                    & (routine_logs.c.log_date == log_date),
                )
            )
            .where(routines.c.active.is_(True))
            .order_by(routines.c.id)
        ).mappings().all()
    return rows


def update_check_status(routine_id, log_date, checked):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO routine_logs (routine_id, log_date, checked)
                VALUES (:routine_id, :log_date, :checked)
                ON CONFLICT (routine_id, log_date) DO UPDATE
                SET checked = EXCLUDED.checked
                """
            ),
            {
                "routine_id": routine_id,
                "log_date": log_date,
                "checked": checked,
            },
        )


def get_monthly_routine_summary(year, month):
    last_day = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    with engine.begin() as conn:
        total_routine_count = conn.execute(
            select(func.count())
            .select_from(routines)
            .where(routines.c.active.is_(True))
        ).scalar_one()

        rows = conn.execute(
            select(
                routine_logs.c.log_date,
                func.sum(func.cast(routine_logs.c.checked, Integer)).label("checked_count"),
            )
            .select_from(routine_logs.join(routines, routine_logs.c.routine_id == routines.c.id))
            .where(
                routine_logs.c.log_date.between(start_date, end_date),
                routines.c.active.is_(True),
            )
            .group_by(routine_logs.c.log_date)
        ).mappings().all()

    checked_by_date = {
        (row["log_date"].isoformat() if hasattr(row["log_date"], "isoformat") else str(row["log_date"])): int(row["checked_count"] or 0)
        for row in rows
    }

    today = today_korea()
    monthly_data = []

    for day in range(1, last_day + 1):
        current_date = date(year, month, day)
        current_date_text = current_date.isoformat()
        checked_count = checked_by_date.get(current_date_text, 0)
        rate = checked_count / total_routine_count if total_routine_count > 0 else 0

        monthly_data.append(
            {
                "day": day,
                "date": current_date_text,
                "checked_count": checked_count,
                "total_count": total_routine_count,
                "rate": rate,
                "is_future": current_date > today,
            }
        )

    return monthly_data


def render_today_view(log_date):
    st.subheader("루틴 추가")
    new_routine = st.text_input("추가할 루틴", placeholder="예: 5시 기상")

    if st.button("루틴 추가", type="primary"):
        add_routine(new_routine)
        st.rerun()

    st.divider()
    st.subheader("오늘의 루틴 체크")

    logs = get_routine_logs(log_date)

    if len(logs) == 0:
        st.write("아직 등록된 루틴이 없습니다.")
        return

    checked_count = 0
    total_count = len(logs)

    for log in logs:
        routine_id = log["routine_id"]
        routine_name = log["routine_name"]
        checked_value = bool(log["checked"])

        checked = st.checkbox(
            routine_name,
            value=checked_value,
            key=f"{log_date.isoformat()}_{routine_id}",
        )

        if checked:
            checked_count += 1

        if checked != checked_value:
            update_check_status(routine_id, log_date, checked)

    rate = checked_count / total_count if total_count > 0 else 0

    st.subheader("달성률")
    st.progress(rate)
    st.write(f"{checked_count}개 / {total_count}개 완료")
    st.write(f"달성률 {rate * 100:.0f}%")


def render_monthly_view(selected_date):
    st.subheader("월간 루틴 수행 현황")

    year = selected_date.year
    month = selected_date.month
    monthly_data = get_monthly_routine_summary(year, month)
    past_monthly_data = [data for data in monthly_data if not data["is_future"]]
    monthly_checked_total = sum(data["checked_count"] for data in past_monthly_data)
    monthly_possible_total = sum(data["total_count"] for data in past_monthly_data)
    monthly_rate = monthly_checked_total / monthly_possible_total if monthly_possible_total > 0 else 0

    st.write(f"{year}년 {month}월 전체 달성률")
    st.progress(monthly_rate)
    st.write(f"{monthly_checked_total}개 / {monthly_possible_total}개 완료")
    st.write(f"월간 달성률 {monthly_rate * 100:.0f}%")
    st.write("")

    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    monthly_dict = {data["day"]: data for data in monthly_data}
    month_calendar = calendar.monthcalendar(year, month)
    calendar_items = []

    for weekday in weekdays:
        calendar_items.append(f"<div class='calendar-header'>{weekday}</div>")

    for week in month_calendar:
        for day in week:
            if day == 0:
                calendar_items.append("<div class='calendar-cell empty'></div>")
                continue

            data = monthly_dict[day]
            day_rate = data["rate"]
            cell_class = "calendar-cell future" if data["is_future"] else "calendar-cell"

            if data["is_future"]:
                icon = "▫️"
                rate_text = "-"
            elif day_rate == 1:
                icon = "✅"
                rate_text = "100%"
            elif day_rate >= 0.5:
                icon = "🟡"
                rate_text = f"{day_rate * 100:.0f}%"
            elif day_rate > 0:
                icon = "🟠"
                rate_text = f"{day_rate * 100:.0f}%"
            else:
                icon = "⬜"
                rate_text = "0%"

            calendar_items.append(
                f"<div class='{cell_class}'>"
                f"<div class='calendar-icon'>{icon}</div>"
                f"<div class='calendar-day'>{day}일</div>"
                f"<div class='calendar-rate'>{rate_text}</div>"
                "</div>"
            )

    st.markdown(
        f"<div class='routine-calendar'>{''.join(calendar_items)}</div>",
        unsafe_allow_html=True,
    )

def render_manage_view():
    st.subheader("루틴 삭제")

    active_routines = get_active_routines()

    if len(active_routines) == 0:
        st.write("삭제할 루틴이 없습니다.")
        return

    routine_options = {routine["name"]: routine["id"] for routine in active_routines}
    selected_name = st.selectbox("삭제할 루틴 선택", list(routine_options.keys()))

    if st.button("선택한 루틴 삭제"):
        delete_routine(routine_options[selected_name])
        st.rerun()


st.set_page_config(page_title="루틴 체크", page_icon="✅", layout="centered")
st.markdown(
    """
    <style>
    .block-container {
        max-width: 760px;
        padding-top: 1.5rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }

    div.stButton > button {
        width: 100%;
        min-height: 2.75rem;
    }

    .routine-calendar {
        display: grid;
        grid-template-columns: repeat(7, minmax(0, 1fr));
        gap: 5px;
        width: 100%;
    }

    .calendar-header,
    .calendar-cell {
        min-width: 0;
        text-align: center;
    }

    .calendar-header {
        font-size: 0.86rem;
        font-weight: 700;
        color: #4b5563;
        padding: 0.25rem 0;
    }

    .calendar-cell {
        height: 62px;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        background: #ffffff;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        line-height: 1.15;
        overflow: hidden;
    }

    .calendar-cell.empty {
        border-color: transparent;
        background: transparent;
    }

    .calendar-cell.future {
        background: #f9fafb;
        color: #9ca3af;
    }

    .calendar-icon {
        font-size: 1.05rem;
        line-height: 1;
        margin-bottom: 0.16rem;
    }

    .calendar-day {
        font-size: 0.82rem;
        font-weight: 700;
        white-space: nowrap;
    }

    .calendar-rate {
        font-size: 0.78rem;
        color: #4b5563;
        white-space: nowrap;
    }

    @media (max-width: 640px) {
        .block-container {
            padding-top: 1rem;
            padding-left: 0.75rem;
            padding-right: 0.75rem;
        }

        h1 {
            font-size: 1.65rem !important;
        }

        h2, h3 {
            font-size: 1.08rem !important;
        }

        .routine-calendar {
            gap: 3px;
        }

        .calendar-header {
            font-size: 0.72rem;
        }

        .calendar-cell {
            height: 50px;
            border-radius: 6px;
        }

        .calendar-icon {
            font-size: 0.95rem;
            margin-bottom: 0.14rem;
        }

        .calendar-day {
            font-size: 0.68rem;
        }

        .calendar-rate {
            font-size: 0.64rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
init_db()

st.title("나의 루틴 체크 ✅")

with st.sidebar:
    st.subheader("저장 방식")
    if DATABASE_URL.startswith("sqlite"):
        st.info("현재는 이 노트북의 SQLite 파일에 저장됩니다. 여러 기기 연동은 DATABASE_URL 설정 후 가능합니다.")
    else:
        st.success("클라우드 DB에 저장 중입니다. 같은 앱 주소로 접속하면 기기 간 동기화됩니다.")

selected_date = st.date_input("날짜 선택", today_korea())
log_date = selected_date
st.caption(f"선택한 날짜: {log_date.isoformat()}")

view = st.radio(
    "화면",
    ["오늘", "월간", "관리"],
    horizontal=True,
    label_visibility="collapsed",
)

st.divider()

if view == "오늘":
    render_today_view(log_date)
elif view == "월간":
    render_monthly_view(selected_date)
else:
    render_manage_view()




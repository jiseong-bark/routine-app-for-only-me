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
    update,
)
from sqlalchemy.exc import IntegrityError


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


def create_log_if_not_exists(routine_id, log_date):
    with engine.begin() as conn:
        existing_id = conn.execute(
            select(routine_logs.c.id).where(
                routine_logs.c.routine_id == routine_id,
                routine_logs.c.log_date == log_date,
            )
        ).scalar_one_or_none()

        if existing_id is None:
            try:
                conn.execute(
                    routine_logs.insert().values(
                        routine_id=routine_id,
                        log_date=log_date,
                        checked=False,
                    )
                )
            except IntegrityError:
                pass


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
    create_log_if_not_exists(routine_id, log_date)

    with engine.begin() as conn:
        conn.execute(
            update(routine_logs)
            .where(
                routine_logs.c.routine_id == routine_id,
                routine_logs.c.log_date == log_date,
            )
            .values(checked=checked)
        )


def get_monthly_routine_summary(year, month):
    active_routines = get_active_routines()
    total_routine_count = len(active_routines)
    last_day = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    with engine.begin() as conn:
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
        row["log_date"].isoformat(): int(row["checked_count"] or 0)
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


st.set_page_config(page_title="루틴 체크", page_icon="✅", layout="centered")
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
st.divider()

st.subheader("루틴 추가")
new_routine = st.text_input("추가할 루틴", placeholder="예: 5시 기상")

if st.button("루틴 추가", type="primary"):
    add_routine(new_routine)
    st.rerun()

st.divider()
st.subheader("오늘의 루틴 체크")

active_routines = get_active_routines()

if len(active_routines) == 0:
    st.write("아직 등록된 루틴이 없습니다.")
else:
    for routine in active_routines:
        create_log_if_not_exists(routine["id"], log_date)

    logs = get_routine_logs(log_date)
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
            st.rerun()

    rate = checked_count / total_count if total_count > 0 else 0

    st.subheader("달성률")
    st.progress(rate)
    st.write(f"{checked_count}개 / {total_count}개 완료")
    st.write(f"달성률 {rate * 100:.0f}%")

st.divider()
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
header_cols = st.columns(7)

for i, weekday in enumerate(weekdays):
    header_cols[i].markdown(f"**{weekday}**")

monthly_dict = {data["day"]: data for data in monthly_data}
month_calendar = calendar.monthcalendar(year, month)

for week in month_calendar:
    cols = st.columns(7)

    for i, day in enumerate(week):
        if day == 0:
            cols[i].write("")
            continue

        data = monthly_dict[day]
        day_rate = data["rate"]

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

        cols[i].markdown(
            f"""
            <div style='text-align:center; border:1px solid #ddd; border-radius:8px; padding:6px; margin:2px;'>
                <div>{icon}</div>
                <div>{day}일</div>
                <div>{rate_text}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()
st.subheader("루틴 삭제")

active_routines = get_active_routines()

if len(active_routines) > 0:
    routine_options = {routine["name"]: routine["id"] for routine in active_routines}
    selected_name = st.selectbox("삭제할 루틴 선택", list(routine_options.keys()))

    if st.button("선택한 루틴 삭제"):
        delete_routine(routine_options[selected_name])
        st.rerun()
else:
    st.write("삭제할 루틴이 없습니다.")



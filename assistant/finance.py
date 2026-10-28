"""Read-only financial answers computed from the same ledger as the Finance page."""

import calendar
import re
from datetime import date, timedelta

from django.db.models import Count, Min, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from finances.models import Payment
from schedule.models import Lesson
from students.models import Student


FINANCE_INTENT = re.compile(
    r"заработ|начисл|доход|выруч|получил|получено|поступ|оплат|оплач|плат[её]ж|"
    r"внес[её]|взнос|баланс|долг|аванс|остаток средств|сколько.*(?:рубл|₽)|"
    r"стоимост[ьи]|сколько стоит|цен[ауые] занятия|ставк[ауые]|денег",
    re.I,
)
FINANCE_REQUEST = re.compile(r"\b(?:сколько|каков\w*|какая|какой|кто|посчитай|покажи|сравни|сумма|отч[её]т)\b", re.I)
APP_CONTEXT = re.compile(r"ученик|заняти|урок|репетит|препода|\bя\b|\bмне\b|\bмой\b|\bмои\b|\bу меня\b", re.I)
PERIOD_CONTEXT = re.compile(r"\bза\s+(?:прошл|этот|текущ|\d|январ|феврал|март|апрел|ма[йяею]|июн|июл|август|сентябр|октябр|ноябр|декабр)|\bв\s+(?:этом месяце|январ|феврал|март|апрел|ма[йяею]|июн|июл|август|сентябр|октябр|ноябр|декабр)|\bс\s+\d|\bза неделю\b", re.I)
DATE_IN_TEXT = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{4})\b")
MONTH_PATTERN = r"январ\w*|феврал\w*|март\w*|апрел\w*|ма[йяею]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*"
MONTH_IN_TEXT = re.compile(rf"\b(?:{MONTH_PATTERN})\b", re.I)
MONTH_STEMS = ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")


def is_finance_question(question: str, has_student: bool = False) -> bool:
    if not FINANCE_INTENT.search(question) or not FINANCE_REQUEST.search(question):
        return False
    return bool(has_student or APP_CONTEXT.search(question) or PERIOD_CONTEXT.search(question)
                or (re.search(r"\b(?:кто|у кого)\b", question, re.I) and re.search(r"долг|баланс", question, re.I)))


def month_number(word: str) -> int:
    return next(index for index, stem in enumerate(MONTH_STEMS, 1) if word.casefold().startswith(stem))


def parsed_date(value: str) -> date:
    if "-" in value:
        return date.fromisoformat(value)
    day, month, year = re.split(r"[./]", value)
    return date(int(year), int(month), int(day))


def period_for(question: str, mode: str = "auto", start_text: str = "", end_text: str = "") -> tuple[date, date, str]:
    today = timezone.localdate()
    start = end = None
    if mode == "auto":
        dates = DATE_IN_TEXT.findall(question)
        if dates:
            try:
                start, end = parsed_date(dates[0]), parsed_date(dates[1]) if len(dates) > 1 else parsed_date(dates[0])
            except ValueError:
                raise ValueError("В вопросе указана некорректная дата") from None
            mode = "custom"
        else:
            different_months = re.search(rf"\bс\s+(\d{{1,2}})\s+({MONTH_PATTERN})\s+по\s+(\d{{1,2}})\s+({MONTH_PATTERN})(?:\s+(20\d{{2}}))?", question, re.I)
            same_month = re.search(rf"\bс\s+(\d{{1,2}})\s+по\s+(\d{{1,2}})\s+({MONTH_PATTERN})(?:\s+(20\d{{2}}))?", question, re.I)
            months = MONTH_IN_TEXT.findall(question)
            year_match = re.search(r"\b(20\d{2})\b", question)
            year = int(year_match.group(1)) if year_match else today.year
            if different_months:
                start_month, end_month = month_number(different_months.group(2)), month_number(different_months.group(4))
                year = int(different_months.group(5)) if different_months.group(5) else year
                try:
                    start = date(year - (start_month > end_month), start_month, int(different_months.group(1)))
                    end = date(year, end_month, int(different_months.group(3)))
                except ValueError:
                    raise ValueError("В вопросе указан некорректный период") from None
                mode = "custom"
            elif same_month:
                month = month_number(same_month.group(3))
                year = int(same_month.group(4)) if same_month.group(4) else year
                try:
                    start, end = date(year, month, int(same_month.group(1))), date(year, month, int(same_month.group(2)))
                except ValueError:
                    raise ValueError("В вопросе указан некорректный период") from None
                mode = "custom"
            elif months:
                month = month_number(months[0])
                start = date(year, month, 1)
                end_month = month_number(months[1]) if len(months) > 1 and " по " in question.casefold() else month
                end = date(year, end_month, calendar.monthrange(year, end_month)[1])
                mode = "custom"
            elif re.search(r"\b(?:весь|всё|все)\s+время\b|\bза\s+всё\s+время\b", question, re.I):
                first_lesson = Lesson.objects.aggregate(earliest=Min("date"))["earliest"]
                first_payment = Payment.objects.aggregate(earliest=Min("paid_on"))["earliest"]
                start = min([day for day in (first_lesson, first_payment, today) if day])
                end = today
                mode = "all_time"
            elif re.search(r"\bсегодня\b", question, re.I):
                start = end = today
                mode = "custom"
            elif re.search(r"\bвчера\b", question, re.I):
                start = end = today - timedelta(days=1)
                mode = "custom"
            elif days := re.search(r"последн\w*\s+(\d{1,3})\s+дн", question, re.I):
                if int(days.group(1)) < 1:
                    raise ValueError("Количество дней должно быть больше нуля")
                end = today
                start = today - timedelta(days=int(days.group(1)) - 1)
                mode = "custom"
            elif year_match:
                start, end = date(year, 1, 1), date(year, 12, 31)
                mode = "custom"
            elif re.search(r"прошл\w*\s+недел|предыдущ\w*\s+недел", question, re.I):
                mode = "previous_week"
            elif re.search(r"прошл\w*\s+год|предыдущ\w*\s+год", question, re.I):
                mode = "previous_year"
            elif re.search(r"прошл\w*\s+месяц|предыдущ\w*\s+месяц", question, re.I):
                mode = "previous_month"
            elif re.search(r"недел", question, re.I):
                mode = "week"
            elif re.search(r"(?:этом|текущем|этот)\s+году|за\s+год|с начала года", question, re.I):
                mode = "year"
            else:
                mode = "month"
    if mode == "custom":
        if start is None or end is None:
            try:
                start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
            except (TypeError, ValueError):
                raise ValueError("Укажите корректные даты периода") from None
        if end < start or end - start > timedelta(days=3650):
            raise ValueError("Период должен быть не длиннее 10 лет, конец не раньше начала")
    elif mode == "all_time":
        pass
    elif mode == "month":
        start = today.replace(day=1)
        end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    elif mode == "previous_month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif mode == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif mode == "previous_week":
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
    elif mode == "year":
        start, end = today.replace(month=1, day=1), today.replace(month=12, day=31)
    elif mode == "previous_year":
        start, end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    else:
        raise ValueError("Некорректный период")
    return start, end, mode


def report(start: date, end: date, selected: list[Student] | None) -> dict:
    students = selected if selected is not None else list(Student.objects.order_by("name"))
    ids = [item.id for item in students]
    completed = Lesson.objects.filter(student_id__in=ids, status="completed")
    payments = Payment.objects.filter(student_id__in=ids)
    charges = completed.filter(date__range=(start, end)).values("student_id").annotate(
        total=Sum(Coalesce("charged_price_rub", "student__price_rub")), count=Count("id"))
    receipts = payments.filter(paid_on__range=(start, end)).values("student_id").annotate(
        total=Sum("amount_rub"), count=Count("id"))
    all_charges = completed.values("student_id").annotate(total=Sum(Coalesce("charged_price_rub", "student__price_rub")))
    all_receipts = payments.values("student_id").annotate(total=Sum("amount_rub"))
    by_charge = {row["student_id"]: row for row in charges}
    by_receipt = {row["student_id"]: row for row in receipts}
    lifetime_charges = {row["student_id"]: row["total"] or 0 for row in all_charges}
    lifetime_receipts = {row["student_id"]: row["total"] or 0 for row in all_receipts}
    rows = []
    for item in students:
        charged = by_charge.get(item.id, {})
        received = by_receipt.get(item.id, {})
        rows.append({
            "name": item.name, "grade": item.grade,
            "price_rub": item.price_rub,
            "earned_rub": charged.get("total") or 0,
            "completed_count": charged.get("count") or 0,
            "received_rub": received.get("total") or 0,
            "payment_count": received.get("count") or 0,
            "balance_rub": item.opening_balance_rub + lifetime_receipts.get(item.id, 0) - lifetime_charges.get(item.id, 0),
        })
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "scope": "student" if selected and len(selected) == 1 else "selected" if selected else "all",
        "students": rows,
        "earned_rub": sum(row["earned_rub"] for row in rows),
        "received_rub": sum(row["received_rub"] for row in rows),
        "completed_count": sum(row["completed_count"] for row in rows),
        "payment_count": sum(row["payment_count"] for row in rows),
        "balance_rub": sum(row["balance_rub"] for row in rows),
    }


def answer(question: str, data: dict) -> str:
    scope = f"Ученик «{data['students'][0]['name']}»" if data["scope"] == "student" and data["students"] else "Указанные ученики" if data["scope"] == "selected" else "Все ученики"
    dates = f"с {date.fromisoformat(data['start']):%d.%m.%Y} по {date.fromisoformat(data['end']):%d.%m.%Y}"
    earned = f"{data['earned_rub']:,}".replace(",", " ")
    received = f"{data['received_rub']:,}".replace(",", " ")
    balance = f"{data['balance_rub']:,}".replace(",", " ")
    lowered = question.lower()
    def word(count, one, few, many):
        return one if count % 10 == 1 and count % 100 != 11 else few if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14 else many

    if re.search(r"сколько стоит|стоимост|цен[ауые] занятия|ставк[ауые]", lowered):
        if data["scope"] != "student":
            return "Текущая стоимость занятия по ученикам:\n" + "\n".join(f"{row['name']}: {row['price_rub']:,} ₽".replace(",", " ") for row in data["students"])
        return f"{scope}: текущая стоимость занятия {data['students'][0]['price_rub']:,} ₽.".replace(",", " ")
    if re.search(r"баланс|долг|аванс|остаток средств", lowered):
        if re.search(r"\bу кого\b|\bкто\b", lowered):
            debtors = [row for row in data["students"] if row["balance_rub"] < 0]
            return "Ученики с долгом: " + (", ".join(f"{row['name']} ({row['balance_rub']:,} ₽)".replace(",", " ") for row in debtors) if debtors else "нет") + "."
        return f"{scope}: текущий баланс {balance} ₽. Он учитывает начальный остаток, все внесения и все проведённые занятия за всё время, а не только период {dates}."
    if re.search(r"получил|получено|поступ|оплат|оплач|плат[её]ж|внес[её]|взнос", lowered) and not re.search(r"заработ|начисл|доход|выруч", lowered):
        result = f"{scope}: за период {dates} получено {received} ₽ ({data['payment_count']} {word(data['payment_count'], 'внесение', 'внесения', 'внесений')}). Начальный остаток сюда не входит. За проведённые занятия начислено {earned} ₽."
    else:
        result = f"{scope}: за период {dates} начислено {earned} ₽ за {data['completed_count']} {word(data['completed_count'], 'проведённое занятие', 'проведённых занятия', 'проведённых занятий')}. Фактически внесено за этот период {received} ₽ ({data['payment_count']} {word(data['payment_count'], 'внесение', 'внесения', 'внесений')})."
    if data["scope"] == "selected":
        result += "\n" + "\n".join(f"{row['name']}: начислено {row['earned_rub']:,} ₽, получено {row['received_rub']:,} ₽".replace(",", " ") for row in data["students"])
    return result

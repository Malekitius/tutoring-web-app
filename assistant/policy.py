"""The assistant never receives finance records or money-related free text."""

import re


MONEY_TERMS = re.compile(r"ден[еь]г|финанс|оплат|оплач|плат[её]ж|платил|платила|рубл|стоимост|цен[аыуе]|долг|баланс|аванс|выруч|заработ|тариф|₽", re.I)


def teaching_text(value: str) -> str:
    if MONEY_TERMS.search(value or ""):
        return "[финансовые сведения скрыты]"
    return value or ""

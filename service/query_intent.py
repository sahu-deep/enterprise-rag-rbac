import re


def is_employee_count_by_department_question(query: str) -> bool:
    normalized_query = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
    return bool(
        re.search(
            r"\b(each|every|all)\s+(department|team)\b|"
            r"\b(by|per)\s+(department|team)\b|"
            r"\bdepartment\s+wise\b|"
            r"\b(breakdown|break down)\b",
            normalized_query,
        )
    ) and bool(re.search(r"\b(employee|employees|staff|workforce|people|headcount)\b", normalized_query))


def is_employee_count_question(query: str) -> bool:
    normalized_query = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
    mentions_people = re.search(
        r"\b(employee|employees|staff|workforce|people|headcount)\b",
        normalized_query,
    )
    asks_for_count = re.search(
        r"\b(how many|number of|count|total|headcount)\b",
        normalized_query,
    )
    asks_for_department_count_without_noun = re.search(
        r"\bhow many\s+(?:are there\s+)?(?:in|within|for)\s+.+\s+(?:department|team)\b",
        normalized_query,
    )
    return (
        bool(mentions_people and asks_for_count)
        or bool(asks_for_department_count_without_noun)
        or is_employee_count_by_department_question(query)
    )

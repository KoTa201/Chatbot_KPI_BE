import math


def validate_page(page: int) -> int:
    if not isinstance(page, int):
        raise ValueError(f"page harus berupa integer. Diterima: {type(page).__name__}")
    if page < 1:
        raise ValueError("'page' tidak boleh negatif dan minimal 1.")
    return page


def validate_limit(limit: int, *, max_limit: int = 100, clamp: bool = False) -> int:
    if not isinstance(limit, int):
        raise ValueError(f"limit harus berupa integer. Diterima: {type(limit).__name__}")
    if limit < 1:
        raise ValueError("'limit' harus antara 1 dan 100.")
    if limit > max_limit:
        if clamp:
            return max_limit
        raise ValueError(f"'limit' harus antara 1 dan {max_limit}.")
    return limit


def calculate_total_pages(total: int, limit: int, *, minimum: int = 0) -> int:
    if total <= 0:
        return minimum
    return math.ceil(total / limit)

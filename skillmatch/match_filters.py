"""Optional display-percentage filtering after the full corpus has been ranked."""

from urllib.parse import urlencode

MIN_MATCH_OPTIONS = (
    ("", "Any match"),
    ("30", "30%+"),
    ("50", "50%+"),
    ("70", "70%+"),
    ("80", "80%+"),
    ("90", "90%+"),
)


def minimum_match_results(request, ranked):
    raw = request.GET.get("min_match", "")
    minimum = raw if raw in dict(MIN_MATCH_OPTIONS) else ""
    filtered = (
        [match for match in ranked if match.similarity_percent >= int(minimum)]
        if minimum
        else ranked
    )
    search = {"q": request.GET["q"]} if "q" in request.GET else {}
    clear_query = urlencode(search)
    pagination_query = urlencode({**search, **({"min_match": minimum} if minimum else {})})
    return filtered, {
        "min_match": minimum,
        "min_match_options": MIN_MATCH_OPTIONS,
        "filter_excludes_all": bool(ranked) and not filtered,
        "clear_match_url": request.path + ("?" + clear_query if clear_query else ""),
        "match_pagination_query": pagination_query,
    }

"""Share one bounded source window between drafting and verification."""


def window(source, limit=3000):
    text = source.get('text', '')
    if len(text) <= limit:
        return text
    span = source.get('evidence_span')
    if (isinstance(span, (list, tuple)) and len(span) == 2
            and all(type(n) is int for n in span)
            and 0 <= span[0] < span[1] <= len(text) and span[1] - span[0] <= limit):
        start = max(0, min(span[0] - 300, len(text) - limit))
        return text[start:start + limit]
    return text[:limit]

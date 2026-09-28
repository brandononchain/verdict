"""Bounded Markdown units shared by drafting and Jev verification.

Code fences and section headings are checked with their explanatory prose.
The renderer remains a separate, non-executing presentation layer.
"""
import re


def units(answer):
    pieces, current, fenced = [], [], False
    for line in answer.replace('\r\n', '\n').split('\n'):
        if line.startswith('```'):
            fenced = not fenced
        if not line.strip() and not fenced and current:
            pieces.append('\n'.join(current).strip()); current = []
        else:
            current.append(line)
    if fenced:
        raise ValueError('Unclosed code block')
    if current and '\n'.join(current).strip():
        pieces.append('\n'.join(current).strip())
    result, pending_heading = [], ''
    for part in pieces:
        if re.fullmatch(r'#{1,4}\s+[^\n]+', part):
            pending_heading += part + '\n'
        elif part.startswith('```'):
            if not result or pending_heading:
                raise ValueError('A code block needs preceding cited explanation')
            result[-1] += '\n\n' + part
        else:
            result.append(pending_heading + part)
            pending_heading = ''
    if pending_heading:
        raise ValueError('A heading needs content')
    if not result or len(result) > 4:
        raise ValueError('Answer has too many sections')
    return result

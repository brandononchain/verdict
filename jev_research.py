"""Jev-only research judgment. Jev chooses evidence; code presents exact excerpts.

No text-generating model is called. Source text is never treated as instructions.
"""
import json
import math
import os
import re
from urllib.parse import urlsplit
import urllib.request

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
MAX_RESPONSE_BYTES = 200_000
MAX_STATE_BYTES = 80_000

class JevError(Exception):
    pass


def passage(query, text):
    """Deterministic bounded extract from retrieved content, not authored prose."""
    terms = set(re.findall(r'\w+', query.lower()))
    segments = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if s.strip()]
    if not segments:
        return ''
    segments.sort(key=lambda s: (-len(terms.intersection(re.findall(r'\w+', s.lower()))), len(s)))
    return segments[0][:180].strip()


def state_and_questions(query, sources):
    candidates = []
    for source in sources[:8]:
        excerpt = passage(query, source.get('text', ''))
        if excerpt:
            candidates.append({'id': str(source['n']), 'title': source.get('title', '')[:180],
                'domain': source.get('domain', 'private'), 'passage': excerpt,
                'provenance': 'private note' if source.get('note_id') else 'web page'})
    if not candidates:
        raise JevError('No readable evidence was found')
    state = {'user_question': query, 'candidates': candidates}
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_STATE_BYTES:
        raise JevError('Evidence exceeded the Jev input limit')
    criteria = {candidate['id']: candidate['title'] + ' — ' + candidate['passage'][:100] for candidate in candidates}
    criteria['none'] = 'None of these passages directly addresses the question.'
    questions = {
        'best_passage': {'type': 'choice', 'instructions':
            'Which `candidates` passage most directly answers `user_question`? Choose none if none directly answers it.',
            'criteria': criteria},
        'sufficient': {'type': 'noul', 'instructions':
            'Does at least one `candidates` passage contain enough explicit information to answer `user_question` without outside knowledge?'},
        'conflict': {'type': 'noul', 'instructions':
            'Do the `candidates` passages explicitly disagree on a fact needed to answer `user_question`?'}
    }
    return state, questions, candidates


def call(state, questions):
    key = os.environ['TYPESAFE_API_KEY']
    payload = json.dumps({'model': os.environ.get('JEV_MODEL', 'jev-latest'),
        'state': state, 'questions': questions}).encode()
    request = urllib.request.Request(ENDPOINT, data=payload, method='POST', headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'User-Agent': 'Zearch/1.0'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise JevError('Jev response exceeded its limit')
            return json.loads(raw)
    except (OSError, ValueError) as exc:
        raise JevError('The Jev service could not complete this judgment') from exc


def judge(query, sources):
    state, questions, candidates = state_and_questions(query, sources)
    raw = call(state, questions)
    if not isinstance(raw, dict) or not isinstance(raw.get('answers'), dict):
        raise JevError('Jev returned an invalid decision')
    answers = raw['answers']
    choice = answers.get('best_passage', {}).get('choice')
    allowed = {c['id'] for c in candidates} | {'none'}
    if choice not in allowed:
        raise JevError('Jev selected an unknown passage')
    probs = answers['best_passage'].get('probabilities') or {}
    values = [answers.get(k, {}).get('noul') for k in ('sufficient', 'conflict')]
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise JevError('Jev returned an invalid judgment')
    sufficient, conflict = values
    selected_probability = probs.get(choice, 0)
    if type(selected_probability) not in (int, float) or not math.isfinite(selected_probability) or not 0 <= selected_probability <= 1:
        raise JevError('Jev returned an invalid choice probability')
    selected = next((c for c in candidates if c['id'] == choice), None)
    can_answer = selected is not None and sufficient >= .65 and selected_probability >= .45
    judgment = {'selected': int(choice) if selected else None,
        'selected_probability': round(selected_probability, 4),
        'sufficiency_probability': round(sufficient, 4),
        'conflict_probability': round(conflict, 4),
        'gate': 'answer' if can_answer and conflict < .65 else 'review' if can_answer else 'abstain',
        'model': raw.get('model', os.environ.get('JEV_MODEL', 'jev-latest'))}
    return judgment, selected, raw.get('usage') or {}, candidates


def format_answer(judgment, selected, candidates, sources):
    gate = judgment['gate']
    if gate == 'abstain':
        return 'I could not find a passage that clearly answers this question. Open the sources below, or try a more specific question.'
    cite = '[' + str(judgment['selected']) + ']'
    label = 'Your note' if next(s for s in sources if s['n'] == judgment['selected']).get('note_id') else 'The selected source'
    answer = f'{label} says: “{selected["passage"]}” {cite}'
    if gate == 'review':
        answer += '\n\nThe retrieved passages may disagree. Review the cited source and the other evidence before relying on this excerpt.'
    else:
        answer += '\n\nThis is an excerpt selected by Jev, not a generated synthesis. Open the citation for full context.'
    return answer

"""Provider abstraction: URL policy, credentials, readiness, malformed output, fallback and embedding cache."""
import json
import httpx
import pytest
from sqlalchemy import select
from app import ai
from app.ai import AIUnavailable, AIOutputInvalid
from app.db import EmbeddingCache
from app.schemas import Extraction

GOOD = {'requirements': [], 'complete': True, 'academic_scope_explicit': False, 'opportunity_type': 'internship', 'metadata_evidence': {}}
TAGS = {'models': [{'name': 'qwen3.5:9b', 'digest': 'aaaaaaaaaaaaaaaa'}, {'name': 'qwen3-embedding:0.6b', 'digest': 'bbbbbbbbbbbbbbbb'}]}

@pytest.fixture
def ollama(monkeypatch):
    """Route httpx to a fake Ollama; returns the list of recorded requests and a mutable state dict."""
    calls, state = [], {'chat': [json.dumps(GOOD)], 'tags': TAGS, 'down': False}
    def handler(request):
        calls.append(request)
        if state['down']: raise httpx.ConnectError('refused')
        if request.url.path == '/api/tags': return httpx.Response(200, json=state['tags'])
        body = json.loads(request.content)
        if request.url.path == '/api/chat':
            if body['model'] not in {m['name'] for m in state['tags']['models']}: return httpx.Response(404, json={'error': f"model '{body['model']}' not found"})
            return httpx.Response(200, json={'message': {'content': state['chat'].pop(0)}, 'done_reason': 'stop'})
        if request.url.path == '/api/embed': return httpx.Response(200, json={'embeddings': [[float(len(t)), 1.0] for t in body['input']]})
        return httpx.Response(404)
    real = httpx.Client
    monkeypatch.setattr(ai.httpx, 'Client', lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **{x: y for x, y in k.items() if x != 'transport'}))
    monkeypatch.setattr(ai.settings, 'ai_provider', 'ollama')
    monkeypatch.setattr(ai.settings, 'ollama_base_url', 'http://127.0.0.1:11434')
    monkeypatch.setattr(ai.settings, 'ollama_model', 'qwen3.5:9b')
    monkeypatch.setattr(ai.settings, 'ollama_embedding_model', 'qwen3-embedding:0.6b')
    monkeypatch.setattr(ai.settings, 'ai_allow_hosted_fallback', False)
    ai._status_cache.clear()
    return calls, state

@pytest.mark.parametrize('url,ok', [('http://127.0.0.1:11434', True), ('http://localhost:11434', True), ('http://[::1]:11434', True),
                                    ('https://ollama.internal.example', True), ('http://10.0.0.5:11434', False), ('http://ollama.example.com', False),
                                    ('ftp://127.0.0.1', False), ('http://user:pw@127.0.0.1:11434', False)])
def test_local_url_policy(url, ok):
    if ok: assert ai.validate_local_url(url)
    else:
        with pytest.raises(AIUnavailable): ai.validate_local_url(url)

def test_explicit_private_http_host_allowed(monkeypatch):
    monkeypatch.setattr(ai.settings, 'ollama_allowed_http_hosts', 'ollama')
    assert ai.validate_local_url('http://ollama:11434')

def test_hosted_requires_https_and_key(monkeypatch):
    monkeypatch.setattr(ai.settings, 'ai_api_key', '')
    with pytest.raises(AIUnavailable, match='AI_API_KEY'): ai.OpenAIProvider()
    monkeypatch.setattr(ai.settings, 'ai_api_key', 'test-key-not-real')
    monkeypatch.setattr(ai.settings, 'ai_base_url', 'http://api.example.com/v1')
    with pytest.raises(AIUnavailable, match='HTTPS'): ai.OpenAIProvider()

def test_disabled_provider_never_fabricates(monkeypatch):
    monkeypatch.setattr(ai.settings, 'ai_provider', 'disabled')
    with pytest.raises(AIUnavailable, match='disabled'): ai.structured('Python is required.', Extraction, '')

def test_ollama_native_structured_request_without_api_key(ollama, monkeypatch):
    calls, _ = ollama
    monkeypatch.setattr(ai.settings, 'ai_api_key', '')
    result, provenance = ai.structured('Python is required.', Extraction, 'x')
    chat = [c for c in calls if c.url.path == '/api/chat'][0]
    body = json.loads(chat.content)
    assert 'authorization' not in chat.headers
    assert body['stream'] is False and body['think'] is False and body['format']['type'] == 'object' and body['options']['temperature'] == 0
    assert 'untrusted_document' in body['messages'][1]['content']
    assert provenance['provider'] == 'ollama' and provenance['model'] == 'ollama:qwen3.5:9b@aaaaaaaaaaaa' and result.complete

def test_malformed_output_retried_once_then_rejected(ollama):
    _, state = ollama
    state['chat'] = ['{not json', json.dumps(GOOD)]
    assert ai.structured('Python is required.', Extraction, 'x')[0].complete
    state['chat'] = ['{"requirements": "nope"}', '[]']
    with pytest.raises(AIOutputInvalid): ai.structured('Python is required.', Extraction, 'x')

def test_missing_model_gives_pull_instruction(ollama, monkeypatch):
    monkeypatch.setattr(ai.settings, 'ollama_model', 'not-installed:1b')
    with pytest.raises(AIUnavailable, match='ollama pull not-installed:1b'): ai.structured('x', Extraction, 'x')
    status = ai.ai_status()
    assert status['ready'] is False and 'ollama pull not-installed:1b' in status['error']

def test_unreachable_runtime_reported(ollama):
    _, state = ollama; state['down'] = True
    with pytest.raises(AIUnavailable, match='not reachable'): ai.structured('x', Extraction, 'x')
    assert ai.ai_status()['ready'] is False

def test_ready_status(ollama):
    s = ai.ai_status()
    assert s['ready'] and s['llm_ready'] and s['embedding_ready'] and s['fallback'] is None

def test_hosted_fallback_only_when_explicitly_enabled(ollama, monkeypatch):
    _, state = ollama; state['down'] = True
    monkeypatch.setattr(ai.settings, 'ai_fallback_provider', 'openai')
    monkeypatch.setattr(ai.settings, 'ai_api_key', 'test-key-not-real')
    monkeypatch.setattr(ai.settings, 'ai_base_url', 'https://api.example.com/v1')
    used = []
    monkeypatch.setattr(ai.OpenAIProvider, 'chat_json', lambda self, *a: used.append('hosted') or json.dumps(GOOD))
    with pytest.raises(AIUnavailable): ai.structured('x', Extraction, 'x')
    assert used == []
    monkeypatch.setattr(ai.settings, 'ai_allow_hosted_fallback', True)
    _, provenance = ai.structured('x', Extraction, 'x')
    assert used == ['hosted'] and provenance['provider'] == 'openai' and provenance['hosted'] is True

def test_oversized_document_not_truncated(ollama):
    with pytest.raises(ValueError, match='cannot safely truncate'): ai.structured('x' * 100_001, Extraction, 'x')

def test_embedding_cache_versioned_by_model_digest(ollama, db):
    calls, state = ollama
    v1, key1 = ai.embeddings(['alpha', 'beta'], db); db.commit()
    embeds = lambda: sum(1 for c in calls if c.url.path == '/api/embed')
    assert embeds() == 1 and key1.endswith('@bbbbbbbbbbbb')
    v2, _ = ai.embeddings(['alpha', 'beta'], db)
    assert v2 == v1 and embeds() == 1
    state['tags'] = {'models': [TAGS['models'][0], {'name': 'qwen3-embedding:0.6b', 'digest': 'cccccccccccccccc'}]}
    _, key3 = ai.embeddings(['alpha'], db); db.commit()
    assert embeds() == 2 and key3 != key1
    assert {r.model_key for r in db.scalars(select(EmbeddingCache))} == {key1, key3}

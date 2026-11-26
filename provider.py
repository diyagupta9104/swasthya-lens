"""Small OpenAI Responses and embeddings adapter with sanitized errors."""
import requests
import config


class ProviderError(Exception):
    pass


def post(endpoint: str, payload: dict) -> dict:
    try:
        response = requests.post('https://api.openai.com/v1/' + endpoint,
            headers={'Authorization': 'Bearer ' + config.api_key(), 'Content-Type': 'application/json'},
            json=payload, timeout=(10, 55))
    except requests.RequestException as exc:
        raise ProviderError('OpenAI connection unavailable') from exc
    if not response.ok:
        labels = {401: 'OpenAI key was rejected', 429: 'OpenAI quota or rate limit reached', 403: 'OpenAI access denied'}
        raise ProviderError(labels.get(response.status_code, f'OpenAI request failed (HTTP {response.status_code})'))
    return response.json()


def respond(instructions: str, items: list, tools: list, allow_tools: bool = True, require_tool: bool = False) -> dict:
    payload = {'model': config.MODEL, 'instructions': instructions, 'input': items,
               'store': False, 'max_output_tokens': 1100}
    if config.MODEL.startswith('gpt-4'):
        payload['temperature'] = 0.2
    if allow_tools:
        payload.update(tools=tools, parallel_tool_calls=True, tool_choice='required' if require_tool else 'auto')
    return post('responses', payload)


def output_text(response: dict) -> str:
    return '\n'.join(part.get('text', '') for item in response.get('output', [])
        if item.get('type') == 'message' for part in item.get('content', []) if part.get('type') == 'output_text')


def embed(texts: list[str]) -> list[list[float]]:
    result = post('embeddings', {'model': config.EMBEDDING_MODEL, 'input': texts})
    return [item['embedding'] for item in sorted(result['data'], key=lambda item: item['index'])]

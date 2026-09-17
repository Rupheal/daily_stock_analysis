"""Prospective provider configuration through frozen DSA's native YAML loader.

No prompt, response, score, max-token or upstream source rewriting. JSON is a
YAML subset. The credential is an environment reference, never a file value.
"""
import json

VERSION = 'O_DEEPSEEK_FLASH_NONTHINKING_v1'


def configure(root, version):
    if version != VERSION:
        raise ValueError('UNRECOGNIZED_NATIVE_CONFIGURATION')
    path = root / 'native-model-config.json'
    value = {'model_list': [{'model_name': 'openai/deepseek-flash',
        'litellm_params': {'model': 'openai/deepseek-flash',
            'api_base': 'https://api.deepseek.com',
            'api_key': 'os.environ/LLM_DEEPSEEK_API_KEY',
            'extra_body': {'thinking': {'type': 'disabled'}}}}]}
    with path.open('x') as handle:
        json.dump(value, handle, indent=2)
    return {'LITELLM_CONFIG': str(path.resolve()), 'DSA_EXPECT_THINKING': 'disabled'}

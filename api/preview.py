import io
import os
from urllib.parse import parse_qs, urlparse

from PIL import Image

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# This file is intentionally lightweight and just serves the preview route for Vercel.
# The actual conversion state is kept in the main api/index.py entrypoint for compatibility.


def handler(request, response):
    parsed = urlparse(request.url)
    query = parse_qs(parsed.query)
    factor_value = query.get('factor', ['4'])[0]

    try:
        factor = int(factor_value)
        if factor < 2 or factor > 50:
            raise ValueError
    except ValueError:
        response.status = 400
        response.text = 'Factor must be an integer between 2 and 50.'
        return response

    response.status = 200
    response.headers['Content-Type'] = 'image/png'
    response.body = b''
    return response

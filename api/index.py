import io
import os
import re
from urllib.parse import parse_qs, urlparse

from PIL import Image

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(WORKSPACE_DIR, 'assets')
FRONTEND_DIR = os.path.join(WORKSPACE_DIR, 'frontend')

# In-memory state for Vercel serverless runtime
# This is ephemeral per instance and not guaranteed across requests.
LAST_QUANTIZED_IMAGE = None


def _downscale_image(image, scale_factor):
    width, height = image.size
    new_width = max(1, int(width / scale_factor))
    new_height = max(1, int(height / scale_factor))
    if new_width == width and new_height == height:
        return image.copy()
    return image.resize((new_width, new_height), resample=Image.Resampling.BOX)


def _reduce_color_palette(image, palette_size=100):
    if image.mode != 'RGB':
        image = image.convert('RGB')
    max_colors = max(2, min(int(palette_size), 256))
    quantized = image.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    return quantized.convert('RGB')


def _pixel_art_pipeline_from_quantized(image, downsample_factor=4, upscale_factor=None):
    if upscale_factor is None:
        upscale_factor = downsample_factor

    width, height = image.size
    if downsample_factor <= 1:
        return image.copy()

    target_width = max(1, int(width / downsample_factor))
    target_height = max(1, int(height / downsample_factor))
    downsampled = image.resize((target_width, target_height), resample=Image.Resampling.BOX)
    if upscale_factor != 1:
        return downsampled.resize((width, height), resample=Image.Resampling.NEAREST)
    return downsampled


def _parse_multipart(raw_body, content_type):
    boundary = None
    match = re.search(r'boundary=(.*)', content_type)
    if match:
        boundary = match.group(1).strip('"')
    if not boundary:
        return {}

    boundary_bytes = b'--' + boundary.encode('utf-8')
    fields = {}
    for part in raw_body.split(boundary_bytes):
        if not part or part in (b'--\r\n', b'--\n', b'--'):
            continue

        chunk = part.strip(b'\r\n')
        if not chunk or chunk.startswith(b'--'):
            continue

        header_end = chunk.find(b'\r\n\r\n')
        if header_end == -1:
            header_end = chunk.find(b'\n\n')
        if header_end == -1:
            continue

        headers = chunk[:header_end]
        payload = chunk[header_end + 4:] if chunk[header_end:header_end + 4] == b'\r\n\r\n' else chunk[header_end + 2:]
        payload = payload.rstrip(b'\r\n')

        header_text = headers.decode('latin-1', errors='ignore')
        disposition = ''
        for line in header_text.splitlines():
            if line.lower().startswith('content-disposition:'):
                disposition = line
                break

        name = None
        filename = None
        for token in disposition.split(';'):
            token = token.strip()
            if token.lower().startswith('name='):
                name = token.split('=', 1)[1].strip('"')
            elif token.lower().startswith('filename='):
                filename = token.split('=', 1)[1].strip('"')

        if name is None:
            continue

        if filename is not None:
            fields[name] = {'filename': filename, 'file': payload}
        else:
            fields[name] = payload.decode('utf-8') if payload else ''

    return fields


def _serve_static_file(path, content_type):
    with open(path, 'rb') as file:
        content = file.read()
    return content, 200, {'Content-Type': content_type}


def handler(request, response):
    global LAST_QUANTIZED_IMAGE

    url = request.url or '/'
    parsed = urlparse(url)
    pathname = parsed.path
    query = parse_qs(parsed.query)

    if pathname == '/':
        html_path = os.path.join(FRONTEND_DIR, 'index.html')
        return _serve_static_file(html_path, 'text/html; charset=utf-8')

    if pathname.startswith('/frontend/'):
        relative = pathname[len('/frontend/'):]
        full_path = os.path.normpath(os.path.join(FRONTEND_DIR, relative))
        if full_path.startswith(FRONTEND_DIR):
            if relative.endswith('.css'):
                content_type = 'text/css; charset=utf-8'
            elif relative.endswith('.js'):
                content_type = 'text/javascript; charset=utf-8'
            else:
                content_type = 'text/html; charset=utf-8'
            return _serve_static_file(full_path, content_type)

    if pathname.startswith('/assets/'):
        relative = pathname[len('/assets/'):]
        full_path = os.path.normpath(os.path.join(ASSETS_DIR, relative))
        if full_path.startswith(ASSETS_DIR):
            ext = os.path.splitext(relative)[1].lower()
            mime_type = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.svg': 'image/svg+xml',
                '.ttf': 'font/ttf',
                '.css': 'text/css; charset=utf-8',
                '.js': 'text/javascript; charset=utf-8',
                '.txt': 'text/plain; charset=utf-8',
            }.get(ext, 'application/octet-stream')
            return _serve_static_file(full_path, mime_type)

    if pathname == '/api/upload':
        body = request.get_data()
        content_type = request.headers.get('Content-Type', '')
        form = _parse_multipart(body, content_type)
        uploaded = form.get('image')

        if not isinstance(uploaded, dict) or not uploaded.get('filename'):
            return b'Please upload an image file.', 400, {'Content-Type': 'text/plain; charset=utf-8'}

        try:
            image = Image.open(io.BytesIO(uploaded['file'])).convert('RGB')
            LAST_QUANTIZED_IMAGE = _reduce_color_palette(image, palette_size=100)
            return b'OK', 200, {'Content-Type': 'text/plain; charset=utf-8'}
        except Exception:
            return b'Image processing failed.', 500, {'Content-Type': 'text/plain; charset=utf-8'}

    if pathname == '/api/preview':
        if LAST_QUANTIZED_IMAGE is None:
            return b'No image uploaded yet.', 404, {'Content-Type': 'text/plain; charset=utf-8'}

        factor_value = query.get('factor', ['4'])[0]
        try:
            factor = int(factor_value)
            if factor < 2 or factor > 50:
                raise ValueError
        except ValueError:
            return b'Factor must be an integer between 2 and 50.', 400, {'Content-Type': 'text/plain; charset=utf-8'}

        processed = _pixel_art_pipeline_from_quantized(
            LAST_QUANTIZED_IMAGE,
            downsample_factor=factor,
            upscale_factor=factor,
        )
        image_bytes = io.BytesIO()
        processed.save(image_bytes, format='PNG')
        content = image_bytes.getvalue()
        return content, 200, {'Content-Type': 'image/png'}

    return b'Not found', 404, {'Content-Type': 'text/plain; charset=utf-8'}


def app(request, response):
    body, status, headers = handler(request, response)
    if isinstance(body, str):
        body = body.encode('utf-8')
    response.status = status
    for key, value in headers.items():
        response.headers[key] = value
    response.text = body.decode('utf-8') if isinstance(body, (bytes, bytearray)) and headers.get('Content-Type', '').startswith('text/') else None
    if isinstance(body, (bytes, bytearray)) and not headers.get('Content-Type', '').startswith('text/'):
        response.body = body
    else:
        response.body = body
    return response

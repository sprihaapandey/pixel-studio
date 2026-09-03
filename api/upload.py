import io
import re
from PIL import Image


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


def handler(request, response):
    body = request.body or b''
    form = _parse_multipart(body, request.headers.get('Content-Type', ''))
    uploaded = form.get('image')

    if not isinstance(uploaded, dict) or not uploaded.get('filename'):
        response.status = 400
        response.text = 'Please upload an image file.'
        return response

    try:
        image = Image.open(io.BytesIO(uploaded['file'])).convert('RGB')
        response.status = 200
        response.text = 'OK'
        return response
    except Exception:
        response.status = 500
        response.text = 'Image processing failed.'
        return response

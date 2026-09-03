import argparse
import io
import os
import random
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from PIL import Image, ImageFilter

INPUT_PATH = "/Users/sprihapandey/pixel-studio/input_image_2.png"
OUTPUT_PATH = "/Users/sprihapandey/pixel-studio/output_image_2.png"
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(WORKSPACE_DIR, "frontend")
ASSETS_DIR = os.path.join(WORKSPACE_DIR, "assets")
PREVIEW_PATH = os.path.join(WORKSPACE_DIR, "output_preview.png")


def downscale_image(image, scale_factor):
    """Resize / Downsample the image to a smaller resolution.

    Using PIL's built-in box resampling is much faster than iterating every block
    in Python while still preserving a strong pixel-art look.
    """
    width, height = image.size
    new_width = max(1, int(width / scale_factor))
    new_height = max(1, int(height / scale_factor))

    if new_width == width and new_height == height:
        return image.copy()

    return image.resize((new_width, new_height), resample=Image.Resampling.BOX)


def extract_edge_features(image, threshold=35):
    """Detect strong structural edges so linear features stay visible during downsampling."""
    grayscale = image.convert("L")
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    return edges.point(lambda p: 255 if p > threshold else 0)


def preserve_line_features(image, edge_map, strength=32):
    """Boost high-contrast line structures to keep straight edges and silhouettes sharp."""
    processed = image.copy()
    width, height = image.size

    for y in range(1, height - 1):
        for x in range(1, width - 1):
            if edge_map.getpixel((x, y)) <= 10:
                continue

            center = image.getpixel((x, y))
            left = image.getpixel((x - 1, y))
            right = image.getpixel((x + 1, y))
            up = image.getpixel((x, y - 1))
            down = image.getpixel((x, y + 1))

            neighbors = [left, right, up, down]
            avg_neighbor = tuple(
                int(sum(neighbor[channel] for neighbor in neighbors) / len(neighbors))
                for channel in range(3)
            )

            adjusted = []
            for channel in range(3):
                delta = avg_neighbor[channel] - center[channel]
                value = center[channel] + delta * 0.9 + strength * 0.35
                adjusted.append(max(0, min(255, int(value))))

            processed.putpixel((x, y), tuple(adjusted))

    return processed


def reduce_color_palette(image, palette_size=100):
    """Reduce the image to a fixed palette using Pillow's native quantizer.

    This is significantly faster than the custom k-means implementation while
    still producing a very similar constrained palette result.
    """
    if image.mode != "RGB":
        image = image.convert("RGB")

    max_colors = max(2, min(int(palette_size), 256))
    quantized = image.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    return quantized.convert("RGB")


def color_quantize(image, k=8, iterations=10, seed=None):
    """COLOR QUANTIZATION — restrict to a limited palette
       Use k-means clustering on the colors in small_image:
           - pick K initial centroids (e.g. random pixels, or K-means++)
           - repeat until convergence:
               assign each pixel to nearest centroid (by Euclidean RGB distance)
               recompute centroid = mean of assigned pixels
           - replace each pixel's color with its centroid color"""
    pixels = list(image.getdata())
    if not pixels:
        return image.copy()

    if seed is not None:
        random.seed(seed)

    centroids = random.sample(pixels, min(k, len(pixels)))
    while len(centroids) < k:
        centroids.append(pixels[0])

    for _ in range(iterations):
        clusters = [[] for _ in range(k)]

        for pixel in pixels:
            centroid_index = min(
                range(k),
                key=lambda i: sum(
                    (pixel[channel] - centroids[i][channel]) ** 2 for channel in range(3)
                ),
            )
            clusters[centroid_index].append(pixel)

        new_centroids = []
        for cluster in clusters:
            if cluster:
                new_centroids.append(
                    tuple(
                        int(sum(pixel[channel] for pixel in cluster) / len(cluster))
                        for channel in range(3)
                    )
                )
            else:
                new_centroids.append(centroids[len(new_centroids)])

        if new_centroids == centroids:
            centroids = new_centroids
            break

        centroids = new_centroids

    quantized_image = image.copy()
    for y in range(image.height):
        for x in range(image.width):
            pixel = image.getpixel((x, y))
            centroid_index = min(
                range(k),
                key=lambda i: sum(
                    (pixel[channel] - centroids[i][channel]) ** 2 for channel in range(3)
                ),
            )
            quantized_image.putpixel((x, y), centroids[centroid_index])

    return quantized_image


def edge_detail_processing(image, threshold=24, strength=1.2):
    """Optional edge/detail pass to preserve crisp pixel-art outlines."""
    processed = image.copy()
    width, height = image.size

    for y in range(1, height - 1):
        for x in range(1, width - 1):
            center = image.getpixel((x, y))
            neighbors = [
                image.getpixel((x - 1, y)),
                image.getpixel((x + 1, y)),
                image.getpixel((x, y - 1)),
                image.getpixel((x, y + 1)),
            ]

            avg_difference = sum(
                sum(abs(center[channel] - neighbor[channel]) for channel in range(3))
                for neighbor in neighbors
            ) / (len(neighbors) * 3)

            if avg_difference > threshold:
                adjusted = []
                for channel in range(3):
                    delta = (avg_difference - threshold) * strength
                    value = center[channel] + delta
                    adjusted.append(max(0, min(255, int(value))))
                processed.putpixel((x, y), tuple(adjusted))

    return processed


def upscale_image(image, scale_factor):
    """Nearest-Neighbor Upscale to preserve blocky pixel-art style."""
    width, height = image.size
    new_width = int(width * scale_factor)
    new_height = int(height * scale_factor)
    upscaled_image = image.resize((new_width, new_height), Image.NEAREST)
    return upscaled_image


def pixel_art_pipeline(image, downsample_factor=4, palette_size=100, upscale_factor=None):
    """Input Image -> Resize / Downsample -> Feature Extraction -> Reduce Color Palette -> Quantize Colors -> Optional Edge / Detail Processing -> Nearest-Neighbor Upscale -> Pixel Art Output"""
    if upscale_factor is None:
        upscale_factor = downsample_factor

    downsampled = downscale_image(image, downsample_factor)
    edge_map = extract_edge_features(downsampled)
    feature_preserved = preserve_line_features(downsampled, edge_map, strength=32)
    reduced_palette = reduce_color_palette(feature_preserved, palette_size=palette_size)
    detailed = edge_detail_processing(reduced_palette, threshold=24, strength=1.2)
    upscaled = upscale_image(detailed, upscale_factor)
    return upscaled


def pixel_art_pipeline_from_quantized(image, downsample_factor=4, upscale_factor=None):
    """Fast preview path for a pre-quantized image.

    The expensive palette reduction already happened once during upload, so each
    slider change should only re-render the already-quantized image using a quick
    downsample/upscale pass rather than running all edge-preservation filters again.
    """
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


def parse_args():
    parser = argparse.ArgumentParser(description="Pixel-art converter with a fixed palette and user-selected scale factor.")
    parser.add_argument("--input", default=INPUT_PATH, help="Path to the input image.")
    parser.add_argument("--output", default=OUTPUT_PATH, help="Path for the output image.")
    parser.add_argument("--factor", type=int, default=4, help="Shared downsample/upscale factor selected by the user.")
    parser.add_argument("--serve", action="store_true", help="Run the browser UI instead of the command-line conversion.")
    parser.add_argument("--port", type=int, default=8000, help="Port for the local web UI.")
    return parser.parse_args()


HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Pixel Art Converter</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #111827;
            color: #f3f4f6;
            display: flex;
            justify-content: center;
            padding: 32px;
        }
        .panel {
            width: min(900px, 100%);
            background: #1f2937;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }
        h1 { margin-top: 0; }
        form { display: grid; gap: 12px; }
        input {
            padding: 10px 12px;
            border-radius: 8px;
            border: 1px solid #374151;
            font-size: 16px;
        }
        input[type="range"] {
            width: 100%;
            accent-color: #60a5fa;
        }
        .preview {
            margin-top: 24px;
            background: #0f172a;
            border: 1px solid #374151;
            border-radius: 8px;
            padding: 16px;
        }
        .status {
            margin-top: 16px;
            padding: 10px 12px;
            background: rgba(59, 130, 246, 0.08);
            border: 1px solid rgba(96, 165, 250, 0.35);
            border-radius: 8px;
        }
        .status-bar {
            width: 100%;
            height: 10px;
            background: rgba(148, 163, 184, 0.2);
            border-radius: 999px;
            overflow: hidden;
            margin-top: 8px;
        }
        .status-fill {
            width: 0%;
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, #60a5fa, #34d399);
            transition: width 0.25s ease;
        }
        .status-text {
            font-size: 14px;
            color: #dbeafe;
        }
        img {
            max-width: 100%;
            display: block;
            border-radius: 8px;
        }
        .value {
            font-weight: bold;
            color: #93c5fd;
        }
    </style>
</head>
<body>
    <div class="panel">
      <h1>Pixel Art Converter</h1>
      <form id="pixelForm">
        <label>
          Upload image
          <input id="imageInput" type="file" name="image" accept="image/*" required />
        </label>
        <label>
          Pixel Resolution / Scale factor
          <div class="value" id="factorValue">4</div>
          <input id="factorSlider" type="range" name="factor" value="4" min="2" max="50" required />
        </label>
      </form>

      <div id="statusBox" class="status" aria-live="polite">
        <div id="statusText" class="status-text">Waiting for image</div>
        <div class="status-bar">
          <div id="statusFill" class="status-fill"></div>
        </div>
      </div>

      <div class="preview">
        <h2>Output</h2>
        <img id="outputImage" src="/output_preview.png" alt="Converted pixel art preview" />
      </div>
    </div>

    <script>
        const factorSlider = document.getElementById('factorSlider');
        const factorValue = document.getElementById('factorValue');
        const imageInput = document.getElementById('imageInput');
        const outputImage = document.getElementById('outputImage');
        const statusText = document.getElementById('statusText');
        const statusFill = document.getElementById('statusFill');
        let uploadReady = false;

        function setStatus(message, percent) {
            statusText.textContent = message;
            statusFill.style.width = percent + '%';
        }

        function setPlaceholder() {
            outputImage.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400"><rect width="100%" height="100%" fill="#0f172a"/><text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" fill="#94a3b8" font-size="28" font-family="Arial">Upload an image to preview</text></svg>'
            );
        }

        function refreshPreview() {
            const factor = factorSlider.value;
            factorValue.textContent = factor;
            if (!uploadReady || imageInput.files.length === 0) {
                setStatus('Waiting for image', 0);
                setPlaceholder();
                return;
            }

            setStatus('Rendering preview...', 70);
            outputImage.src = '/preview?factor=' + factor + '&t=' + Date.now();
        }

        outputImage.addEventListener('load', function () {
            setStatus('Preview ready', 100);
        });

        outputImage.addEventListener('error', function () {
            setStatus('Preview unavailable', 0);
        });

        factorSlider.disabled = true;
        uploadReady = false;
        setStatus('Waiting for image', 0);
        setPlaceholder();

        imageInput.addEventListener('change', function () {
            if (!imageInput.files.length) {
                factorSlider.disabled = true;
                uploadReady = false;
                setStatus('Waiting for image', 0);
                setPlaceholder();
                return;
            }

            const formData = new FormData();
            formData.append('image', imageInput.files[0]);
            setStatus('Uploading and quantizing image...', 25);

            fetch('/upload', {
                method: 'POST',
                body: formData
            }).then(response => {
                if (!response.ok) {
                    throw new Error('Upload failed');
                }
                uploadReady = true;
                factorSlider.disabled = false;
                setStatus('Image ready. Rendering preview...', 60);
                refreshPreview();
            }).catch(() => {
                uploadReady = false;
                factorSlider.disabled = true;
                setStatus('Upload failed', 0);
                setPlaceholder();
            });
        });

        factorSlider.addEventListener('input', function () {
            if (!uploadReady || imageInput.files.length === 0) return;
            refreshPreview();
        });
    </script>
</body>
</html>
"""


def parse_form_data(content_type, raw_body):
    fields = {}

    if not content_type:
        return fields

    if content_type.startswith("application/x-www-form-urlencoded"):
        parsed = parse_qs(raw_body.decode("utf-8"))
        for key, values in parsed.items():
            fields[key] = values[0] if values else ""
        return fields

    if content_type.startswith("multipart/form-data"):
        boundary = content_type.split("boundary=")[-1].strip('"')
        boundary_bytes = b"--" + boundary.encode("utf-8")
        parts = raw_body.split(boundary_bytes)

        for part in parts:
            if not part or part in (b"--\r\n", b"--\n", b"--"):
                continue

            chunk = part.strip(b"\r\n")
            if not chunk or chunk.startswith(b"--"):
                continue

            header_end = chunk.find(b"\r\n\r\n")
            if header_end == -1:
                header_end = chunk.find(b"\n\n")
            if header_end == -1:
                continue

            headers = chunk[:header_end]
            payload = chunk[header_end + 4:] if chunk[header_end:header_end+4] == b"\r\n\r\n" else chunk[header_end + 2:]
            payload = payload.rstrip(b"\r\n")

            header_text = headers.decode("latin-1")
            disposition = ""
            for line in header_text.splitlines():
                if line.lower().startswith("content-disposition:"):
                    disposition = line
                    break

            name = None
            filename = None
            if "name=" in disposition:
                for token in disposition.split(";"):
                    token = token.strip()
                    if token.lower().startswith("name="):
                        name = token.split("=", 1)[1].strip('"')
                    elif token.lower().startswith("filename="):
                        filename = token.split("=", 1)[1].strip('"')

            if name is None:
                continue

            if filename is not None:
                fields[name] = {"filename": filename, "file": payload}
            else:
                fields[name] = payload.decode("utf-8") if payload else ""

        return fields

    return fields


LAST_QUANTIZED_IMAGE = None


class PixelArtHandler(BaseHTTPRequestHandler):
    def _send_file(self, file_path, content_type=None):
        if not os.path.exists(file_path):
            self.send_response(404)
            self.end_headers()
            return False

        with open(file_path, "rb") as file:
            content = file.read()

        try:
            self.send_response(200)
            if content_type:
                self.send_header("Content-Type", content_type)
            else:
                self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            return False

        return True

    def do_GET(self):
        if self.path == "/":
            index_path = os.path.join(FRONTEND_DIR, "index.html")
            self._send_file(index_path, "text/html; charset=utf-8")
            return

        if self.path.startswith("/frontend/"):
            relative_path = self.path[len("/frontend/") :]
            full_path = os.path.normpath(os.path.join(FRONTEND_DIR, relative_path))
            if full_path.startswith(FRONTEND_DIR):
                content_type = "text/css; charset=utf-8" if relative_path.endswith(".css") else "text/javascript; charset=utf-8" if relative_path.endswith(".js") else "text/html; charset=utf-8"
                self._send_file(full_path, content_type)
                return

        if self.path.startswith("/assets/"):
            relative_path = self.path[len("/assets/") :]
            full_path = os.path.normpath(os.path.join(ASSETS_DIR, relative_path))
            if full_path.startswith(ASSETS_DIR):
                extension = os.path.splitext(relative_path)[1].lower()
                mime_type = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".svg": "image/svg+xml",
                    ".css": "text/css; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8",
                    ".txt": "text/plain; charset=utf-8",
                }.get(extension, "application/octet-stream")
                self._send_file(full_path, mime_type)
                return

        if self.path in ("/preview", "/api/preview"):
            global LAST_QUANTIZED_IMAGE
            if LAST_QUANTIZED_IMAGE is None:
                self.send_response(404)
                self.end_headers()
                return

            query = self.path.split("?", 1)[-1]
            params = parse_qs(query)
            factor_value = params.get("factor", ["4"])[0]

            try:
                factor = int(factor_value)
                if factor < 2 or factor > 50:
                    raise ValueError
            except ValueError:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Factor must be an integer between 2 and 50.")
                return

            processed = pixel_art_pipeline_from_quantized(
                LAST_QUANTIZED_IMAGE,
                downsample_factor=factor,
                upscale_factor=factor,
            )
            image_bytes = io.BytesIO()
            processed.save(image_bytes, format="PNG")
            content = image_bytes.getvalue()

            try:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                return
            return

        if self.path == "/output_preview.png":
            if not os.path.exists(PREVIEW_PATH):
                self.send_response(404)
                self.end_headers()
                return
            with open(PREVIEW_PATH, "rb") as preview_file:
                content = preview_file.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global LAST_QUANTIZED_IMAGE

        if self.path in ("/upload", "/api/upload"):
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            form = parse_form_data(self.headers.get("Content-Type", ""), raw_body)
            uploaded = form.get("image")

            if uploaded is None or not isinstance(uploaded, dict) or not uploaded.get("filename"):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Please upload an image file.")
                return

            try:
                image = Image.open(io.BytesIO(uploaded["file"])).convert("RGB")
                LAST_QUANTIZED_IMAGE = reduce_color_palette(image, palette_size=100)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
                return
            except Exception:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Image processing failed.")
                return

        self.send_response(404)
        self.end_headers()


def run_ui(host="0.0.0.0", port=8000):
    server = ThreadingHTTPServer((host, port), PixelArtHandler)
    print(f"Pixel art UI running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    args = parse_args()

    if args.serve:
        run_ui(port=args.port)
    else:
        img = Image.open(args.input).convert("RGB")
        output_image = pixel_art_pipeline(
            img,
            downsample_factor=args.factor,
            palette_size=100,
            upscale_factor=args.factor,
        )
        output_image.save(args.output)
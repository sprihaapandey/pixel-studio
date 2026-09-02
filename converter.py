from PIL import Image
import random

INPUT_PATH = "/Users/sprihapandey/pixel-studio/input_image_3.png"
OUTPUT_PATH = "/Users/sprihapandey/pixel-studio/output_image_3.png"


def downscale_image(image, scale_factor):
    """Resize / Downsample the image to a smaller resolution."""
    width, height = image.size
    new_width = max(1, int(width / scale_factor))
    new_height = max(1, int(height / scale_factor))
    downscaled_image = Image.new("RGB", (new_width, new_height))

    for x in range(new_width):
        for y in range(new_height):
            x0 = x * scale_factor
            y0 = y * scale_factor
            x1 = min(x0 + scale_factor, width)
            y1 = min(y0 + scale_factor, height)
            block = image.crop((x0, y0, x1, y1))
            pixels = list(block.getdata())

            if not pixels:
                avg_color = (0, 0, 0)
            else:
                avg_color = tuple(
                    int(sum(pixel[channel] for pixel in pixels) / len(pixels))
                    for channel in range(3)
                )

            downscaled_image.putpixel((x, y), avg_color)

    return downscaled_image


def reduce_color_palette(image, palette_size=16):
    """Reduce the image to a small set of representative colors."""
    return color_quantize(image, k=palette_size, iterations=10, seed=42)


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


def edge_detail_processing(image, threshold=18, strength=0.9):
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


def pixel_art_pipeline(image, downsample_factor=16, palette_size=24, upscale_factor=16):
    """Input Image -> Resize / Downsample -> Reduce Color Palette -> Quantize Colors -> Optional Edge / Detail Processing -> Nearest-Neighbor Upscale -> Pixel Art Output"""
    downsampled = downscale_image(image, downsample_factor)
    reduced_palette = reduce_color_palette(downsampled, palette_size=palette_size)
    detailed = edge_detail_processing(reduced_palette, threshold=18, strength=0.9)
    upscaled = upscale_image(detailed, upscale_factor)
    return upscaled


img = Image.open(INPUT_PATH).convert("RGB")
output_image = pixel_art_pipeline(img)
output_image.save(OUTPUT_PATH)
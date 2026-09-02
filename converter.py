from PIL import Image

img = Image.open("/Users/sprihapandey/pixel-studio/input_image.jpg")
img = img.convert("RGB")
def downscale_image(image, scale_factor):
    width, height = image.size
    new_width = int(width / scale_factor)
    new_height = int(height / scale_factor)
    downscaled_image = image.resize((new_width, new_height))
    for x in range(new_width):
        for y in range(new_height):
            block = image.crop((x * scale_factor, y * scale_factor, (x + 1) * scale_factor, (y + 1) * scale_factor))
            avg_color = tuple(map(lambda c: int(sum(c) / len(c)), zip(*block.get_flattened_data())))
            downscaled_image.putpixel((x, y), avg_color)
    return downscaled_image

scaled_img = downscale_image(img, 16)
scaled_img.save("/Users/sprihapandey/pixel-studio/output_image.jpg")
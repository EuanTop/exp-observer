"""Image-only evidence previews, isolated from the application's document."""

MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'"

IMAGE_MIMES = {
    'image/png': 'image/png',
    'image/jpeg': 'image/jpeg',
    'image/jpg': 'image/jpeg',
    'image/gif': 'image/gif',
    'image/webp': 'image/webp',
    'image/avif': 'image/avif',
    'image/bmp': 'image/bmp',
    'image/x-ms-bmp': 'image/bmp',
    'image/x-icon': 'image/x-icon',
    'image/vnd.microsoft.icon': 'image/x-icon',
    'image/svg+xml': 'image/svg+xml',
}


def image_mime(value):
    """Use retained MIME only; a filename must never turn HTML into an image."""
    return IMAGE_MIMES.get(value.split(';', 1)[0].strip().lower()) if isinstance(value, str) else None

"""Build icon.ico from the tray icon image."""
from widget import tray_image

tray_image().resize((256, 256)).save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])

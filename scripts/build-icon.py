"""Normalize the generated tray artwork and build a multi-resolution Windows icon."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "tray-icon.png"
PNG_OUTPUT = ROOT / "assets" / "tray-icon-final.png"
ICO_OUTPUT = ROOT / "assets" / "tray-icon.ico"


def main() -> None:
    image = Image.open(SOURCE).convert("RGBA")
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        raise RuntimeError("The icon source is fully transparent.")

    subject = image.crop(bounds)
    side = max(subject.size)
    padding = max(12, round(side * 0.08))
    canvas = Image.new("RGBA", (side + padding * 2, side + padding * 2))
    canvas.alpha_composite(
        subject,
        ((canvas.width - subject.width) // 2, (canvas.height - subject.height) // 2),
    )
    normalized = canvas.resize((512, 512), Image.Resampling.LANCZOS)
    normalized.save(PNG_OUTPUT)
    normalized.save(
        ICO_OUTPUT,
        format="ICO",
        sizes=((16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)),
    )


if __name__ == "__main__":
    main()

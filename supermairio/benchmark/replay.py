"""Replay a recorded episode in the emulator and save it as an animated GIF.

The session log stores the buttons of every frame, so no model call is needed. The replay stops if a
position differs from the recorded one: the GIF shows exactly what happened in that session.

    uv run supermairio replay runs/<session> --episode 1 --scale 2 --output docs/assets/replay.gif
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from supermairio.game.emulator import MarioGame

STRIP = 46  # pixels of the caption below the game, before scaling
FINAL_HOLD_MS = 2500
BACKGROUND, TEXT, ACCENT = (24, 24, 32), (235, 235, 240), (255, 196, 64)


def read_jsonl(path):
    with open(path, encoding="utf-8") as lines:
        return [json.loads(line) for line in lines]


def caption(rgb, size, frame, latency, title, font):
    """Game image with the model's current choice below it."""
    width, height = rgb.shape[1], rgb.shape[0]
    image = Image.new("RGB", (width, height + STRIP), BACKGROUND)
    image.paste(Image.fromarray(rgb), (0, 0))
    image = image.resize((width * size, (height + STRIP) * size), Image.NEAREST)
    draw = ImageDraw.Draw(image)
    top = height * size + 6 * size
    choice = frame["move"] or "waiting for the first choice"
    timing = f"{latency:.2f} s" if latency else "—"
    details = f"x {frame['x_pos']} | latency {timing}"
    draw.text((8 * size, top), title, font=font, fill=TEXT)
    draw.text((8 * size, top + 16 * size), choice, font=font, fill=ACCENT)
    draw.text(((width - 8) * size - draw.textlength(details, font=font), top + 16 * size), details, font=font, fill=TEXT)
    return image


def add_arguments(parser):
    parser.add_argument("session", type=Path, help="session directory under runs/")
    parser.add_argument("--episode", type=int, default=1, help="episode to replay (default: 1)")
    parser.add_argument("--output", type=Path, required=True, help="GIF file to write")
    parser.add_argument("--every", type=int, default=3, help="keep one image every N frames (default: 3, 20 images/s)")
    parser.add_argument("--scale", type=int, default=1, help="integer upscaling factor (default: 1)")


def run(args):
    config = json.loads((args.session / "config.json").read_text(encoding="utf-8"))
    frames = [item for item in read_jsonl(args.session / "frames.jsonl") if item["episode"] == args.episode]
    if not frames:
        raise SystemExit(f"No frames for episode {args.episode}")
    latencies = {item["index"]: item["request_seconds"] for item in read_jsonl(args.session / "events.jsonl")
        if item.get("event") == "decision" and item.get("episode") == args.episode}

    font = ImageFont.load_default(size=11 * args.scale)
    timing = "turn-based" if config["execution_mode"] == "paused" else f"{config['game_fps']} FPS, never paused"
    title = f"{config['model']} | {timing}"
    images = []
    with MarioGame(config["max_frames"]) as game:
        game.reset(config["seed"])
        for number, frame in enumerate(frames):
            result = game.step(frame["action"], 1)
            x = result.observation.info.get("x_pos")
            if x != frame["x_pos"]:
                raise SystemExit(f"Replay diverges at frame {frame['frames']}: x {x}, recorded {frame['x_pos']}")
            if number % args.every == 0 or number == len(frames) - 1:
                images.append(caption(result.observation.rgb, args.scale, frame, latencies.get(frame["index"]), title, font))

    # One palette for every image: the NES colours are few, so the GIF stays small and without dithering.
    sample = Image.new("RGB", (images[0].width, images[0].height * 3))
    for row, image in enumerate((images[0], images[len(images) // 2], images[-1])):
        sample.paste(image, (0, row * images[0].height))
    palette = sample.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    converted = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    durations = [round(args.every * 1000 / config["game_fps"])] * len(converted)
    durations[-1] = FINAL_HOLD_MS
    args.output.parent.mkdir(parents=True, exist_ok=True)
    converted[0].save(args.output, save_all=True, append_images=converted[1:], duration=durations, loop=0, optimize=True)
    size = args.output.stat().st_size / 1_000_000
    print(f"{args.output}: {len(converted)} images, {size:.1f} MB, last x={frames[-1]['x_pos']}")
    return 0

"""Scene read from Super Mario Bros NES RAM: what is around Mario, relative to him.

Distances are in pixels, 16 px = one tile. dx is the object's left edge minus Mario's
left edge (positive = to the right; Mario is 16 px wide). dy is the height of the
object's bottom above Mario's feet (positive = higher). Only what is on screen is
reported, so the scene adds no knowledge beyond the screenshot, only exact measures.
Addresses and codes were calibrated on SuperMarioBros-1-1-v0.
"""

TILE = 16
SCREEN_WIDTH = 256
FLAG_X = 3160  # 1-1 flagpole, approximate level x

# Mario
PLAYER_PAGE, PLAYER_X, PLAYER_Y = 0x6D, 0x86, 0x3B8  # PLAYER_Y + 32 = feet, in tile coordinates
SCREEN_EDGE = 0x71C  # level x of the screen's left edge, low byte
PLAYER_SPEED = 0x57  # signed, 1/16 px per frame
PLAYER_VERTICAL_SPEED = 0x9F  # signed, negative while rising
PLAYER_FLOAT = 0x1D  # 0 on the ground
POWERUP_LEVEL = 0x756  # 0 small, 1 big, 2 fire

# Enemies, five slots: active, type, state, page, x, y (y + 24 = feet), signed speed (1/16 px per frame)
ENEMY_ACTIVE, ENEMY_TYPE, ENEMY_STATE = 0x0F, 0x16, 0x1E
ENEMY_PAGE, ENEMY_X, ENEMY_Y, ENEMY_SPEED = 0x6E, 0x87, 0xCF, 0x58
ENEMIES = {0x00: "koopa", 0x01: "koopa", 0x02: "buzzy_beetle", 0x03: "koopa", 0x06: "goomba",
    0x0D: "piranha_plant", 0x0E: "flying_koopa", 0x12: "spiny"}
STOMPED = 0x04  # a flattened goomba, or a koopa turned into a shell
DEFEATED = 0x20  # falling off the screen

# Power-up object, slot 5
POWERUP_ACTIVE, POWERUP_OBJECT, POWERUP_KIND = 0x14, 0x1B, 0x39
POWERUP_PAGE, POWERUP_X, POWERUP_Y, POWERUP_SPEED = 0x73, 0x8C, 0xD4, 0x5D
POWERUP = 0x2E
POWERUPS = {0: "mushroom", 1: "fire_flower", 2: "star", 3: "one_up"}

# Tile map: two 16x13 screens of 16 px tiles from y=32, chosen by page parity
TILES, SCREEN_TILES, ROWS, TOP = 0x500, 208, 13, 32
FLOOR_ROWS = (11, 12)  # y 208 and 224
PIPE = range(0x10, 0x16)
QUESTION = (0xC0, 0xC1)
BRICKS = (0x51, 0x52, 0x57, 0x58)
HIDDEN = (0x60,)  # invisible block: not on screen, never reported
KINDS = {**{code: "pipe" for code in PIPE}, **{code: "question_block" for code in QUESTION},
    **{code: "brick" for code in BRICKS}, 0x54: "ground", 0x61: "stairs", 0xC4: "used_block"}
LOOKAHEAD = 10 * TILE  # obstacles and pits, ahead of Mario
BLOCK_RANGE = 3 * TILE  # reachable blocks, horizontally
BLOCK_HEIGHT = 5 * TILE  # reachable blocks, above Mario's feet


def signed(value):
    return value - 256 if value > 127 else value


def tile(ram, x, row):
    if not 0 <= row < ROWS or x < 0:
        return 0
    return ram[TILES + (x // SCREEN_WIDTH) % 2 * SCREEN_TILES + row * 16 + (x % SCREEN_WIDTH) // TILE]


def solid(code):
    return code != 0 and code not in HIDDEN


def read_scene(ram) -> dict:
    """Describe the visible scene from a RAM snapshot (any indexable of byte values)."""
    x = ram[PLAYER_PAGE] * 256 + ram[PLAYER_X]
    feet = ram[PLAYER_Y] + 32
    screen_x = (ram[PLAYER_X] - ram[SCREEN_EDGE]) % SCREEN_WIDTH
    left = x - screen_x
    right = left + SCREEN_WIDTH
    on_ground = ram[PLAYER_FLOAT] == 0
    vertical = signed(ram[PLAYER_VERTICAL_SPEED])
    mario = {"size": {0: "small", 1: "big", 2: "fire"}.get(ram[POWERUP_LEVEL], "unknown"),
        "on_ground": on_ground,
        "vertical": "none" if on_ground else "rising" if vertical < 0 else "falling",
        "speed": round(signed(ram[PLAYER_SPEED]) / 16, 2), "screen_x": screen_x}

    enemies = []
    for slot in range(5):
        kind, state = ram[ENEMY_TYPE + slot], ram[ENEMY_STATE + slot]
        if not ram[ENEMY_ACTIVE + slot] or state & DEFEATED:
            continue
        name = ENEMIES.get(kind, "enemy")
        if state == STOMPED:
            if name == "goomba":
                continue  # flattened: harmless and about to vanish
            name = "shell"
        ex = ram[ENEMY_PAGE + slot] * 256 + ram[ENEMY_X + slot]
        if left - TILE <= ex < right:
            speed = signed(ram[ENEMY_SPEED + slot])
            enemies.append({"type": name, "dx": ex - x, "dy": feet - (ram[ENEMY_Y + slot] + 24),
                "moving": "left" if speed < 0 else "right" if speed > 0 else "still", "speed": round(speed / 16, 2)})
    enemies.sort(key=lambda enemy: abs(enemy["dx"]))

    items = []
    if ram[POWERUP_ACTIVE] and ram[POWERUP_OBJECT] == POWERUP:
        ix = ram[POWERUP_PAGE] * 256 + ram[POWERUP_X]
        if left - TILE <= ix < right:
            speed = signed(ram[POWERUP_SPEED])
            items.append({"type": POWERUPS.get(ram[POWERUP_KIND], "power_up"), "dx": ix - x,
                "dy": feet - (ram[POWERUP_Y] + 24),
                "moving": "left" if speed < 0 else "right" if speed > 0 else "still", "speed": round(speed / 16, 2)})

    # The row Mario stands on, or would land on: first solid tile below his feet.
    column = x + TILE // 2
    base = next((row for row in range((feet - TOP) // TILE, ROWS) if solid(tile(ram, column, row))), FLOOR_ROWS[0])
    obstacle = pit = None
    start = (column // TILE + 1) * TILE
    for cx in range(start, min(right, x + LOOKAHEAD), TILE):
        if obstacle is None and solid(tile(ram, cx, base - 1)):
            height = 0
            while solid(tile(ram, cx, base - 1 - height)):
                height += 1
            obstacle = {"type": KINDS.get(tile(ram, cx, base - height), "block"), "dx": cx - x,
                "height_tiles": height}
        if pit is None and not any(solid(tile(ram, cx, row)) for row in FLOOR_ROWS):
            width = 0
            while cx + width < right and not any(solid(tile(ram, cx + width, row)) for row in FLOOR_ROWS):
                width += TILE
            pit = {"dx": cx - x, "width_px": width}
        if obstacle and pit:
            break

    blocks = []
    for cx in range(max(left, x - BLOCK_RANGE) // TILE * TILE, min(right, x + TILE + BLOCK_RANGE), TILE):
        for row in range(ROWS):
            code = tile(ram, cx, row)
            bottom = TOP + (row + 1) * TILE
            if code in QUESTION or code in BRICKS:
                if 0 < feet - bottom <= BLOCK_HEIGHT:
                    blocks.append({"type": KINDS[code], "dx": cx - x, "dy": feet - bottom})
    blocks.sort(key=lambda block: (abs(block["dx"]), block["dy"]))

    return {"mario": mario, "enemies": enemies, "obstacle_ahead": obstacle, "pit_ahead": pit,
        "blocks": blocks[:6], "items": items,
        "progress": {"x": x, "flag_x": FLAG_X, "percent": round(100 * min(x, FLAG_X) / FLAG_X)}}

"""Scene perception: conventions on a synthetic RAM, then the real 1-1 level."""

import unittest

from app import scene as s
from app.contracts import has_jump
from app.game import MarioGame
from app.moves import MOVES, MoveExecutor


def ram_with(x=100, screen_x=40, feet=208):
    ram = bytearray(0x800)
    ram[s.PLAYER_PAGE], ram[s.PLAYER_X] = divmod(x, 256)
    ram[s.PLAYER_Y] = feet - 32
    ram[s.SCREEN_EDGE] = (x - screen_x) % 256
    for cx in range(0, 512, 16):
        for row in s.FLOOR_ROWS:
            put(ram, cx, row, 0x54)
    return ram


def put(ram, x, row, code):
    ram[s.TILES + (x // 256) % 2 * s.SCREEN_TILES + row * 16 + (x % 256) // 16] = code


def enemy(ram, slot, kind, x, y=184, state=0, speed=0):
    ram[s.ENEMY_ACTIVE + slot], ram[s.ENEMY_TYPE + slot], ram[s.ENEMY_STATE + slot] = 1, kind, state
    ram[s.ENEMY_PAGE + slot], ram[s.ENEMY_X + slot] = divmod(x, 256)
    ram[s.ENEMY_Y + slot], ram[s.ENEMY_SPEED + slot] = y, speed % 256


class SyntheticSceneTests(unittest.TestCase):
    def test_surfaces_describe_each_step_and_clip_ground_to_screen(self):
        ram = ram_with(x=200, screen_x=117)  # visible [83, 339)
        for cx, highest_row in ((224, 10), (240, 9), (256, 8)):
            for row in range(highest_row, 11):
                put(ram, cx, row, 0x61)
        surfaces = s.read_scene(ram)["surfaces"]
        self.assertEqual([(p["dx"], p["width_px"], p["top_dy"]) for p in surfaces],
            [(-117, 141, 0), (24, 16, 16), (40, 16, 32), (56, 16, 48), (72, 67, 0)])
        self.assertFalse(surfaces[0]["left_edge_visible"])
        self.assertFalse(surfaces[-1]["right_edge_visible"])
        self.assertTrue(all(not p["width_is_lower_bound"] for p in surfaces[1:-1]))
        put(ram, 352, 7, 0x61)  # Entirely off-screen: must not affect any surface.
        put(ram, 304, 7, 0x60)  # Hidden block: not a visible platform.
        self.assertEqual(s.read_scene(ram)["surfaces"], surfaces)

    def test_surfaces_keep_holes_and_floating_blocks_distinct(self):
        ram = ram_with(x=200, screen_x=120)
        for cx in (240, 256):
            for row in s.FLOOR_ROWS:
                put(ram, cx, row, 0)
        put(ram, 192, 7, 0xC0)
        surfaces = s.read_scene(ram)["surfaces"]
        geometry = [(p["dx"], p["width_px"], p["top_dy"]) for p in surfaces]
        self.assertEqual(geometry, [(-120, 160, 0), (-8, 16, 64), (72, 64, 0)])

    def test_partial_pit_does_not_infer_an_offscreen_bank(self):
        ram = ram_with(x=200, screen_x=120)  # visible [80, 336)
        for cx in (320, 336, 352):
            for row in s.FLOOR_ROWS:
                put(ram, cx, row, 0)
        expected = {"dx": 120, "width_px": 16, "near_edge_visible": True,
            "far_edge_visible": False, "width_is_lower_bound": True, "under_mario": False}
        self.assertEqual(s.read_scene(ram)["pit_ahead"], expected)
        for row in s.FLOOR_ROWS:
            put(ram, 336, row, 0x54)  # Moving the hidden bank must change nothing.
        self.assertEqual(s.read_scene(ram)["pit_ahead"], expected)

    def test_pit_edges_stay_fixed_while_mario_crosses(self):
        for x in (235, 253, 269, 280):
            ram = ram_with(x=x, screen_x=x - 160)
            for cx in (240, 256, 272):
                for row in s.FLOOR_ROWS:
                    put(ram, cx, row, 0)
            pit = s.read_scene(ram)["pit_ahead"]
            self.assertEqual((x + pit["dx"], pit["width_px"]), (240, 48))
            self.assertTrue(pit["under_mario"])
            self.assertFalse(pit["width_is_lower_bound"])

    def test_both_clipped_edges_and_partial_tiles(self):
        ram = ram_with(x=200, screen_x=117)  # visible [83, 339)
        for cx in range(80, 352, 16):
            for row in s.FLOOR_ROWS:
                put(ram, cx, row, 0)
        self.assertEqual(s.read_scene(ram)["pit_ahead"], {"dx": -117, "width_px": 256,
            "near_edge_visible": False, "far_edge_visible": False,
            "width_is_lower_bound": True, "under_mario": True})

    def test_relative_positions_kinds_and_window(self):
        ram = ram_with()
        put(ram, 160, 9, 0x12)  # pipe, two tiles above the floor
        put(ram, 160, 10, 0x14)
        for row in s.FLOOR_ROWS:
            put(ram, 256, row, 0)
            put(ram, 272, row, 0)
        put(ram, 96, 7, 0xC0)  # question block, bottom 48 px above the feet
        put(ram, 112, 5, 0x60)  # hidden block: invisible, never reported
        enemy(ram, 0, 0x06, 180, speed=-10)
        enemy(ram, 1, 0x06, 150, state=s.STOMPED)
        enemy(ram, 2, 0x00, 200, state=s.STOMPED)
        enemy(ram, 3, 0x06, 400)  # off screen: right edge is x=316
        enemy(ram, 4, 0x06, 120, state=s.DEFEATED)
        ram[s.POWERUP_ACTIVE], ram[s.POWERUP_OBJECT], ram[s.POWERUP_KIND] = 1, s.POWERUP, 0
        ram[s.POWERUP_X], ram[s.POWERUP_Y], ram[s.POWERUP_SPEED] = 120, 184, 16
        ram[s.PLAYER_SPEED] = 24
        scene = s.read_scene(ram)
        self.assertEqual(scene["mario"], {"size": "small", "on_ground": True, "vertical": "none",
            "speed": 1.5, "screen_x": 40})
        self.assertEqual(scene["enemies"], [{"type": "goomba", "dx": 80, "dy": 0, "moving": "left", "speed": -0.62},
            {"type": "shell", "dx": 100, "dy": 0, "moving": "still", "speed": 0.0}])
        self.assertEqual(scene["obstacle_ahead"], {"type": "pipe", "dx": 60, "height_tiles": 2})
        self.assertEqual(scene["pit_ahead"], {"dx": 156, "width_px": 32,
            "near_edge_visible": True, "far_edge_visible": True,
            "width_is_lower_bound": False, "under_mario": False})
        self.assertEqual(scene["blocks"], [{"type": "question_block", "dx": -4, "dy": 48}])
        self.assertEqual(scene["items"], [{"type": "mushroom", "dx": 20, "dy": 0, "moving": "right", "speed": 1.0}])
        self.assertEqual(scene["progress"], {"x": 100, "flag_x": s.FLAG_X, "percent": 3})

    def test_airborne_mario_measures_walls_from_the_ground_below(self):
        ram = ram_with(feet=150)
        ram[s.PLAYER_FLOAT], ram[s.PLAYER_VERTICAL_SPEED], ram[s.POWERUP_LEVEL] = 1, 0xF8, 1
        put(ram, 128, 10, 0x61)
        mario = s.read_scene(ram)["mario"]
        self.assertEqual((mario["size"], mario["on_ground"], mario["vertical"]), ("big", False, "rising"))
        self.assertEqual(s.read_scene(ram)["obstacle_ahead"], {"type": "stairs", "dx": 28, "height_tiles": 1})
        ram[s.PLAYER_VERTICAL_SPEED] = 4
        self.assertEqual(s.read_scene(ram)["mario"]["vertical"], "falling")

    def test_nothing_ahead_and_far_objects_are_omitted(self):
        ram = ram_with()
        put(ram, 288, 10, 0x54)  # beyond the lookahead of ten tiles
        scene = s.read_scene(ram)
        self.assertIsNone(scene["obstacle_ahead"])
        self.assertIsNone(scene["pit_ahead"])
        self.assertEqual((scene["enemies"], scene["blocks"], scene["items"]), ([], [], []))


class RealLevelSceneTests(unittest.TestCase):
    def test_first_screens_of_level_1_1(self):
        seen = {"goomba": False, "question_block": False, "pipe_heights": set(), "pit": False}
        with MarioGame() as game:
            observation = game.reset(123)
            first = observation.info["scene"]
            self.assertEqual(first["mario"]["size"], "small")
            self.assertTrue(first["mario"]["on_ground"])
            self.assertEqual(first["progress"]["x"], 40)
            executor = MoveExecutor()
            held_on_ground = 0  # frames with A while back on the ground after take-off
            airborne = False
            # A scene-driven script: jump at enemies, walls and pits, run otherwise.
            for _ in range(900):
                scene, ground = observation.info["scene"], observation.info["on_ground"]
                seen["goomba"] |= any(e["type"] == "goomba" and e["dx"] > 0 and e["moving"] == "left" and -1 < e["speed"] < 0
                    for e in scene["enemies"])
                seen["question_block"] |= any(b["type"] == "question_block" for b in scene["blocks"])
                if scene["obstacle_ahead"] and scene["obstacle_ahead"]["type"] == "pipe":
                    seen["pipe_heights"].add(scene["obstacle_ahead"]["height_tiles"])
                seen["pit"] |= scene["pit_ahead"] is not None and scene["pit_ahead"]["width_px"] >= 32
                executor.settle(ground)
                danger = (any(0 < e["dx"] < 80 for e in scene["enemies"])
                    or any(scene[key] and scene[key]["dx"] < 40 for key in ("obstacle_ahead", "pit_ahead")))
                if executor.finished or not executor.move.jump:
                    if danger and ground:
                        executor.start(MOVES["high_jump_right"])
                    elif executor.finished:
                        executor.start(MOVES["run_right"])
                action, source = executor.current()
                if executor.frames == 0:
                    airborne = False
                if source == "move" and has_jump(action):
                    airborne |= ground is False
                    held_on_ground += airborne and ground is True
                result = game.step(action, 1)
                executor.advance(1)
                observation = result.observation
                if result.done or observation.info["x_pos"] > 1200:
                    break
        self.assertTrue(seen["goomba"] and seen["question_block"] and seen["pit"], seen)
        self.assertLessEqual({2, 3, 4}, seen["pipe_heights"])
        self.assertGreater(observation.info["x_pos"], 1150)
        # The early landing at x≈903 (on a pipe) no longer keeps A pressed on the ground.
        self.assertEqual(held_on_ground, 0)


if __name__ == "__main__":
    unittest.main()

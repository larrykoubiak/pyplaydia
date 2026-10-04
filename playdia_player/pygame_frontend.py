"""Minimal pygame-ce window, input and audio adapter."""

from concurrent.futures import ThreadPoolExecutor

from playdia_codec import ControlInput, Picture

from .audio import OUTPUT_CHANNELS, OUTPUT_RATE, normalize_pcm
from .engine import DiscPlayer, PlaybackState


WINDOW_SCALE = 3
DECODE_AHEAD = 12
SEGMENT_PREFETCH_SECONDS = 2.0


class FrameDecoder:
    """Decode a short rolling window without blocking pygame's event loop."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playdia-video")
        self.generation = None
        self.frames = ()
        self.futures = {}

    def reset(self, generation, frames):
        for future in self.futures.values():
            future.cancel()
        self.generation = generation
        self.frames = frames
        self.futures = {}
        self.prefetch(0)

    def prefetch(self, frame_index):
        if frame_index < 0:
            frame_index = 0
        first = max(0, frame_index - 1)
        stop = min(len(self.frames), frame_index + DECODE_AHEAD)
        for index in range(first, stop):
            if index not in self.futures:
                self.futures[index] = self.executor.submit(self.frames[index].decode_rgb)
        for index in tuple(self.futures):
            if index < frame_index - 2:
                del self.futures[index]

    def result(self, frame_index):
        future = self.futures.get(frame_index)
        if future is None or not future.done():
            return None
        return future.result()

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)


def run_player(cue_path) -> int:
    # Kept local so extraction remains usable without the optional dependency.
    import pygame

    # Video decoding is CPU-heavy. A ~108 ms device buffer avoids underruns
    # while still allowing prompt stops when an input takes another route.
    pygame.mixer.pre_init(OUTPUT_RATE, -16, OUTPUT_CHANNELS, 4096)
    pygame.init()
    pygame.display.set_caption("pyplaydia")
    screen = pygame.display.set_mode(
        (Picture.width * WINDOW_SCALE, Picture.height * WINDOW_SCALE),
        pygame.RESIZABLE,
    )
    clock = pygame.time.Clock()
    keymap = {
        pygame.K_z: ControlInput.B,
        pygame.K_x: ControlInput.A,
        pygame.K_RIGHT: ControlInput.RIGHT,
        pygame.K_LEFT: ControlInput.LEFT,
        pygame.K_UP: ControlInput.UP,
        pygame.K_DOWN: ControlInput.DOWN,
    }
    audio_available = pygame.mixer.get_init() is not None
    audio_channel = None
    seen_generation = -1
    seen_frame = (-1, -1)
    surface = None
    scaled_surface = None
    scaled_key = None
    scaled_position = (0, 0)
    decoder = FrameDecoder()
    running = True

    try:
        with DiscPlayer(cue_path) as player:
            while running:
                elapsed = clock.tick(60) / 1000.0
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            running = False
                        elif event.key in keymap:
                            player.press(keymap[event.key])

                player.advance(elapsed)
                if (
                    player.state is PlaybackState.PLAYING
                    and player.segment.duration - player.playhead <= SEGMENT_PREFETCH_SECONDS
                ):
                    player.prefetch_automatic_segment()

                if player.generation != seen_generation:
                    if audio_channel is not None:
                        audio_channel.stop()
                        audio_channel = None
                    decoder.reset(player.generation, player.segment.frames)
                    surface = None
                    scaled_surface = None
                    scaled_key = None
                    seen_frame = (-1, -1)
                    if audio_available and player.segment.pcm:
                        pcm = normalize_pcm(
                            player.segment.pcm,
                            player.segment.sample_rate,
                            player.segment.channels,
                        )
                        audio_channel = pygame.mixer.Sound(buffer=pcm).play()
                    seen_generation = player.generation

                frame = player.current_frame
                frame_key = (player.generation, player.frame_index)
                if frame is not None:
                    decoder.prefetch(player.frame_index)
                    rgb = decoder.result(player.frame_index)
                    if rgb is not None and frame_key != seen_frame:
                        surface = pygame.image.frombytes(
                            rgb, (Picture.width, Picture.height), "RGB"
                        )
                        scaled_key = None
                        seen_frame = frame_key

                screen.fill("black")
                if surface is not None:
                    width, height = screen.get_size()
                    render_key = (seen_frame, width, height)
                    if render_key != scaled_key:
                        scale = min(width / Picture.width, height / Picture.height)
                        size = (
                            max(1, round(Picture.width * scale)),
                            max(1, round(Picture.height * scale)),
                        )
                        scaled_surface = pygame.transform.scale(surface, size)
                        scaled_position = ((width - size[0]) // 2, (height - size[1]) // 2)
                        scaled_key = render_key
                    screen.blit(scaled_surface, scaled_position)
                pygame.display.flip()

                lba = frame.lba if frame is not None else player.segment.start_lba
                pygame.display.set_caption(
                    f"pyplaydia - {player.state.value} - LBA {lba} - {player.message}"
                )
    finally:
        if audio_channel is not None:
            audio_channel.stop()
        decoder.close()
        pygame.quit()
    return 0

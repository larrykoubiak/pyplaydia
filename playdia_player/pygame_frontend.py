"""Minimal pygame-ce window, input, video and streaming-audio adapter."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic

from playdia_codec import ControlInput, Picture

from .audio import OUTPUT_CHANNELS, OUTPUT_RATE
from .engine import DiscPlayer


WINDOW_SCALE = 3
DECODE_AHEAD = 12
AUDIO_DEVICE_FRAMES = 4096
AUDIO_FRAME_BYTES = OUTPUT_CHANNELS * 2
STICK_PRESS_THRESHOLD = 16384
STICK_RELEASE_THRESHOLD = 8192


class GamepadInputMapper:
    """Map SDL's standardized controller layout to Playdia controls."""

    def __init__(self, pygame):
        self.left_x = pygame.CONTROLLER_AXIS_LEFTX
        self.left_y = pygame.CONTROLLER_AXIS_LEFTY
        self.button_map = {
            # Xbox labels are reversed relative to the Playdia's physical
            # A/B placement, so preserve the buttons' positions here.
            pygame.CONTROLLER_BUTTON_A: ControlInput.B,
            pygame.CONTROLLER_BUTTON_B: ControlInput.A,
            pygame.CONTROLLER_BUTTON_DPAD_RIGHT: ControlInput.RIGHT,
            pygame.CONTROLLER_BUTTON_DPAD_LEFT: ControlInput.LEFT,
            pygame.CONTROLLER_BUTTON_DPAD_UP: ControlInput.UP,
            pygame.CONTROLLER_BUTTON_DPAD_DOWN: ControlInput.DOWN,
        }
        self.axes = {}
        self.active_directions = {}

    def button_down(self, button):
        return self.button_map.get(button)

    def axis_motion(self, instance_id, axis, value):
        if axis not in (self.left_x, self.left_y):
            return None
        values = self.axes.setdefault(instance_id, [0, 0])
        values[1 if axis == self.left_y else 0] = value
        x, y = values
        magnitude = max(abs(x), abs(y))
        current = self.active_directions.get(instance_id)

        if current is not None:
            if magnitude <= STICK_RELEASE_THRESHOLD:
                self.active_directions.pop(instance_id, None)
            return None

        if magnitude < STICK_PRESS_THRESHOLD:
            return None
        candidate = self._direction(x, y)
        self.active_directions[instance_id] = candidate
        return candidate

    def remove(self, instance_id):
        self.axes.pop(instance_id, None)
        self.active_directions.pop(instance_id, None)

    @staticmethod
    def _direction(x, y):
        if abs(x) >= abs(y):
            return ControlInput.RIGHT if x > 0 else ControlInput.LEFT
        return ControlInput.DOWN if y > 0 else ControlInput.UP


class FrameDecoder:
    """Decode a rolling frame window without blocking pygame's event loop."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playdia-video")
        self.generation = None
        self.futures = {}

    def reset(self, generation):
        for future in self.futures.values():
            future.cancel()
        self.generation = generation
        self.futures = {}

    def sync(self, generation, frames):
        if generation != self.generation:
            self.reset(generation)
        wanted = frames[:DECODE_AHEAD]
        wanted_lbas = {frame.lba for frame in wanted}
        for lba in tuple(self.futures):
            if lba not in wanted_lbas:
                self.futures[lba].cancel()
                del self.futures[lba]
        for frame in wanted:
            if frame.lba not in self.futures:
                self.futures[frame.lba] = self.executor.submit(frame.decode_rgb)

    def result(self, frame):
        future = self.futures.get(frame.lba)
        if future is None or not future.done():
            return None
        return future.result()

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)


class AudioStream:
    """Continuously feed PCM to SDL and expose the samples actually heard."""

    def __init__(self, device_factory=None, audio_format=None, clock=monotonic):
        if device_factory is None:
            from pygame._sdl2.audio import AUDIO_S16, AudioDevice

            device_factory = AudioDevice
            audio_format = AUDIO_S16

        self.clock = clock
        self.lock = Lock()
        self.buffers = deque()
        self.head_offset = 0
        self.submitted_frames = 0
        self.played_frames = 0
        self.inflight_frames = 0
        self.inflight_started_at = None
        self.device = device_factory(
            None,
            False,
            OUTPUT_RATE,
            audio_format,
            OUTPUT_CHANNELS,
            AUDIO_DEVICE_FRAMES,
            0,
            self._callback,
        )
        self.device.pause(0)

    def reset(self):
        with self.lock:
            self.buffers.clear()
            self.head_offset = 0
            self.submitted_frames = 0
            self.played_frames = 0
            self.inflight_frames = 0
            self.inflight_started_at = None

    def extend(self, chunks):
        chunks = tuple(bytes(chunk) for chunk in chunks)
        if any(len(chunk) % AUDIO_FRAME_BYTES for chunk in chunks):
            raise ValueError("PCM chunks must contain complete stereo sample frames")
        if not chunks:
            return
        with self.lock:
            self.buffers.extend(chunks)
            self.submitted_frames += sum(len(chunk) for chunk in chunks) // AUDIO_FRAME_BYTES

    def _callback(self, device, stream):
        """Fill one device buffer; exceptions must never escape SDL's thread."""
        try:
            requested = len(stream)
            output = bytearray(requested)
            written = 0
            now = self.clock()
            with self.lock:
                # The preceding callback buffer has reached the speakers now.
                self.played_frames += self.inflight_frames
                while written < requested and self.buffers:
                    chunk = self.buffers[0]
                    available = len(chunk) - self.head_offset
                    count = min(requested - written, available)
                    output[written:written + count] = chunk[
                        self.head_offset:self.head_offset + count
                    ]
                    written += count
                    self.head_offset += count
                    if self.head_offset == len(chunk):
                        self.buffers.popleft()
                        self.head_offset = 0
                self.inflight_frames = written // AUDIO_FRAME_BYTES
                self.inflight_started_at = now
            stream[:] = output
        except BaseException:
            # Exceptions escaping an SDL audio callback can terminate the
            # process. Preserve silence even if malformed data slips through.
            try:
                stream[:] = bytes(len(stream))
            except BaseException:
                pass

    def _snapshot(self):
        with self.lock:
            return (
                self.played_frames,
                self.inflight_frames,
                self.inflight_started_at,
                bool(self.buffers),
            )

    @property
    def position(self):
        played, inflight, started_at, _ = self._snapshot()
        if started_at is not None:
            elapsed_frames = max(0.0, self.clock() - started_at) * OUTPUT_RATE
            played += min(inflight, elapsed_frames)
        return played / OUTPUT_RATE

    @property
    def drained(self):
        _, inflight, started_at, buffered = self._snapshot()
        if buffered:
            return False
        if started_at is None:
            return True
        return (self.clock() - started_at) * OUTPUT_RATE >= inflight

    @property
    def has_audio(self):
        with self.lock:
            return self.submitted_frames > 0

    def close(self):
        device, self.device = self.device, None
        if device is not None:
            device.pause(1)
            device.close()


class SilentAudioStream:
    """Wall-clock fallback used when SDL cannot open an audio device."""

    has_audio = False
    drained = True
    position = 0.0

    def reset(self):
        pass

    def extend(self, chunks):
        pass

    def close(self):
        pass


def run_player(cue_path) -> int:
    # Kept local so extraction remains usable without the optional dependency.
    import pygame

    pygame.init()
    # mixer.Channel.queue only retains one sound and loses handoffs when video
    # decoding stalls the UI. Use SDL's continuous callback device instead.
    pygame.mixer.quit()
    try:
        from pygame._sdl2 import INIT_AUDIO, init_subsystem

        init_subsystem(INIT_AUDIO)
        audio = AudioStream()
    except (ImportError, pygame.error):
        audio = SilentAudioStream()

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
    gamepad = GamepadInputMapper(pygame)
    controllers = {}
    controller_api = None
    try:
        import pygame._sdl2.controller as controller_api

        controller_api.init()
    except (ImportError, pygame.error):
        controller_api = None

    def open_controller(device_index):
        if controller_api is None or not controller_api.is_controller(device_index):
            return
        try:
            controller = controller_api.Controller(device_index)
        except pygame.error:
            return
        if controller.id in controllers:
            controller.quit()
        else:
            controllers[controller.id] = controller

    if controller_api is not None:
        for device_index in range(controller_api.get_count()):
            open_controller(device_index)

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
            # Discard ISO/player construction time; scene zero has not started.
            clock.tick()
            while running:
                elapsed = clock.tick(60) / 1000.0
                generation_before_input = player.generation
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            running = False
                        elif event.key in keymap:
                            player.press(keymap[event.key])
                    elif event.type == pygame.CONTROLLERDEVICEADDED:
                        open_controller(event.device_index)
                    elif event.type == pygame.CONTROLLERDEVICEREMOVED:
                        controller = controllers.pop(event.instance_id, None)
                        if controller is not None:
                            controller.quit()
                        gamepad.remove(event.instance_id)
                    elif event.type == pygame.CONTROLLERBUTTONDOWN:
                        input_value = gamepad.button_down(event.button)
                        if input_value is not None:
                            player.press(input_value)
                    elif event.type == pygame.CONTROLLERAXISMOTION:
                        input_value = gamepad.axis_motion(
                            event.instance_id, event.axis, event.value
                        )
                        if input_value is not None:
                            player.press(input_value)

                if player.generation != seen_generation:
                    audio.reset()
                    decoder.reset(player.generation)
                    surface = None
                    scaled_surface = None
                    scaled_key = None
                    seen_frame = (-1, -1)
                    seen_generation = player.generation

                audio.extend(player.take_audio_chunks())

                # A button jump begins now; elapsed time from the previous
                # scene must not be charged to the new destination. Audio is
                # the master clock when present, so an underrun also pauses
                # video instead of accumulating A/V drift.
                generation_before_advance = player.generation
                if audio.has_audio:
                    player.advance_to(audio.position)
                    if (
                        player.generation == generation_before_advance
                        and audio.drained
                        and player.segment.stop_lba is not None
                    ):
                        # Let a scene finish if its audio legitimately ends
                        # before the physical sector stream does.
                        player.advance(elapsed)
                elif player.generation == generation_before_input:
                    player.advance(elapsed)

                if player.generation != generation_before_advance:
                    audio.reset()
                    decoder.reset(player.generation)
                    surface = None
                    scaled_surface = None
                    scaled_key = None
                    seen_frame = (-1, -1)
                    seen_generation = player.generation

                audio.extend(player.take_audio_chunks())
                frames = player.segment.frames
                decoder.sync(player.generation, frames)
                frame = player.current_frame
                frame_key = (player.generation, frame.lba if frame is not None else -1)
                if frame is not None:
                    rgb = decoder.result(frame)
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
        for controller in controllers.values():
            controller.quit()
        if controller_api is not None:
            controller_api.quit()
        audio.close()
        decoder.close()
        pygame.quit()
    return 0

"""Small Tk launcher for playback and the command-line export tools."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LaunchMode:
    label: str
    option: str
    uses_destination: bool = False
    uses_limit: bool = False


LAUNCH_MODES = {
    "play": LaunchMode("Play interactively", "--play"),
    "video": LaunchMode("Export video (AVI)", "--video", True, True),
    "audio": LaunchMode("Export audio (WAV)", "--audio", True, True),
    "frames": LaunchMode("Export frames (PNG)", "--frame", True, True),
    "controls": LaunchMode("Dump control sectors", "--controls", True),
}


def build_cli_args(cue_path, mode="play", destination="output", limit=0):
    """Translate a launcher selection to the existing command-line interface."""
    try:
        selected = LAUNCH_MODES[mode]
    except KeyError as exc:
        raise ValueError(f"Unknown launcher mode: {mode}") from exc
    if limit < 0:
        raise ValueError("Limit must be zero or greater")

    args = ["--cue_path", str(cue_path), selected.option]
    if selected.uses_destination:
        args.extend(("--destination", str(destination)))
    if selected.uses_limit:
        args.extend(("--limit", str(limit)))
    return args


def choose_command(cue_path=None, destination="output", limit=0):
    """Show the launcher and return CLI arguments, or None when cancelled."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("pyplaydia")
    root.resizable(True, False)

    cue_var = tk.StringVar(value=str(cue_path or ""))
    mode_var = tk.StringVar(value="play")
    destination_var = tk.StringVar(value=str(destination))
    limit_var = tk.StringVar(value=str(limit))
    result = None

    content = ttk.Frame(root, padding=12)
    content.grid(sticky="nsew")
    content.columnconfigure(1, weight=1)
    root.columnconfigure(0, weight=1)

    ttk.Label(content, text="CUE file").grid(row=0, column=0, sticky="w", padx=(0, 8))
    cue_entry = ttk.Entry(content, textvariable=cue_var, width=58)
    cue_entry.grid(row=0, column=1, sticky="ew")

    def browse_cue():
        initial = Path(cue_var.get()).expanduser()
        if not initial.parent.is_dir():
            initial = Path("input") if Path("input").is_dir() else Path.cwd()
        selected = filedialog.askopenfilename(
            parent=root,
            title="Open Playdia disc",
            initialdir=initial.parent,
            filetypes=(("CUE sheets", "*.cue"), ("All files", "*")),
        )
        if selected:
            cue_var.set(selected)

    ttk.Button(content, text="Browse…", command=browse_cue).grid(
        row=0, column=2, padx=(8, 0)
    )

    mode_box = ttk.LabelFrame(content, text="Action", padding=8)
    mode_box.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
    for row, (key, mode) in enumerate(LAUNCH_MODES.items()):
        ttk.Radiobutton(
            mode_box, text=mode.label, variable=mode_var, value=key
        ).grid(row=row, column=0, sticky="w")

    ttk.Label(content, text="Destination").grid(
        row=2, column=0, sticky="w", padx=(0, 8), pady=(12, 0)
    )
    destination_entry = ttk.Entry(content, textvariable=destination_var)
    destination_entry.grid(row=2, column=1, sticky="ew", pady=(12, 0))

    def browse_destination():
        selected = filedialog.askdirectory(
            parent=root,
            title="Choose output directory",
            initialdir=destination_var.get() or Path.cwd(),
        )
        if selected:
            destination_var.set(selected)

    destination_button = ttk.Button(
        content, text="Browse…", command=browse_destination
    )
    destination_button.grid(row=2, column=2, padx=(8, 0), pady=(12, 0))

    ttk.Label(content, text="Scene limit").grid(
        row=3, column=0, sticky="w", padx=(0, 8), pady=(8, 0)
    )
    limit_entry = ttk.Spinbox(content, from_=0, to=999999, textvariable=limit_var, width=10)
    limit_entry.grid(row=3, column=1, sticky="w", pady=(8, 0))
    ttk.Label(content, text="0 means no limit").grid(
        row=3, column=1, sticky="w", padx=(92, 0), pady=(8, 0)
    )

    def update_mode(*_):
        mode = LAUNCH_MODES[mode_var.get()]
        destination_state = "normal" if mode.uses_destination else "disabled"
        limit_state = "normal" if mode.uses_limit else "disabled"
        destination_entry.configure(state=destination_state)
        destination_button.configure(state=destination_state)
        limit_entry.configure(state=limit_state)

    mode_var.trace_add("write", update_mode)

    def launch():
        nonlocal result
        cue_path = Path(cue_var.get()).expanduser()
        if not cue_path.is_file():
            messagebox.showerror("Cannot open disc", "Choose an existing CUE file.", parent=root)
            cue_entry.focus_set()
            return
        try:
            limit = int(limit_var.get())
            result = build_cli_args(
                cue_path,
                mode_var.get(),
                destination_var.get() or "output",
                limit,
            )
        except ValueError as exc:
            messagebox.showerror("Invalid options", str(exc), parent=root)
            return
        root.destroy()

    buttons = ttk.Frame(content)
    buttons.grid(row=4, column=0, columnspan=3, sticky="e", pady=(16, 0))
    ttk.Button(buttons, text="Quit", command=root.destroy).grid(row=0, column=0)
    ttk.Button(buttons, text="Start", command=launch).grid(row=0, column=1, padx=(8, 0))

    root.bind("<Return>", lambda _event: launch())
    root.bind("<Escape>", lambda _event: root.destroy())
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    update_mode()
    cue_entry.focus_set()
    root.mainloop()
    return result

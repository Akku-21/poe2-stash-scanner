#!/usr/bin/env python3
"""
PoE2 Stash Scanner

Scans a stash tab cell by cell, copies each item via Ctrl+C,
and prints unique items to console.

Usage:
    python stash_scanner.py                  # Normal tab (12x12), calibrate first run
    python stash_scanner.py --quad           # Quad/XXL tab (24x24)
    python stash_scanner.py --calibrate      # Force recalibration
    python stash_scanner.py --delay 0.2      # Slower hover delay (default: 0.15s)

Flow:
    1. Calibrate by clicking top-left and bottom-right corners of stash grid
    2. Switch to PoE2 window (3 second countdown)
    3. Scanner moves mouse cell by cell, Ctrl+C each, reads clipboard
    4. Skips empty cells and deduplicates multi-slot items
    5. Prints each unique item to console
"""

import subprocess
import time
import json
import os
import sys
import hashlib
import argparse
import shutil

import cv2
import numpy as np
import mss

# --- Dependencies ---

XDOTOOL = shutil.which("xdotool")
XCLIP = shutil.which("xclip")

# --- Constants ---

SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scanner_settings.json"
)

VERSION = "0.4.0"

NORMAL_GRID = (12, 12)
QUAD_GRID = (24, 24)

# Timing (seconds)
HOVER_DELAY = 0.03
COPY_DELAY = 0.01
CLIPBOARD_SENTINEL = "__STASH_SCANNER_EMPTY__"
POE_WINDOW_TITLE = "Path of Exile 2"

ITEM_SIZE = {
    "Rings": (1, 1),
    "Amulets": (1, 1),
    "Jewels": (1, 1),
    "Charms": (1, 1),
    "Currency": (1, 1),
    "Stackable Currency": (1, 1),
    "Skill Gems": (1, 1),
    "Support Gems": (1, 1),
    "Waystones": (1, 1),
    "Divination Cards": (1, 1),
    "Quest Items": (1, 1),
    "Belts": (2, 1),
    "Flasks": (1, 2),
    "Life Flasks": (1, 2),
    "Mana Flasks": (1, 2),
    "Helmets": (2, 2),
    "Gloves": (2, 2),
    "Boots": (2, 2),
    "Shields": (2, 2),
    "Bucklers": (2, 2),
    "Foci": (2, 2),
    "Quivers": (2, 3),
    "Daggers": (1, 3),
    "Wands": (1, 3),
    "Sceptres": (1, 3),
    "Claws": (1, 3),
    "One Hand Maces": (1, 3),
    "One Hand Swords": (1, 3),
    "One Hand Axes": (1, 3),
    "Body Armours": (2, 3),
    "Crossbows": (2, 3),
    "Bows": (2, 4),
    "Staves": (2, 4),
    "Two Hand Swords": (2, 4),
    "Two Hand Maces": (2, 4),
    "Two Hand Axes": (2, 4),
    "Spears": (2, 4),
    "Flails": (2, 3),
    "Quarterstaves": (2, 4),
}

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
STASH_TEMPLATE = os.path.join(TEMPLATE_DIR, "stash_header.png")
STASH_MATCH_THRESHOLD = 0.8


def capture_screen_region(region=None):
    with mss.mss() as sct:
        if region:
            monitor = {
                "left": region[0],
                "top": region[1],
                "width": region[2],
                "height": region[3],
            }
        else:
            monitor = sct.monitors[0]
        screenshot = sct.grab(monitor)
        return np.array(screenshot)[:, :, :3]


def is_stash_open(search_region=None):
    if not os.path.exists(STASH_TEMPLATE):
        return True
    template = cv2.imread(STASH_TEMPLATE)
    if template is None:
        return True
    screenshot = capture_screen_region(search_region)
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return max_val >= STASH_MATCH_THRESHOLD


def save_stash_template():
    print("\n" + "=" * 50)
    print("  SAVE STASH TEMPLATE")
    print("=" * 50)
    print("\nOpen your stash in PoE2, then click the")
    print("TOP-LEFT corner of the 'STASH' header text")
    top_left = wait_for_click()
    print(f"  Top-left: {top_left}")

    print("\nClick the BOTTOM-RIGHT corner of the 'STASH' header text")
    bottom_right = wait_for_click()
    print(f"  Bottom-right: {bottom_right}")

    w = bottom_right[0] - top_left[0]
    h = bottom_right[1] - top_left[1]
    if w <= 0 or h <= 0:
        print("  [ERROR] Invalid region!")
        return

    img = capture_screen_region((top_left[0], top_left[1], w, h))
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    cv2.imwrite(STASH_TEMPLATE, img)
    print(f"\n  Template saved: {STASH_TEMPLATE} ({w}x{h})")


def get_poe_window_id():
    """Get the PoE2 X11 window ID. Returns window ID string or None."""
    try:
        result = subprocess.run(
            ["xdotool", "search", "--name", POE_WINDOW_TITLE],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except (subprocess.TimeoutExpired, Exception):
        pass
    return None


def focus_poe_window():
    """Focus the PoE2 window. Returns the window ID or None."""
    wid = get_poe_window_id()
    if not wid:
        print("[ERROR] PoE2 window not found!")
        return None
    try:
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", wid],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        print(f"  [FOCUSED] {POE_WINDOW_TITLE} (window {wid})")
        return wid
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"[ERROR] Failed to focus PoE2: {e}")
        return None


def check_dependencies():
    """Verify required system tools are installed."""
    missing = []
    if not XDOTOOL:
        missing.append("xdotool (sudo pacman -S xdotool)")
    if not XCLIP:
        missing.append("xclip (sudo pacman -S xclip)")
    if missing:
        print("[ERROR] Missing dependencies:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)


# --- Low-level helpers ---


def move_mouse(x, y):
    """Move mouse to absolute position, wait for completion."""
    subprocess.run(
        ["xdotool", "mousemove", "--sync", str(int(x)), str(int(y))],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )


def send_ctrl_c(window_id):
    """Send Ctrl+C to a specific window via xdotool --window."""
    subprocess.run(
        ["xdotool", "key", "--window", window_id, "ctrl+c"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )


def move_and_copy(x, y, window_id, hover_delay):
    """Move mouse + wait + Ctrl+C in a single xdotool invocation."""
    subprocess.run(
        [
            "xdotool",
            "mousemove",
            str(int(x)),
            str(int(y)),
            "sleep",
            f"{hover_delay:.3f}",
            "key",
            "--window",
            window_id,
            "ctrl+c",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )


def clear_clipboard():
    """Set clipboard to a sentinel value so we can detect empty cells.

    xclip forks a child to serve clipboard content. Using capture_output=True
    would deadlock because subprocess.run waits for the child's inherited pipes
    to close. DEVNULL avoids this — the child inherits /dev/null, not pipes.
    """
    subprocess.run(
        ["xclip", "-selection", "clipboard"],
        input=CLIPBOARD_SENTINEL.encode(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )


def read_clipboard():
    """Read current clipboard content."""
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return ""


def is_poe_item(text):
    """Check if clipboard text looks like a PoE2 item."""
    if not text or text == CLIPBOARD_SENTINEL:
        return False
    return "Item Class:" in text and "Rarity:" in text


def extract_item_class(text):
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("Item Class:"):
            return stripped.replace("Item Class:", "").strip()
    return ""


def get_item_size(item_class):
    return ITEM_SIZE.get(item_class, (1, 1))


def extract_item_summary(text):
    """Extract a one-line summary from item clipboard text."""
    lines = text.strip().split("\n")
    rarity = ""
    name = ""
    base_type = ""
    item_class = ""

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Item Class:"):
            item_class = stripped.replace("Item Class:", "").strip()
        elif stripped.startswith("Rarity:"):
            rarity = stripped.replace("Rarity:", "").strip()
            # Next line(s) are name and possibly base type
            if i + 1 < len(lines) and lines[i + 1].strip() != "--------":
                name = lines[i + 1].strip()
            if i + 2 < len(lines) and lines[i + 2].strip() != "--------":
                base_type = lines[i + 2].strip()

    if base_type:
        return f"[{rarity}] {name} — {base_type} ({item_class})"
    elif name:
        return f"[{rarity}] {name} ({item_class})"
    else:
        return f"[{rarity}] ({item_class})"


# --- Calibration ---


def wait_for_click():
    """Wait for a mouse click and return the (x, y) position."""
    # Use xdotool to get mouse position after user clicks
    # We poll for mouse button state changes
    print("  (left-click to select position...)")

    # Wait for mouse button press using xdotool
    # Simple approach: wait for Enter key in terminal instead
    # Actually, let's use pynput if available, otherwise use terminal input
    try:
        from pynput import mouse as pynput_mouse

        click_pos = [None]

        def on_click(x, y, button, pressed):
            if pressed and button == pynput_mouse.Button.left:
                click_pos[0] = (x, y)
                return False

        with pynput_mouse.Listener(on_click=on_click) as listener:
            listener.join()

        return click_pos[0]

    except ImportError:
        # Fallback: ask user to position mouse and press Enter
        input("  Position mouse and press Enter...")
        result = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            capture_output=True,
            text=True,
        )
        pos = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                key, val = line.split("=", 1)
                pos[key] = int(val)
        return (pos.get("X", 0), pos.get("Y", 0))


def calibrate():
    print("\n" + "=" * 50)
    print("  STASH GRID CALIBRATION")
    print("=" * 50)
    print("\nClick the CENTER of the TOP-LEFT cell (row 0, col 0)")
    top_left = wait_for_click()
    print(f"  Top-left cell center: {top_left}")

    print("\nClick the CENTER of the BOTTOM-RIGHT cell (last row, last col)")
    bottom_right = wait_for_click()
    print(f"  Bottom-right cell center: {bottom_right}")

    print(
        f"\n  Grid region: ({top_left[0]},{top_left[1]}) -> ({bottom_right[0]},{bottom_right[1]})"
    )
    print("  Calibration saved!\n")

    return {"top_left": list(top_left), "bottom_right": list(bottom_right)}


# --- Settings ---


def load_settings():
    """Load saved settings from disk."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_settings(settings):
    """Save settings to disk."""
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# --- Grid math ---


def calculate_cell_centers(top_left, bottom_right, grid_size):
    """Center-to-center calibration: points are centers of corner cells (0,0) and (N-1,N-1)."""
    cols, rows = grid_size
    x1, y1 = top_left
    x2, y2 = bottom_right

    x_step = (x2 - x1) / (cols - 1) if cols > 1 else 0
    y_step = (y2 - y1) / (rows - 1) if rows > 1 else 0

    centers = []
    for row in range(rows):
        for col in range(cols):
            cx = x1 + col * x_step
            cy = y1 + row * y_step
            centers.append((int(cx), int(cy), row, col))

    return centers


# --- Scanner ---


def scan_stash(top_left, bottom_right, grid_size, window_id, hover_delay=HOVER_DELAY):
    """Scan stash tab cell by cell. Returns list of unique items found."""
    from pynput import keyboard as pynput_kb

    abort_flag = [False]

    def on_press(key):
        if key == pynput_kb.Key.f10:
            abort_flag[0] = True
            return False

    kb_listener = pynput_kb.Listener(on_press=on_press)
    kb_listener.start()

    cols, rows = grid_size
    centers = calculate_cell_centers(top_left, bottom_right, grid_size)
    total_cells = len(centers)

    print(f"\n{'=' * 50}")
    print(f"  SCANNING STASH TAB")
    print(f"{'=' * 50}")
    print(f"  Grid: {cols}x{rows} ({total_cells} cells)")
    print(f"  Hover delay: {hover_delay}s")
    print(f"  Estimated time: ~{total_cells * (hover_delay + COPY_DELAY + 0.02):.0f}s")
    print(f"  Press F10 to stop")
    print(f"{'=' * 50}\n")

    items_found = []
    occupied = set()
    empty_cells = 0
    skipped_cells = 0
    scanned_cells = 0

    clear_clipboard()

    scan_start = time.time()

    debug = os.environ.get("DEBUG", "") == "1"
    t_move_total = 0.0
    t_clip_total = 0.0

    for i, (cx, cy, row, col) in enumerate(centers):
        if abort_flag[0]:
            print(f"\n\n  [STOPPED by F10]")
            break

        if (row, col) in occupied:
            skipped_cells += 1
            continue

        pct = (i + 1) / total_cells * 100
        sys.stdout.write(
            f"\r  [{i + 1}/{total_cells}] ({pct:3.0f}%) "
            f"row {row:2d} col {col:2d} | "
            f"found: {len(items_found)} | "
            f"empty: {empty_cells} | "
            f"skip: {skipped_cells}"
        )
        sys.stdout.flush()

        scanned_cells += 1

        t0 = time.perf_counter()
        move_and_copy(cx, cy, window_id, hover_delay)
        t1 = time.perf_counter()
        time.sleep(COPY_DELAY)

        text = read_clipboard()
        t2 = time.perf_counter()

        t_move_total += t1 - t0
        t_clip_total += t2 - t1 - COPY_DELAY

        if debug and scanned_cells <= 10:
            sys.stdout.write(
                f"\n  [DBG] move+copy={1000 * (t1 - t0):.0f}ms "
                f"clip={1000 * (t2 - t1 - COPY_DELAY):.0f}ms "
                f"total={1000 * (t2 - t0):.0f}ms\n"
            )

        if not is_poe_item(text):
            empty_cells += 1
            continue

        item_class = extract_item_class(text)
        w, h = get_item_size(item_class)
        for r in range(row, row + h):
            for c in range(col, col + w):
                occupied.add((r, c))

        summary = extract_item_summary(text)
        items_found.append(
            {
                "text": text,
                "summary": summary,
                "cell": [row, col],
                "size": [w, h],
                "item_class": item_class,
            }
        )

        sys.stdout.write(f"\n  >>> #{len(items_found)}: {summary} [{w}x{h}]\n")
        sys.stdout.flush()

    kb_listener.stop()
    elapsed = time.time() - scan_start

    # Final summary
    print(f"\n\n{'=' * 50}")
    print(f"  SCAN COMPLETE ({elapsed:.1f}s)")
    print(f"{'=' * 50}")
    print(f"  Items found:    {len(items_found)}")
    print(f"  Cells scanned:  {scanned_cells}")
    print(f"  Cells skipped:  {skipped_cells} (occupied by known items)")
    print(f"  Empty cells:    {empty_cells}")
    print(f"  Total cells:    {total_cells}")
    if scanned_cells > 0:
        print(f"  Avg per cell:   {1000 * elapsed / scanned_cells:.0f}ms")
        saved_pct = 100 * skipped_cells / total_cells if total_cells > 0 else 0
        print(f"  Cells saved:    {saved_pct:.0f}% (skipped via size detection)")
    print(f"{'=' * 50}")

    if items_found:
        print(f"\n  All items:")
        print(f"  {'-' * 46}")
        for i, item in enumerate(items_found, 1):
            print(f"  {i:3d}. {item['summary']}")
        print(f"  {'-' * 46}")

    return items_found


def print_full_items(items):
    """Print full clipboard text for all items."""
    if not items:
        return

    print(f"\n\n{'=' * 60}")
    print(f"  FULL ITEM DATA")
    print(f"{'=' * 60}")

    for i, item in enumerate(items, 1):
        print(f"\n{'─' * 60}")
        print(f"  ITEM #{i} (cell [{item['cell'][0]},{item['cell'][1]}])")
        print(f"{'─' * 60}")
        print(item["text"])

    print(f"{'─' * 60}\n")


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="PoE2 Stash Scanner — scan stash tab items via Ctrl+C"
    )
    parser.add_argument(
        "--quad",
        action="store_true",
        help="Quad/XXL stash tab (24x24 grid)",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Force recalibration of stash grid corners",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=HOVER_DELAY,
        help=f"Hover delay in seconds before Ctrl+C (default: {HOVER_DELAY})",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print full item text after scan (not just summaries)",
    )
    parser.add_argument(
        "--countdown",
        type=int,
        default=3,
        help="Seconds to wait before scanning starts (default: 3)",
    )
    parser.add_argument(
        "--save-template",
        action="store_true",
        help="Capture and save the stash header template for detection",
    )
    args = parser.parse_args()

    check_dependencies()

    if args.save_template:
        save_stash_template()
        sys.exit(0)

    grid_size = QUAD_GRID if args.quad else NORMAL_GRID
    grid_label = "Quad/XXL (24x24)" if args.quad else "Normal (12x12)"

    print(f"\n  PoE2 Stash Scanner v{VERSION}")
    print(f"  Grid: {grid_label}")

    # Load settings or calibrate
    settings = load_settings()
    grid_key = "quad" if args.quad else "normal"

    if args.calibrate or grid_key not in settings:
        cal = calibrate()
        settings[grid_key] = cal
        save_settings(settings)

    grid_cal = settings[grid_key]
    top_left = tuple(grid_cal["top_left"])
    bottom_right = tuple(grid_cal["bottom_right"])

    print(f"  Region: {top_left} -> {bottom_right}")

    wid = get_poe_window_id()
    if not wid:
        print("\n  [ERROR] PoE2 window not found! Is the game running?")
        sys.exit(1)

    print(f"\n  Starting scan in {args.countdown} seconds...")
    for i in range(args.countdown, 0, -1):
        sys.stdout.write(f"\r  {i}...")
        sys.stdout.flush()
        time.sleep(1)

    focus_poe_window()
    time.sleep(0.3)

    if not is_stash_open():
        print("\n  [ERROR] Stash does not appear to be open!")
        print("  Open your stash in PoE2 and try again.")
        print("  (If no template saved yet, run: --save-template)")
        sys.exit(1)

    print(f"\r  GO!   ")

    try:
        items = scan_stash(
            top_left,
            bottom_right,
            grid_size,
            wid,
            hover_delay=args.delay,
        )
    except KeyboardInterrupt:
        print("\n\n  [ABORTED by user]")
        sys.exit(0)

    # Optionally print full item data
    if args.full and items:
        print_full_items(items)


if __name__ == "__main__":
    main()

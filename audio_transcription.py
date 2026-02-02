import os
import time
import requests
import threading
import queue
import re
from datetime import datetime
import win32clipboard
import pyautogui
import numpy as np
import sounddevice as sd
import wavio
from dotenv import load_dotenv
import tkinter as tk
import platform
import ctypes
import ctypes.wintypes
import sys
import traceback
import logging

# Set up logging for better error tracking
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('transcription_errors.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Windows message constants
WM_HOTKEY = 0x0312
WM_DESTROY = 0x0002

# Modifier constants for RegisterHotKey
MOD_ALT = 0x0001      # Left Alt
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # Avoid auto-repeat messages for held keys
MOD_RALT = 0x0100     # Right Alt key (AltGr)

# Map common key names to VK codes
VK_CODE_MAP = {
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74, 'f6': 0x75,
    'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45, 'f': 0x46, 'g': 0x47,
    'h': 0x48, 'i': 0x49, 'j': 0x4A, 'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E,
    'o': 0x4F, 'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54, 'u': 0x55,
    'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59, 'z': 0x5A,
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35, '6': 0x36,
    '7': 0x37, '8': 0x38, '9': 0x39,
    'space': 0x20, 'enter': 0x0D, 'esc': 0x1B, 'tab': 0x09,
    # Navigation keys
    'end': 0x23, 'home': 0x24, 'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
    # Additional keys
    'insert': 0x2D, 'delete': 0x2E, 'pageup': 0x21, 'pagedown': 0x22,
    'numlock': 0x90, 'scroll': 0x91, 'pause': 0x13, 'capslock': 0x14,
    'print': 0x2A, 'printscreen': 0x2C, 'snapshot': 0x2C,
}

# Function to clean environment variable values
def clean_env_value(value, default=""):
    if value is None:
        return default
    
    # Remove comments
    if "#" in value:
        value = value.split("#")[0]
        
    # Strip whitespace and remove quotes
    return value.strip().replace('"', '').replace("'", "")

# Parse boolean environment variable
def parse_bool_env(env_name, default="false"):
    value = clean_env_value(os.getenv(env_name), default).lower()
    return value == "true" or value == "yes" or value == "1"

# Parse integer environment variable
def parse_int_env(env_name, default):
    try:
        return int(clean_env_value(os.getenv(env_name), str(default)))
    except ValueError:
        print(f"Warning: Invalid {env_name} value, using default of {default}")
        return default

def parse_float_env(env_name, default):
    try:
        return float(clean_env_value(os.getenv(env_name), str(default)))
    except ValueError:
        print(f"Warning: Invalid {env_name} value, using default of {default}")
        return float(default)

# Global variables for recording
is_recording = False
recording_data = []
current_recording_file = None
indicator_status = None  # Current status of the indicator
indicator_root = None    # Root tkinter window for the indicator
hotkey_id = 1  # An arbitrary ID for our hotkey
reset_hotkey_id = 2  # ID for the reset hotkey

# Optional: chunked transcription state (for faster perceived UX)
chunk_queue = None
chunk_stop_event = None
chunk_thread = None
chunk_done_event = None
chunk_transcript = ""
chunk_transcript_lock = threading.Lock()
chunk_transcript_error = None
chunk_dropped_blocks = 0
chunk_abort_short = False
last_recording_frames = 0

def safe_clipboard_copy(text):
    """Safely copy text to clipboard with error handling (Unicode)"""
    try:
        if not isinstance(text, str):
            text = str(text)
        
        # Clean text for clipboard
        try:
            text.encode('utf-8')
            safe_text = text
        except UnicodeEncodeError:
            safe_text = text.encode('utf-8', errors='replace').decode('utf-8')

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            # Force Unicode clipboard format to avoid 'mbcs' encoding
            win32clipboard.SetClipboardText(safe_text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        logger.info("Text copied to clipboard successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to copy to clipboard: {e}")
        return False


def parse_hotkey(hotkey_str):
    """Parses a hotkey string (e.g., 'ctrl+alt+f9') into modifiers and VK code."""
    parts = hotkey_str.lower().split('+')
    modifiers = 0
    vk_code = None
    key_part = parts[-1].strip()  # The actual key is the last part

    if key_part in VK_CODE_MAP:
        vk_code = VK_CODE_MAP[key_part]
    else:
        # Try to map single characters if not in the explicit map
        if len(key_part) == 1 and 'a' <= key_part <= 'z':
             vk_code = VK_CODE_MAP.get(key_part)  # Use get to avoid KeyError
        elif len(key_part) == 1 and '0' <= key_part <= '9':
             vk_code = VK_CODE_MAP.get(key_part)  # Use get to avoid KeyError
        else:
             raise ValueError(f"Unsupported key: {key_part}")

    if vk_code is None:
         raise ValueError(f"Could not map key: {key_part}")

    for part in parts[:-1]:
        mod = part.strip()
        if mod == 'ctrl' or mod == 'control':
            modifiers |= MOD_CONTROL
        elif mod == 'alt':
            modifiers |= MOD_ALT  # Left Alt only
        elif mod == 'lalt':
            modifiers |= MOD_ALT  # Explicit left Alt
        elif mod == 'ralt':
            modifiers |= MOD_RALT  # Right Alt only
        elif mod == 'shift':
            modifiers |= MOD_SHIFT
        elif mod == 'win' or mod == 'windows':
            modifiers |= MOD_WIN
        else:
            raise ValueError(f"Unknown modifier: {mod}")

    return modifiers | MOD_NOREPEAT, vk_code  # Add NOREPEAT by default

def hotkey_listener_thread():
    """Registers the hotkeys and runs the message loop."""
    user32 = ctypes.windll.user32
    try:
        # Register main recording hotkey
        modifiers, vk_code = parse_hotkey(HOTKEY)
        print(f"Attempting to register hotkey: ID={hotkey_id}, Modifiers={modifiers:#04x}, VK={vk_code:#04x} ({HOTKEY})")

        if not user32.RegisterHotKey(None, hotkey_id, modifiers, vk_code):
            error_code = ctypes.GetLastError()
            print(f"Error: Failed to register hotkey. Code: {error_code}")
            if error_code == 1409:
                print("This hotkey might already be registered by another application.")
            return

        # Register reset hotkey (Ctrl+Shift+R)
        reset_modifiers = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
        reset_vk_code = 0x52  # VK_R key
        print(f"Attempting to register reset hotkey: ID={reset_hotkey_id}, Modifiers={reset_modifiers:#04x}, VK={reset_vk_code:#04x} (Ctrl+Shift+R)")

        if not user32.RegisterHotKey(None, reset_hotkey_id, reset_modifiers, reset_vk_code):
            error_code = ctypes.GetLastError()
            print(f"Warning: Failed to register reset hotkey. Code: {error_code}")
            print("UI reset functionality will not be available.")
        else:
            print("Reset hotkey (Ctrl+Shift+R) registered successfully.")

        print(f"Hotkey '{HOTKEY}' registered successfully. Listening for messages...")

        # Message loop
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                if msg.wParam == hotkey_id:
                    print(f"Hotkey '{HOTKEY}' pressed!")
                    # Call toggle_recording via Tkinter's main loop
                    if indicator_root:
                        indicator_root.after(0, toggle_recording)
                    else:
                        print("Warning: indicator_root not available, cannot toggle recording.")
                        toggle_recording()
                elif msg.wParam == reset_hotkey_id:
                    print("Reset hotkey (Ctrl+Shift+R) pressed!")
                    # Call reset_ui_state via Tkinter's main loop
                    if indicator_root:
                        indicator_root.after(0, reset_ui_state)
                    else:
                        print("Warning: indicator_root not available, cannot reset UI state.")
                        reset_ui_state()

            # Required for processing other messages
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    except Exception as e:
        print(f"Error in hotkey listener thread: {e}")
    finally:
        print("Unregistering hotkeys...")
        try:
            user32.UnregisterHotKey(None, hotkey_id)
            user32.UnregisterHotKey(None, reset_hotkey_id)
        except:
            pass
        print("Hotkey listener thread finished.")
   
# Function to run indicator window as main window
def run_indicator():
    global indicator_root
    
    # Create the main window if it doesn't exist
    if indicator_root is None:
        indicator_root = tk.Tk()
        indicator_root.withdraw()  # Hide the main window
        
    # Start the main loop
    indicator_root.mainloop()

# Start the indicator thread at the beginning
indicator_thread = threading.Thread(target=run_indicator, daemon=True)
indicator_thread.start()

# Helper functions for the indicator
def get_status_properties(status):
    """Return properties for the given status"""
    if status == "recording":
        return {
            "bg_color": "#FF4D4D",  # Softer red
            "hover_color": "#FF6666",  # Lighter red on hover
            "icon": None,  # No icon for recording - will be replaced by animation
        }
    elif status == "transcribing":
        return {
            "bg_color": "#FFA64D",  # Softer orange
            "hover_color": "#FFB366",  # Lighter orange on hover
            "icon": "✎",  # Pen icon for transcribing
        }
    elif status == "complete":
        return {
            "bg_color": "#4CAF50",  # Softer green
            "hover_color": "#5FD164",  # Lighter green on hover
            "icon": "✓",  # Checkmark for complete
        }
    else:
        return None  # Invalid status

def create_base_window(indicator_root, x_position, y_position, window_width, window_height, bg_color):
    """Create and configure the base window"""
    top = tk.Toplevel(indicator_root)
    top.title("")
    
    # Set window properties
    top.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")
    top.configure(bg=bg_color)
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    
    # Use transparency for anti-aliasing effect if supported by platform
    try:
        top.attributes("-alpha", 0.80)  # slight transparency
    except:
        pass
    
    return top

def create_frames(top, bg_color):
    """Create the frames for the indicator"""
    # Create a basic frame with groove border
    frame = tk.Frame(top, bg=bg_color, bd=1, relief="groove")
    frame.pack(expand=True, fill="both", padx=2, pady=2)
    
    # Inner frame for content
    inner_frame = tk.Frame(frame, bg=bg_color)
    inner_frame.pack(expand=True, fill="both", padx=2, pady=2)
    
    return frame, inner_frame

def create_standard_icon(inner_frame, icon, font_size, bg_color):
    """Create a standard centered icon"""
    icon_label = tk.Label(
        inner_frame, 
        text=icon,
        font=("Arial", font_size, "bold"),
        fg="white",
        bg=bg_color
    )
    icon_label.pack(expand=True, fill="both")
    
    return icon_label

def setup_standard_hover(inner_frame, icon_label, frame, bg_color, hover_color):
    """Set up hover effects for standard icons"""
    def on_enter(e):
        inner_frame.config(bg=hover_color)
        icon_label.config(bg=hover_color)
        frame.config(bg=hover_color)
    
    def on_leave(e):
        inner_frame.config(bg=bg_color)
        icon_label.config(bg=bg_color)
        frame.config(bg=bg_color)
    
    # Bind hover events
    inner_frame.bind("<Enter>", on_enter)
    inner_frame.bind("<Leave>", on_leave)
    icon_label.bind("<Enter>", on_enter)
    icon_label.bind("<Leave>", on_leave)

def get_color_for_intensity(intensity, bg_color):
    """
    Returns RGB color for given intensity (0.0-1.0)
    Fades between background color and white
    """
    # Parse background color
    bg_r = int(bg_color[1:3], 16)
    bg_g = int(bg_color[3:5], 16)
    bg_b = int(bg_color[5:7], 16)
    
    # Calculate color components
    r = int(bg_r + (255 - bg_r) * intensity)
    g = int(bg_g + (255 - bg_g) * intensity)
    b = int(bg_b + (255 - bg_b) * intensity)
    
    # Ensure values are in valid range
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    
    # Return hex color
    return f"#{r:02x}{g:02x}{b:02x}"

def create_recording_animation(inner_frame, bg_color, hover_color, font_size, top):
    """Create and set up the recording animation"""
    # Container for dots (centered)
    dots_container = tk.Frame(inner_frame, bg=bg_color)
    dots_container.pack(expand=True, fill="both")
    
    # Frame for the dots to allow centering
    dots_frame = tk.Frame(dots_container, bg=bg_color)
    dots_frame.pack(expand=False, anchor="center")
    
    # Create the dots
    dot_labels = []
    dot_size = max(22, int(font_size * 1.5))  # Larger dots
    
    for i in range(4):
        dot = tk.Label(
            dots_frame,
            text="●",  # Solid circle for better visibility
            font=("Arial", dot_size, "bold"),
            fg=bg_color,  # Start with background color (invisible)
            bg=bg_color
        )
        dot.pack(side="left", padx=4)  # More spacing
        dot_labels.append(dot)
    
    # Create a table of 32 pre-calculated colors for smooth transition
    color_levels = 32
    color_table = [get_color_for_intensity(i / (color_levels-1), bg_color) for i in range(color_levels)]
    
    # Save color table in top window for later access
    top.color_table = color_table
    top.bg_color = bg_color
    
    # Define animation function
    def animate_dots():
        if not hasattr(top, "active") or not top.active:
            return
        
        # Get current animation frame
        frames_per_cycle = 120  # Increased from 48 to slow down the overall animation
        current_frame = getattr(top, "animation_frame", 0)
        
        # Use correct color table based on hover state
        hover_table = getattr(top, "hover_color_table", None)
        current_color_table = hover_table if hover_table is not None else top.color_table
        hover_bg = getattr(top, "hover_bg_color", None)
        current_bg = hover_bg if hover_bg is not None else top.bg_color
        
        # Update each dot with proper intensity
        for i in range(4):
            # Calculate position in animation cycle for this dot
            phase = (current_frame - (i * frames_per_cycle // 4)) % frames_per_cycle
            
            # Convert phase to intensity using asymmetric curve with proper easing
            import math
            angle = (phase / frames_per_cycle) * 2 * math.pi
            
            # Extended brightening phase (1/4 of cycle instead of 1/6)
            if angle < math.pi/4:  # First quarter of cycle - brightening phase
                # Normalized time within the brightening phase (0 to 1)
                t = angle / (math.pi/4)
                # Ease-in-out curve: slower at beginning and end, faster in middle
                # This makes it slow down as it approaches full brightness
                if t < 0.5:
                    # First half: accelerating (ease-in)
                    intensity = 2 * t * t
                else:
                    # Second half: decelerating (ease-out)
                    t = t - 1  # Adjust t to -0.5 to 0 range
                    intensity = 1 - 2 * t * t
            else:  # Fade for the remainder of the cycle
                # Start fading quickly, then slow down (ease-out)
                normalized = (angle - math.pi/4) / (2*math.pi - math.pi/4)
                intensity = 1.0 - math.pow(normalized, 0.5)  # Square root for pronounced ease-out
            
            # Get color for this intensity
            color_index = int(intensity * (color_levels-1))
            color = current_color_table[color_index]
            
            # Apply color to dot
            if intensity > 0.01:  # Only update visible dots
                dot_labels[i].config(fg=color)
            else:
                dot_labels[i].config(fg=current_bg)  # Hide completely faded dots
        
        # Increment frame
        top.animation_frame = (current_frame + 1) % frames_per_cycle
        
        # Schedule next animation frame (16.67ms = ~60fps for extremely smooth animation)
        top.after(16, animate_dots)
    
    # Set up hover effects
    def on_enter(e):
        # Store original color for animation
        top.hover_bg_color = hover_color
        
        # Pre-calculate hover colors
        top.hover_color_table = [get_color_for_intensity(i / (color_levels-1), hover_color) for i in range(color_levels)]
        
        # Update background colors
        inner_frame.config(bg=hover_color)
        dots_container.config(bg=hover_color)
        dots_frame.config(bg=hover_color)
        
        # Update background for all dots
        for dot in dot_labels:
            dot.config(bg=hover_color)
    
    def on_leave(e):
        # Restore original color
        top.hover_bg_color = None
        top.hover_color_table = None
        
        # Update background colors
        inner_frame.config(bg=bg_color)
        dots_container.config(bg=bg_color)
        dots_frame.config(bg=bg_color)
        
        # Update background for all dots
        for dot in dot_labels:
            dot.config(bg=bg_color)
    
    # Bind hover events
    inner_frame.bind("<Enter>", on_enter)
    inner_frame.bind("<Leave>", on_leave)
    dots_container.bind("<Enter>", on_enter)
    dots_container.bind("<Leave>", on_leave)
    dots_frame.bind("<Enter>", on_enter)
    dots_frame.bind("<Leave>", on_leave)
    
    # Return animation function and elements
    return animate_dots, dots_container, dots_frame, dot_labels

def set_window_platform_specifics(top):
    """Set platform-specific window properties"""
    if platform.system() == "Windows":
        try:
            hwnd = top.winfo_id()
            # Always on top
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)
        except:
            pass

def show_indicator(status):
    """Show indicator with given status using the appropriate type"""
    global indicator_status, indicator_root
    
    # If first time or indicator was closed, create a new toplevel window
    if indicator_status != status:
        indicator_status = status
        
        # Use the main thread's root to create a new toplevel window
        def create_toplevel():
            # Get properties for this status
            props = get_status_properties(status)
            if not props:
                return  # Invalid status
            
            bg_color = props["bg_color"]
            hover_color = props["hover_color"]
            icon = props["icon"]
            
            # Get screen dimensions
            screen_width = indicator_root.winfo_screenwidth()
            screen_height = indicator_root.winfo_screenheight()
            
            # Set window size
            window_width = int(screen_width * 0.15)
            window_height = int(screen_height * 0.05)
            
            # Ensure minimum size
            window_width = max(window_width, 60)
            window_height = max(window_height, 36)
            
            # Set position
            x_position = (screen_width - window_width) // 2
            y_position = screen_height - window_height - int(screen_height * 0.05)
            
            # Create base window
            top = create_base_window(indicator_root, x_position, y_position, window_width, window_height, bg_color)
            
            # Create frames
            frame, inner_frame = create_frames(top, bg_color)
            
            # Font size based on screen resolution
            font_size = max(18, int(screen_height * 0.025))
            
            animation_active = False
            
            # Create content based on status
            if status == "recording":
                # Set up animation
                animate_dots, dots_container, dots_frame, dot_labels = create_recording_animation(
                    inner_frame, bg_color, hover_color, font_size, top
                )
                
                # Start animation
                top.active = True
                top.animation_frame = 0
                animate_dots()
                animation_active = True
            else:
                # For non-recording states, show standard icon
                icon_label = create_standard_icon(inner_frame, icon, font_size, bg_color)
                setup_standard_hover(inner_frame, icon_label, frame, bg_color, hover_color)
            
            # Set platform-specific properties
            set_window_platform_specifics(top)
            
            # Close any existing indicator
            if hasattr(indicator_root, 'current_indicator') and indicator_root.current_indicator:
                try:
                    if hasattr(indicator_root.current_indicator, "active"):
                        indicator_root.current_indicator.active = False  # Stop animation
                    indicator_root.current_indicator.destroy()
                except:
                    pass
                    
            indicator_root.current_indicator = top
            
            # Auto-close complete indicator after 2.5 seconds
            if status == "complete":
                top.after(2000, top.destroy)
            
            # Handle window destruction properly for animation
            def on_destroy():
                if animation_active:
                    top.active = False  # Stop animation loop
                top.destroy()
            
            top.protocol("WM_DELETE_WINDOW", on_destroy)
        
        # Schedule the UI update in the main thread
        if indicator_root:
            indicator_root.after(0, create_toplevel)

# Configuration
TRANSCRIPTION_MODEL = clean_env_value(os.getenv("TRANSCRIPTION_MODEL"), "local").lower()
FIREWORKS_API_KEY = clean_env_value(os.getenv("FIREWORKS_API_KEY"))
OPENAI_API_KEY = clean_env_value(os.getenv("OPENAI_API_KEY"))
LOCAL_MODEL_PATH = clean_env_value(os.getenv("LOCAL_MODEL_PATH"), "models")
HOTKEY = clean_env_value(os.getenv("RECORDING_HOTKEY"), "f9")
SAMPLE_RATE = 44100  # Sample rate in Hz
DELETE_RECORDINGS = parse_bool_env("DELETE_RECORDINGS", "true")
MAX_RECORDING_AGE_DAYS = parse_int_env("MAX_RECORDING_AGE_DAYS", 7)
USE_GPU = parse_bool_env("USE_GPU", "false")
CHUNK_TRANSCRIBE = parse_bool_env("CHUNK_TRANSCRIBE", "false")
CHUNK_SECONDS = parse_int_env("CHUNK_SECONDS", 12)
CHUNK_OVERLAP_SECONDS = parse_int_env("CHUNK_OVERLAP_SECONDS", 1)
CHUNK_BEAM_SIZE = parse_int_env("CHUNK_BEAM_SIZE", 1)
CHUNK_LANGUAGE = clean_env_value(os.getenv("CHUNK_LANGUAGE"), "en")
CHUNK_VAD_FILTER = parse_bool_env("CHUNK_VAD_FILTER", "true")
CHUNK_QUEUE_MAXSIZE = parse_int_env("CHUNK_QUEUE_MAXSIZE", 256)
CHUNK_FINALIZE_TIMEOUT_SECONDS = parse_int_env("CHUNK_FINALIZE_TIMEOUT_SECONDS", 30)
LOG_FULL_TRANSCRIPT = parse_bool_env("LOG_FULL_TRANSCRIPT", "true")
LOG_CHUNK_DEBUG = parse_bool_env("LOG_CHUNK_DEBUG", "false")
INITIAL_PROMPT = clean_env_value(os.getenv("INITIAL_PROMPT"), "")

# Validate configuration
if TRANSCRIPTION_MODEL not in ["fireworks", "openai", "local"]:
    raise ValueError("TRANSCRIPTION_MODEL must be either 'fireworks', 'openai', or 'local'")

if TRANSCRIPTION_MODEL == "fireworks" and not FIREWORKS_API_KEY:
    raise ValueError("FIREWORKS_API_KEY not found in .env file")
elif TRANSCRIPTION_MODEL == "openai" and not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in .env file")
elif TRANSCRIPTION_MODEL == "local":
    # Try to import faster-whisper
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError("faster-whisper is not installed. Please run 'pip install faster-whisper'")
    
    # Define the default model to use if no local model is found
    DEFAULT_MODEL_SIZE = clean_env_value(os.getenv("DEFAULT_MODEL_SIZE"), "small.en")
    
    # Create models directory if it doesn't exist
    if not os.path.exists(LOCAL_MODEL_PATH):
        os.makedirs(LOCAL_MODEL_PATH, exist_ok=True)
        print(f"Created model directory: {LOCAL_MODEL_PATH}")
    
    # List of valid model sizes
    VALID_MODEL_SIZES = [
        "tiny.en", "tiny", "base.en", "base", "small.en", "small", 
        "medium.en", "medium", "large-v1", "large-v2", "large-v3", 
        "large", "distil-large-v2", "distil-medium.en", "distil-small.en", 
        "distil-large-v3", "large-v3-turbo", "turbo",
        # Add support for full Hugging Face model paths
        "deepdml/faster-whisper-large-v3-turbo-ct2"
    ]
    
    # Look for existing model files
    found_models = []
    try:
        # Check for models in the Hugging Face cache format
        for root, dirs, files in os.walk(LOCAL_MODEL_PATH):
            if "model.bin" in files:
                # Try to extract model size from path or folder name
                path_lower = root.lower()
                
                # First check for full model paths
                if DEFAULT_MODEL_SIZE.lower() in path_lower:
                    if DEFAULT_MODEL_SIZE not in found_models:
                        found_models.append(DEFAULT_MODEL_SIZE)
                        break
                
                # Then check for standard model sizes
                for size in VALID_MODEL_SIZES:
                    if size.lower() in path_lower:
                        if size not in found_models:
                            found_models.append(size)
                            break
        
        # Also check for direct .bin files
        for file in os.listdir(LOCAL_MODEL_PATH):
            if file.endswith('.bin'):
                model_name = file.replace(".bin", "")
                if model_name in VALID_MODEL_SIZES and model_name not in found_models:
                    found_models.append(model_name)
    except Exception as e:
        print(f"Error checking for model files: {e}")
    
    # Determine which model to use
    if found_models:
        print(f"Found existing model(s): {', '.join(found_models)}")
        
        # Extract base model name for comparison (e.g. "large-v3" from "deepdml/faster-whisper-large-v3-turbo-ct2")
        requested_base_model = DEFAULT_MODEL_SIZE.split('/')[-1].replace('faster-whisper-', '').replace('-ct2', '')
        if 'turbo' in requested_base_model:
            requested_base_model = 'large-v3'  # Map turbo variants to base large-v3
        
        # Check if our specified model exists in the found models
        model_match = next((model for model in found_models if model == requested_base_model), None)
        if model_match:
            # Use the specified model
            local_model_name = model_match
            print(f"Using model: {DEFAULT_MODEL_SIZE} (found as {model_match})")
        else:
            # Use first model found
            local_model_name = found_models[0]
            print(f"Using existing model: {local_model_name}")
            if DEFAULT_MODEL_SIZE != "small.en":  # Only show note if user specified a non-default model
                print(f"Note: Requested model '{DEFAULT_MODEL_SIZE}' not found")
                print(f"Delete the models folder if you want to force downloading a specific model")
    else:
        # No local model found, use the default model name for download
        print(f"No model files found in '{LOCAL_MODEL_PATH}'")
        local_model_name = DEFAULT_MODEL_SIZE
        print(f"Will download the {DEFAULT_MODEL_SIZE} model")

# Initialize OpenAI client if needed
if TRANSCRIPTION_MODEL == "openai":
    from openai import OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
else:
    openai_client = None

# Initialize local model if needed
local_model = None
if TRANSCRIPTION_MODEL == "local":
    print(f"Loading model: {local_model_name}")
    print("This may take a moment if downloading for the first time...")
    
    try:
        if USE_GPU:
            try:
                print("Attempting to use GPU...")
                import torch
                if torch.cuda.is_available():
                    print(f"CUDA available: Using {torch.cuda.get_device_name(0)}")
                    # Use the DEFAULT_MODEL_SIZE directly without local_model_name
                    local_model = WhisperModel(DEFAULT_MODEL_SIZE, device="cuda", compute_type="float16", download_root=LOCAL_MODEL_PATH)
                else:
                    print("CUDA not available, falling back to CPU")
                    local_model = WhisperModel(DEFAULT_MODEL_SIZE, device="cpu", compute_type="int8", download_root=LOCAL_MODEL_PATH)
            except Exception as e:
                print(f"GPU acceleration failed, falling back to CPU: {e}")
                local_model = WhisperModel(DEFAULT_MODEL_SIZE, device="cpu", compute_type="int8", download_root=LOCAL_MODEL_PATH)
        else:
            # Directly use CPU
            local_model = WhisperModel(DEFAULT_MODEL_SIZE, device="cpu", compute_type="int8", download_root=LOCAL_MODEL_PATH)
            print("Using CPU for inference (GPU disabled in config)")
            
        print("Model loaded successfully")
    except Exception as e:
        raise Exception(f"Failed to load model: {e}")

# Specify the directory where your recordings are saved
recordings_dir = os.path.expanduser("~/Documents/Sound Recordings") 

def transcribe_audio_fireworks(file_path):
    """Transcribe audio using Fireworks AI's Whisper Turbo"""
    try:
        with open(file_path, "rb") as audio_file:
            response = requests.post(
                "https://audio-turbo.us-virginia-1.direct.fireworks.ai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {FIREWORKS_API_KEY}"},
                files={"file": audio_file},
                data={
                    "model": "whisper-v3-turbo",
                    "temperature": "0",
                    "vad_model": "silero"
                },
                timeout=60  # Add timeout to prevent hanging
            )
            
            if response.status_code == 200:
                result = response.json()
                if "text" in result:
                    return safe_text_handling(result["text"], "Fireworks transcription")
                else:
                    raise Exception(f"Unexpected response format: {result}")
            else:
                raise Exception(f"Error {response.status_code}: {response.text}")
    except requests.exceptions.Timeout:
        raise Exception("Fireworks API request timed out after 60 seconds")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Network error during Fireworks transcription: {str(e)}")
    except Exception as e:
        logger.error(f"Fireworks transcription error: {e}")
        raise Exception(f"Fireworks transcription failed: {str(e)}")

def transcribe_audio_openai(file_path):
    """Transcribe audio using OpenAI's Whisper"""
    try:
        with open(file_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        return safe_text_handling(transcript.text, "OpenAI transcription")
    except Exception as e:
        logger.error(f"OpenAI transcription error: {e}")
        raise Exception(f"OpenAI transcription failed: {str(e)}")

def transcribe_audio_local(file_path):
    """Transcribe audio using local Whisper model"""
    logger.info("Transcribing with local model...")
    
    try:
        # Perform transcription
        try:
            segments, info = local_model.transcribe(
                file_path,
                beam_size=5,
                initial_prompt=INITIAL_PROMPT or None
            )
        except TypeError:
            segments, info = local_model.transcribe(file_path, beam_size=5)
        
        # Combine all segments with safe text handling
        transcript_parts = []
        for segment in segments:
            safe_segment_text = safe_text_handling(segment.text, "local model segment")
            transcript_parts.append(safe_segment_text)
        
        transcript = " ".join(transcript_parts)
        
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        return transcript
    except Exception as e:
        logger.error(f"Local model transcription error: {str(e)}")
        raise Exception(f"Local model transcription error: {str(e)}")

def transcribe_audio(file_path):
    """Transcribe audio using the configured model"""
    if TRANSCRIPTION_MODEL == "fireworks":
        return transcribe_audio_fireworks(file_path)
    elif TRANSCRIPTION_MODEL == "openai":
        return transcribe_audio_openai(file_path)
    else:
        return transcribe_audio_local(file_path)

def safe_text_handling(text, operation="processing"):
    """Safely handle text that might contain problematic characters"""
    if text is None:
        return ""
    
    try:
        # Try to encode as UTF-8 to check for issues
        text.encode('utf-8')
        return text
    except UnicodeEncodeError as e:
        logger.warning(f"Unicode encoding issue in {operation}: {e}")
        # Try to clean the text by removing problematic characters
        try:
            # Replace problematic characters with safe alternatives
            cleaned_text = text.encode('utf-8', errors='replace').decode('utf-8')
            logger.info(f"Cleaned text for {operation}, removed problematic characters")
            return cleaned_text
        except Exception as cleanup_error:
            logger.error(f"Failed to clean text for {operation}: {cleanup_error}")
            return f"[Text processing error: {str(e)}]"
    except Exception as e:
        logger.error(f"Unexpected error in text handling for {operation}: {e}")
        return f"[Text error: {str(e)}]"

def safe_paste_text():
    """Safely paste text with error handling"""
    try:
        pyautogui.hotkey('ctrl', 'v')
        return True
    except Exception as e:
        logger.error(f"Failed to paste text: {e}")
        return False

def copy_to_clipboard(text):
    """Copy text to Windows clipboard (deprecated - use safe_clipboard_copy instead)"""
    print("Warning: copy_to_clipboard is deprecated. Use safe_clipboard_copy instead.")
    return safe_clipboard_copy(text)

def paste_text():
    """Paste text at current cursor position (deprecated - use safe_paste_text instead)"""
    print("Warning: paste_text is deprecated. Use safe_paste_text instead.")
    return safe_paste_text()

def audio_callback(indata, frames, time, status):
    """Callback function for audio recording"""
    global chunk_dropped_blocks
    if status:
        print(f"Status: {status}")
    if is_recording:
        recording_data.append(indata.copy())
        # If chunked transcription is enabled, also feed the chunk queue
        if chunk_queue is not None:
            try:
                chunk_queue.put_nowait(indata.copy())
            except queue.Full:
                # Track dropped audio so we don't treat chunk transcript as authoritative.
                chunk_dropped_blocks += 1
            except Exception:
                # Drop audio if the queue is unavailable; recording still proceeds.
                pass

def _tokenize_words(text):
    return re.findall(r"\b\w+\b", text.lower())

def _drop_leading_tokens(text, count):
    if count <= 0:
        return text
    matches = list(re.finditer(r"\b\w+\b", text))
    if count >= len(matches):
        return ""
    cut = matches[count - 1].end()
    return text[cut:].lstrip()

def _merge_transcripts(prev_text, new_text, max_words=30):
    """Best-effort de-duplication when chunking with overlap."""
    prev_text = (prev_text or "").strip()
    new_text = (new_text or "").strip()
    if not prev_text:
        return new_text
    if not new_text:
        return prev_text

    prev_tokens = _tokenize_words(prev_text)
    new_tokens = _tokenize_words(new_text)
    if not prev_tokens or not new_tokens:
        return f"{prev_text} {new_text}"

    suffix = prev_tokens[-max_words:]
    prefix = new_tokens[:max_words]

    max_k = min(len(suffix), len(prefix))
    for k in range(max_k, 1, -1):
        if suffix[-k:] == prefix[:k]:
            remainder = _drop_leading_tokens(new_text, k).strip()
            if not remainder:
                return prev_text
            return f"{prev_text} {remainder}"

    return f"{prev_text} {new_text}"

def _resample_to_16k(audio, sample_rate):
    if audio is None or len(audio) == 0:
        return audio
    target_rate = 16000
    if sample_rate == target_rate:
        return audio.astype(np.float32, copy=False)
    audio = audio.astype(np.float32, copy=False)
    new_len = int(len(audio) * target_rate / sample_rate)
    if new_len <= 0:
        return np.array([], dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32, copy=False)

def _chunk_transcription_worker(base_file_path):
    """Transcribe audio while recording by chunking audio into smaller windows."""
    global chunk_transcript, chunk_transcript_error

    def prepare_chunk_audio(chunk_audio):
        # Convert to mono float32 and resample to 16 kHz for faster-whisper input.
        audio = np.asarray(chunk_audio, dtype=np.float32)
        if audio.ndim > 1:
            if audio.shape[1] > 1:
                audio = audio.mean(axis=1)
            else:
                audio = audio.reshape(-1)
        audio = audio.reshape(-1)
        return _resample_to_16k(audio, SAMPLE_RATE)

    try:
        if LOG_CHUNK_DEBUG:
            logger.info(
                f"Chunk worker started: chunk_seconds={CHUNK_SECONDS}, overlap_seconds={CHUNK_OVERLAP_SECONDS}, "
                f"beam_size={CHUNK_BEAM_SIZE}, vad_filter={CHUNK_VAD_FILTER}, language={CHUNK_LANGUAGE}"
            )
        chunk_frames = max(1, int(CHUNK_SECONDS * SAMPLE_RATE))
        overlap_frames = max(0, int(CHUNK_OVERLAP_SECONDS * SAMPLE_RATE))
        pending = []
        pending_frames = 0
        tail = None
        chunk_index = 0
        blocks_received = 0
        last_debug_ts = time.time()

        while True:
            # Exit when we've been asked to stop and we've drained everything.
            if chunk_stop_event is not None and chunk_stop_event.is_set():
                # If no more audio is coming, exit and flush pending frames below.
                if chunk_queue is None or chunk_queue.empty():
                    if chunk_abort_short:
                        pending = []
                        pending_frames = 0
                        tail = None
                        if LOG_CHUNK_DEBUG:
                            logger.info("Chunk worker aborting short recording before flush.")
                    else:
                        if LOG_CHUNK_DEBUG:
                            logger.info(
                                f"Chunk worker stopping with pending_frames={pending_frames}, "
                                f"blocks_received={blocks_received}, chunks_done={chunk_index}"
                            )
                    break

            try:
                block = chunk_queue.get(timeout=0.2)
                pending.append(block)
                pending_frames += len(block)
                blocks_received += 1
                now_ts = time.time()
                if LOG_CHUNK_DEBUG and now_ts - last_debug_ts >= 2.0:
                    last_debug_ts = now_ts
                    logger.info(
                        f"Chunk worker status: pending_frames={pending_frames}, "
                        f"blocks_received={blocks_received}, chunks_done={chunk_index}"
                    )
            except Exception:
                # No new audio; loop to check stop conditions.
                pass

            while pending_frames >= chunk_frames:
                chunk_index += 1
                if LOG_CHUNK_DEBUG:
                    logger.info(f"Chunk {chunk_index} ready (frames={chunk_frames}, pending={pending_frames}).")
                # Pull exactly chunk_frames from pending buffers.
                take = []
                remaining = chunk_frames
                while remaining > 0 and pending:
                    buf = pending[0]
                    if len(buf) <= remaining:
                        take.append(buf)
                        pending.pop(0)
                        pending_frames -= len(buf)
                        remaining -= len(buf)
                    else:
                        take.append(buf[:remaining])
                        pending[0] = buf[remaining:]
                        pending_frames -= remaining
                        remaining = 0

                if not take:
                    break

                chunk_audio = np.concatenate(take, axis=0)
                if tail is not None and len(tail) > 0:
                    chunk_audio = np.concatenate([tail, chunk_audio], axis=0)

                # Update tail for next chunk
                if overlap_frames > 0 and len(chunk_audio) > overlap_frames:
                    tail = chunk_audio[-overlap_frames:].copy()
                else:
                    tail = chunk_audio.copy() if overlap_frames > 0 else None

                # Transcribe chunk (favor speed settings by default)
                try:
                    chunk_audio_mono = prepare_chunk_audio(chunk_audio)
                    start_ts = time.time()
                    try:
                        segments, info = local_model.transcribe(
                            chunk_audio_mono,
                            beam_size=CHUNK_BEAM_SIZE,
                            language=CHUNK_LANGUAGE if CHUNK_LANGUAGE else None,
                            vad_filter=CHUNK_VAD_FILTER,
                            initial_prompt=INITIAL_PROMPT or None
                        )
                    except TypeError:
                        # Older faster-whisper versions may not support some kwargs
                        segments, info = local_model.transcribe(
                            chunk_audio_mono,
                            beam_size=CHUNK_BEAM_SIZE
                        )

                    chunk_text_parts = []
                    for segment in segments:
                        chunk_text_parts.append(safe_text_handling(segment.text, "chunk segment"))
                    chunk_text = " ".join(chunk_text_parts).strip()
                    elapsed = time.time() - start_ts
                    if LOG_CHUNK_DEBUG:
                        logger.info(f"Chunk {chunk_index} transcribed in {elapsed:.2f}s (text_len={len(chunk_text)}).")

                    if chunk_text:
                        with chunk_transcript_lock:
                            chunk_transcript = _merge_transcripts(chunk_transcript, chunk_text)
                except Exception as e:
                    chunk_transcript_error = e

        # Flush any remaining audio as a final, smaller chunk
        if pending_frames > 0:
            try:
                if LOG_CHUNK_DEBUG:
                    logger.info(f"Flushing final chunk (pending_frames={pending_frames}).")
                final_audio = np.concatenate(pending, axis=0)
                if tail is not None and len(tail) > 0:
                    final_audio = np.concatenate([tail, final_audio], axis=0)

                final_audio_mono = prepare_chunk_audio(final_audio)
                start_ts = time.time()
                try:
                    segments, info = local_model.transcribe(
                        final_audio_mono,
                        beam_size=CHUNK_BEAM_SIZE,
                        language=CHUNK_LANGUAGE if CHUNK_LANGUAGE else None,
                        vad_filter=CHUNK_VAD_FILTER,
                        initial_prompt=INITIAL_PROMPT or None
                    )
                except TypeError:
                    segments, info = local_model.transcribe(
                        final_audio_mono,
                        beam_size=CHUNK_BEAM_SIZE
                    )

                chunk_text_parts = []
                for segment in segments:
                    chunk_text_parts.append(safe_text_handling(segment.text, "final chunk segment"))
                chunk_text = " ".join(chunk_text_parts).strip()
                elapsed = time.time() - start_ts
                if LOG_CHUNK_DEBUG:
                    logger.info(f"Final chunk transcribed in {elapsed:.2f}s (text_len={len(chunk_text)}).")

                if chunk_text:
                    with chunk_transcript_lock:
                        chunk_transcript = _merge_transcripts(chunk_transcript, chunk_text)
            except Exception as e:
                # Don't hard-fail the app; we'll fall back to full-file transcription.
                chunk_transcript_error = e

    except Exception as e:
        chunk_transcript_error = e
    finally:
        if chunk_done_event is not None:
            try:
                chunk_done_event.set()
            except Exception:
                pass
        if LOG_CHUNK_DEBUG:
            logger.info("Chunk worker finished.")

def start_recording():
    """Start recording audio with safe file path handling"""
    global is_recording, recording_data, current_recording_file
    global chunk_queue, chunk_stop_event, chunk_thread, chunk_done_event
    global chunk_transcript, chunk_transcript_error, chunk_dropped_blocks, chunk_abort_short
    global last_recording_frames
    
    if is_recording:
        return
    
    try:
        # Clear previous recording data
        recording_data = []
        
        # Create a unique filename with safe path handling
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(recordings_dir, exist_ok=True)
        
        # Create filename with safe characters
        safe_filename = f"recording_{timestamp}.wav"
        current_recording_file = os.path.join(recordings_dir, safe_filename)
        
        # Ensure the file path is safe for Windows
        current_recording_file = safe_file_path(current_recording_file)
        
        logger.info(f"Starting recording to: {current_recording_file}")

        # Optionally start chunked transcription (only meaningful for local mode)
        chunk_queue = None
        chunk_stop_event = None
        chunk_thread = None
        chunk_done_event = None
        chunk_transcript_error = None
        chunk_dropped_blocks = 0
        chunk_abort_short = False
        last_recording_frames = 0
        with chunk_transcript_lock:
            chunk_transcript = ""

        if CHUNK_TRANSCRIBE and TRANSCRIPTION_MODEL == "local":
            # Bounded queue to avoid unbounded memory growth if transcription falls behind.
            chunk_queue = queue.Queue(maxsize=CHUNK_QUEUE_MAXSIZE)
            chunk_stop_event = threading.Event()
            chunk_done_event = threading.Event()
            chunk_thread = threading.Thread(
                target=_chunk_transcription_worker,
                args=(current_recording_file,),
                daemon=True
            )
            chunk_thread.start()
        
        # Show recording indicator
        show_indicator("recording")
        
        # Start recording
        is_recording = True
        print("Recording started... Press", HOTKEY, "again to stop.")
        
    except Exception as e:
        logger.error(f"Failed to start recording: {e}")
        print(f"Failed to start recording: {e}")
        # Reset state
        is_recording = False
        recording_data = []
        current_recording_file = None

def stop_recording():
    """Stop recording audio and save file with safe operations"""
    global is_recording, chunk_stop_event, chunk_abort_short, last_recording_frames
    
    if not is_recording:
        return
    
    try:
        # Stop recording
        is_recording = False
        if chunk_stop_event is not None:
            try:
                chunk_stop_event.set()
            except Exception:
                pass
        
        # Show transcribing indicator
        show_indicator("transcribing")
        
        print("Recording stopped.")
        
        if not recording_data:
            print("No audio data recorded.")
            # Reset state and show complete indicator
            if indicator_root:
                indicator_root.after(0, lambda: show_indicator("complete"))
            return
        
        # Convert list of arrays to single array
        recording_array = np.concatenate(recording_data, axis=0)
        last_recording_frames = len(recording_array)
        if CHUNK_TRANSCRIBE and TRANSCRIPTION_MODEL == "local":
            min_frames_for_chunk = max(1, int(CHUNK_SECONDS * SAMPLE_RATE))
            if last_recording_frames < min_frames_for_chunk:
                chunk_abort_short = True
        if LOG_CHUNK_DEBUG:
            logger.info(
                f"Recording stats: frames={last_recording_frames}, seconds={last_recording_frames / SAMPLE_RATE:.2f}, "
                f"chunk_abort_short={chunk_abort_short}"
            )
        
        # Save as WAV file with safe operations
        def save_wav_file(file_path):
            wavio.write(file_path, recording_array, SAMPLE_RATE, sampwidth=2)
        
        try:
            safe_file_operations(current_recording_file, save_wav_file)
            logger.info(f"Recording saved to {current_recording_file}")
            print(f"Recording saved to {current_recording_file}")
        except Exception as save_error:
            logger.error(f"Failed to save recording: {save_error}")
            print(f"Failed to save recording: {save_error}")
            # Show error indicator
            if indicator_root:
                indicator_root.after(0, lambda: show_error_indicator(f"Save failed: {str(save_error)}"))
            return
        
        # Start transcription in a separate thread
        threading.Thread(target=process_recording, args=(current_recording_file,), daemon=True).start()
        
    except Exception as e:
        logger.error(f"Error in stop_recording: {e}")
        print(f"Error stopping recording: {e}")
        # Ensure we're not stuck in recording state
        is_recording = False
        # Show error indicator
        if indicator_root:
            indicator_root.after(0, lambda: show_error_indicator(f"Stop recording error: {str(e)}"))

def process_recording(file_path):
    """Process the recording for transcription with comprehensive error handling"""
    global indicator_root, chunk_thread, chunk_transcript, chunk_transcript_error
    global chunk_done_event, chunk_dropped_blocks, chunk_abort_short
    global last_recording_frames
    
    try:
        logger.info(f"Starting transcription of file: {file_path}")
        logger.info(f"Using {TRANSCRIPTION_MODEL.upper()} model for transcription...")

        # If chunked transcription ran during recording, try to use it first for faster UX.
        if CHUNK_TRANSCRIBE and TRANSCRIPTION_MODEL == "local" and chunk_thread is not None:
            min_frames_for_chunk = max(1, int(CHUNK_SECONDS * SAMPLE_RATE))
            short_recording = last_recording_frames > 0 and last_recording_frames < min_frames_for_chunk
            if LOG_CHUNK_DEBUG:
                logger.info(
                    f"Chunk join decision: short_recording={short_recording}, frames={last_recording_frames}, "
                    f"min_frames_for_chunk={min_frames_for_chunk}, dropped_blocks={chunk_dropped_blocks}"
                )
            if short_recording:
                chunk_abort_short = True
            else:
                try:
                    join_start = time.time()
                    chunk_thread.join(timeout=CHUNK_FINALIZE_TIMEOUT_SECONDS)
                    if LOG_CHUNK_DEBUG:
                        logger.info(f"Chunk join waited {time.time() - join_start:.2f}s.")
                except Exception:
                    pass

            finished = False
            if chunk_done_event is not None:
                try:
                    finished = chunk_done_event.is_set()
                except Exception:
                    finished = False
            if not finished:
                try:
                    finished = not chunk_thread.is_alive()
                except Exception:
                    finished = False

            if chunk_transcript_error:
                logger.warning(f"Chunked transcription failed; falling back to full-file transcription: {chunk_transcript_error}")
            elif short_recording:
                logger.info("Chunked transcription skipped for short recording; using full-file transcription.")
            elif not finished:
                logger.warning("Chunked transcription did not finish in time; falling back to full-file transcription.")
            elif chunk_dropped_blocks > 0:
                logger.warning("Chunked transcription dropped audio blocks; falling back to full-file transcription.")
            else:
                with chunk_transcript_lock:
                    pre = (chunk_transcript or "").strip()
                if pre:
                    logger.info("Using chunked transcript (recording was transcribed during capture).")
                    transcription = pre
                    logger.info(f"Transcription completed successfully: {transcription[:100]}{'...' if len(transcription) > 100 else ''}")
                    if LOG_FULL_TRANSCRIPT:
                        logger.info(f"Full transcript (chunked):\n{transcription}")
                    # Deliver transcript immediately and skip full-file transcription.
                    copied = safe_clipboard_copy(transcription)
                    if not copied:
                        logger.warning("Clipboard failed; echoing transcript to terminal")
                        print("\n----- TRANSCRIPT BEGIN -----\n")
                        try:
                            print(transcription)
                        except Exception:
                            sys.stdout.write(transcription.encode('utf-8', 'replace').decode('utf-8'))
                            sys.stdout.write("\n")
                        print("------ TRANSCRIPT END ------\n")

                    if indicator_root:
                        indicator_root.after(0, lambda: show_indicator("complete"))
                    return
        
        # Perform transcription with timeout protection
        transcription = None
        transcription_error = None
        
        # Use a timeout to prevent hanging
        def transcription_worker():
            nonlocal transcription, transcription_error
            try:
                transcription = transcribe_audio(file_path)
            except Exception as e:
                transcription_error = e
        
        # Start transcription in a separate thread with timeout
        worker_thread = threading.Thread(target=transcription_worker, daemon=True)
        worker_thread.start()
        
        # Wait for transcription with timeout (5 minutes)
        worker_thread.join(timeout=300)
        
        if worker_thread.is_alive():
            # Transcription is taking too long, force stop
            logger.warning("Transcription timeout - forcing stop")
            transcription_error = Exception("Transcription timed out after 5 minutes")
        
        if transcription_error:
            raise transcription_error
        
        if not transcription or transcription.strip() == "":
            raise Exception("Transcription returned empty result")

        # Log successful transcription
        logger.info(f"Transcription completed successfully: {transcription[:100]}{'...' if len(transcription) > 100 else ''}")
        if LOG_FULL_TRANSCRIPT:
            logger.info(f"Full transcript:\n{transcription}")
        
        copied = safe_clipboard_copy(transcription)
        if not copied:
            logger.warning("Clipboard failed; echoing transcript to terminal")
            print("\n----- TRANSCRIPT BEGIN -----\n")
            try:
                print(transcription)
            except Exception as e:
                # Ultimate fallback with replacement to avoid crash
                sys.stdout.write(transcription.encode('utf-8', 'replace').decode('utf-8'))
                sys.stdout.write("\n")
            print("------ TRANSCRIPT END ------\n")
        
        # Show completion indicator
        if indicator_root:
            indicator_root.after(0, lambda: show_indicator("complete"))
        
    except Exception as e:
        # Log the full error with traceback
        error_msg = f"Error transcribing file {file_path}: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Full traceback: {traceback.format_exc()}")
        
        # Print user-friendly error message
        print(f"\n❌ Transcription Error: {str(e)}")
        print("Check the log file 'transcription_errors.log' for detailed information.")
        print("The script will continue running - you can try recording again.\n")
        
        # Show error indicator briefly
        if indicator_root:
            indicator_root.after(0, lambda: show_error_indicator(str(e)))
    
    finally:
        # Always ensure we're not stuck in transcribing state
        try:
            # Clean up the recording file if it exists and cleanup is enabled
            if DELETE_RECORDINGS and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up recording file: {file_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to clean up recording file {file_path}: {cleanup_error}")
        except Exception as cleanup_error:
            logger.warning(f"Error during cleanup: {cleanup_error}")
        
        # Reset any stuck state
        logger.info("Transcription process completed (success or failure)")

def show_error_indicator(error_message):
    """Show an error indicator briefly"""
    global indicator_root
    
    if not indicator_root:
        return
    
    try:
        # Create error indicator
        def create_error_indicator():
            # Get screen dimensions
            screen_width = indicator_root.winfo_screenwidth()
            screen_height = indicator_root.winfo_screenheight()
            
            # Set window size
            window_width = int(screen_width * 0.25)  # Wider for error messages
            window_height = int(screen_height * 0.08)
            
            # Ensure minimum size
            window_width = max(window_width, 200)
            window_height = max(window_height, 60)
            
            # Set position
            x_position = (screen_width - window_width) // 2
            y_position = screen_height - window_height - int(screen_height * 0.05)
            
            # Create error window
            error_top = tk.Toplevel(indicator_root)
            error_top.title("Transcription Error")
            error_top.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")
            error_top.configure(bg="#FF6B6B")  # Error red color
            error_top.overrideredirect(True)
            error_top.attributes("-topmost", True)
            
            # Add error icon and message
            error_frame = tk.Frame(error_top, bg="#FF6B6B")
            error_frame.pack(expand=True, fill="both", padx=10, pady=10)
            
            # Error icon
            error_icon = tk.Label(
                error_frame,
                text="❌",
                font=("Arial", 24, "bold"),
                fg="white",
                bg="#FF6B6B"
            )
            error_icon.pack(side="left", padx=(0, 10))
            
            # Error message (truncated if too long)
            display_error = error_message[:50] + "..." if len(error_message) > 50 else error_message
            error_label = tk.Label(
                error_frame,
                text=f"Error: {display_error}",
                font=("Arial", 12),
                fg="white",
                bg="#FF6B6B",
                wraplength=window_width - 80
            )
            error_label.pack(side="left", expand=True, fill="both")
            
            # Auto-close after 4 seconds
            error_top.after(4000, error_top.destroy)
            
            # Close any existing indicator
            if hasattr(indicator_root, 'current_indicator') and indicator_root.current_indicator:
                try:
                    if hasattr(indicator_root.current_indicator, "active"):
                        indicator_root.current_indicator.active = False
                    indicator_root.current_indicator.destroy()
                except:
                    pass
            
            indicator_root.current_indicator = error_top
        
        # Schedule the error indicator creation
        indicator_root.after(0, create_error_indicator)
        
    except Exception as e:
        logger.error(f"Failed to show error indicator: {e}")
        # Fallback: just show complete indicator to reset state
        if indicator_root:
            indicator_root.after(0, lambda: show_indicator("complete"))

def toggle_recording():
    """Toggle recording state"""
    global is_recording
    
    if is_recording:
        stop_recording()
    else:
        start_recording()

def reset_ui_state():
    """Reset the UI state if it gets stuck"""
    global indicator_root, indicator_status
    
    try:
        if indicator_root and hasattr(indicator_root, 'current_indicator'):
            current_indicator = indicator_root.current_indicator
            if current_indicator:
                try:
                    # Stop any active animations
                    if hasattr(current_indicator, "active"):
                        current_indicator.active = False
                    # Destroy the indicator
                    current_indicator.destroy()
                except Exception as destroy_error:
                    logger.warning(f"Failed to destroy indicator: {destroy_error}")
                
                # Reset the reference
                indicator_root.current_indicator = None
        
        # Reset status
        indicator_status = None
        
        # Show complete indicator to reset state
        if indicator_root:
            indicator_root.after(0, lambda: show_indicator("complete"))
            
        logger.info("UI state reset successfully")
        
    except Exception as e:
        logger.error(f"Failed to reset UI state: {e}")

def cleanup_old_recordings():
    """Delete old recording files to save disk space with error handling"""
    if not DELETE_RECORDINGS:
        return
        
    try:
        logger.info(f"Checking for old recordings (older than {MAX_RECORDING_AGE_DAYS} days)...")
        current_time = time.time()
        count = 0
        errors = 0
        
        if not os.path.exists(recordings_dir):
            logger.info("Recordings directory doesn't exist, skipping cleanup")
            return
        
        for file in os.listdir(recordings_dir):
            try:
                if file.endswith('.wav') or file.endswith('.m4a'):
                    file_path = os.path.join(recordings_dir, file)
                    
                    # Use safe file operations
                    def get_file_age(file_path):
                        return os.path.getmtime(file_path)
                    
                    try:
                        file_age_days = (current_time - safe_file_operations(file_path, get_file_age)) / (60 * 60 * 24)
                        
                        if file_age_days > MAX_RECORDING_AGE_DAYS:
                            # Use safe file operations for deletion
                            def delete_file(file_path):
                                os.remove(file_path)
                            
                            safe_file_operations(file_path, delete_file)
                            count += 1
                            
                    except Exception as age_error:
                        logger.warning(f"Could not determine age of {file}: {age_error}")
                        errors += 1
                        
            except Exception as file_error:
                logger.warning(f"Error processing file {file}: {file_error}")
                errors += 1
                
        if count > 0:
            logger.info(f"Cleaned up {count} old recording{'s' if count > 1 else ''}")
            print(f"Cleaned up {count} old recording{'s' if count > 1 else ''}")
        
        if errors > 0:
            logger.warning(f"Encountered {errors} error{'s' if errors > 1 else ''} during cleanup")
            
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        print(f"Warning: Error during cleanup: {e}")

def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Global exception handler to catch any unhandled exceptions"""
    if issubclass(exc_type, KeyboardInterrupt):
        # Don't log keyboard interrupts
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    # Log the error
    logger.critical("Unhandled exception occurred:", exc_info=(exc_type, exc_value, exc_traceback))
    
    # Print user-friendly message
    print(f"\n💥 Critical Error: {exc_value}")
    print("This error has been logged to 'transcription_errors.log'")
    print("Please check the log file for details and consider restarting the script.\n")
    
    # Try to reset the UI state if possible
    try:
        global indicator_root
        if indicator_root:
            indicator_root.after(0, lambda: show_indicator("complete"))
    except:
        pass

# Set the global exception handler
sys.excepthook = global_exception_handler

def safe_file_path(file_path):
    """Convert file path to safe format for Windows"""
    try:
        # Normalize the path and convert to absolute path
        abs_path = os.path.abspath(file_path)
        
        # Check if the path contains problematic characters
        try:
            abs_path.encode('mbcs')
            return abs_path
        except UnicodeEncodeError:
            # Path contains problematic characters, try to clean it
            logger.warning(f"File path contains problematic characters: {file_path}")
            
            # Try to use short path name (8.3 format) on Windows
            if platform.system() == "Windows":
                try:
                    import win32api
                    short_path = win32api.GetShortPathName(abs_path)
                    logger.info(f"Converted to short path: {short_path}")
                    return short_path
                except Exception as short_path_error:
                    logger.warning(f"Failed to get short path: {short_path_error}")
            
            # Fallback: try to encode with replacement
            try:
                safe_path = abs_path.encode('mbcs', errors='replace').decode('mbcs')
                logger.info(f"Cleaned path using replacement: {safe_path}")
                return safe_path
            except Exception as encode_error:
                logger.error(f"Failed to clean path: {encode_error}")
                # Last resort: return a safe filename
                safe_filename = f"recording_{int(time.time())}.wav"
                safe_dir = os.path.dirname(abs_path)
                return os.path.join(safe_dir, safe_filename)
                
    except Exception as e:
        logger.error(f"Error processing file path {file_path}: {e}")
        # Return a completely safe fallback path
        fallback_dir = os.path.expanduser("~/Documents/Sound Recordings")
        fallback_filename = f"recording_{int(time.time())}.wav"
        return os.path.join(fallback_dir, fallback_filename)

def safe_file_operations(file_path, operation_func):
    """Safely perform file operations with encoding error handling"""
    try:
        # Try with original path first
        return operation_func(file_path)
    except UnicodeEncodeError as e:
        logger.warning(f"Unicode encoding error with file path: {e}")
        
        # Try with safe path
        safe_path = safe_file_path(file_path)
        if safe_path != file_path:
            logger.info(f"Retrying with safe path: {safe_path}")
            try:
                return operation_func(safe_path)
            except Exception as retry_error:
                logger.error(f"Failed with safe path: {retry_error}")
                raise Exception(f"File operation failed even with safe path: {retry_error}")
        else:
            raise Exception(f"Could not create safe file path: {e}")
    except Exception as e:
        logger.error(f"File operation error: {e}")
        raise

def main():
    """Main function with comprehensive error handling"""
    try:
        # Clean up old recordings first
        cleanup_old_recordings()
        
        # Set up recording stream
        stream = sd.InputStream(
            callback=audio_callback,
            channels=1,
            samplerate=SAMPLE_RATE
        )
        
        # Create recordings directory if it doesn't exist
        os.makedirs(recordings_dir, exist_ok=True)
        
        print(f"Starting transcription service using {TRANSCRIPTION_MODEL.upper()} model...")
        print(f"Press {HOTKEY} to start/stop recording.")
        print("Press Ctrl+Shift+R to reset UI state if it gets stuck.")
        print("Press Ctrl+C in the console or close the window to exit.")
        print("Error logs will be saved to 'transcription_errors.log'")
        
        # Start the Win32 hotkey listener thread
        listener = threading.Thread(target=hotkey_listener_thread, daemon=True)
        listener.start()
        
        # Start the recording stream
        with stream:
            try:
                # Keep the program running while listener is alive
                while listener.is_alive():
                    time.sleep(1)
                    
                # If the listener thread dies unexpectedly, we might end up here
                logger.warning("Hotkey listener thread seems to have stopped.")
                print("Hotkey listener thread stopped unexpectedly.")
                
            except KeyboardInterrupt:
                print("Ctrl+C detected. Exiting...")
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                print(f"Unexpected error: {e}")
                print("Check the log file for details.")
            finally:
                # Clean up
                if is_recording:
                    try:
                        if indicator_root:
                            indicator_root.after(0, stop_recording)
                        else:
                            stop_recording()
                    except Exception as cleanup_error:
                        logger.error(f"Error during cleanup: {cleanup_error}")
                print("Service stopped.")
                
    except Exception as e:
        logger.critical(f"Critical error during startup: {e}")
        print(f"Critical startup error: {e}")
        print("Check the log file for details.")
        raise

if __name__ == "__main__":
    main() 

import os
import time
import requests
import threading
from datetime import datetime
import win32clipboard
import keyboard
import pyautogui
import numpy as np
import sounddevice as sd
import wavio
from dotenv import load_dotenv
import tkinter as tk
import platform
import ctypes

# Load environment variables from .env file
load_dotenv()

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

# Global variables for recording
is_recording = False
recording_data = []
current_recording_file = None
indicator_status = None  # Current status of the indicator
indicator_root = None    # Root tkinter window for the indicator
   
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
        current_color_table = getattr(top, "hover_color_table", top.color_table)
        current_bg = getattr(top, "hover_bg_color", top.bg_color)
        
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
        )
        
        if response.status_code == 200:
            return response.json()["text"]
        else:
            raise Exception(f"Error {response.status_code}: {response.text}")

def transcribe_audio_openai(file_path):
    """Transcribe audio using OpenAI's Whisper"""
    with open(file_path, "rb") as audio_file:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    return transcript.text

def transcribe_audio_local(file_path):
    """Transcribe audio using local Whisper model"""
    print("Transcribing with local model...")
    
    try:
        # Perform transcription
        segments, info = local_model.transcribe(file_path, beam_size=5)
        
        # Combine all segments
        transcript = " ".join([segment.text for segment in segments])
        
        print(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        return transcript
    except Exception as e:
        raise Exception(f"Local model transcription error: {str(e)}")

def transcribe_audio(file_path):
    """Transcribe audio using the configured model"""
    if TRANSCRIPTION_MODEL == "fireworks":
        return transcribe_audio_fireworks(file_path)
    elif TRANSCRIPTION_MODEL == "openai":
        return transcribe_audio_openai(file_path)
    else:
        return transcribe_audio_local(file_path)

def copy_to_clipboard(text):
    """Copy text to Windows clipboard"""
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text)
    win32clipboard.CloseClipboard()

def paste_text():
    """Paste text at current cursor position"""
    pyautogui.hotkey('ctrl', 'v')

def audio_callback(indata, frames, time, status):
    """Callback function for audio recording"""
    if status:
        print(f"Status: {status}")
    if is_recording:
        recording_data.append(indata.copy())

def start_recording():
    """Start recording audio"""
    global is_recording, recording_data, current_recording_file
    
    if is_recording:
        return
    
    # Clear previous recording data
    recording_data = []
    
    # Create a unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(recordings_dir, exist_ok=True)
    current_recording_file = os.path.join(recordings_dir, f"recording_{timestamp}.wav")
    
    # Show recording indicator
    show_indicator("recording")
    
    # Start recording
    is_recording = True
    print("Recording started... Press", HOTKEY, "again to stop.")

def stop_recording():
    """Stop recording audio and save file"""
    global is_recording
    
    if not is_recording:
        return
    
    # Stop recording
    is_recording = False
    
    # Show transcribing indicator
    show_indicator("transcribing")
    
    print("Recording stopped.")
    
    if not recording_data:
        print("No audio data recorded.")
        return
    
    # Convert list of arrays to single array
    recording_array = np.concatenate(recording_data, axis=0)
    
    # Save as WAV file
    wavio.write(current_recording_file, recording_array, SAMPLE_RATE, sampwidth=2)
    print(f"Recording saved to {current_recording_file}")
    
    # Start transcription in a separate thread
    threading.Thread(target=process_recording, args=(current_recording_file,)).start()

def process_recording(file_path):
    """Process the recording for transcription"""
    try:
        print(f"Transcribing file: {file_path}")
        print(f"Using {TRANSCRIPTION_MODEL.upper()} model for transcription...")
        
        transcription = transcribe_audio(file_path)
        print(f"Transcription: {transcription}\n")
        
        # Copy to clipboard and paste
        copy_to_clipboard(transcription)
        paste_text()
        
        # Show completion indicator (will auto-close after 4 seconds)
        show_indicator("complete")
        
    except Exception as e:
        print(f"Error transcribing: {str(e)}\n")
       
def toggle_recording():
    """Toggle recording state"""
    global is_recording
    
    if is_recording:
        stop_recording()
    else:
        start_recording()

def cleanup_old_recordings():
    """Delete old recording files to save disk space"""
    if not DELETE_RECORDINGS:
        return
        
    try:
        print(f"Checking for old recordings (older than {MAX_RECORDING_AGE_DAYS} days)...")
        current_time = time.time()
        count = 0
        
        for file in os.listdir(recordings_dir):
            if file.endswith('.wav') or file.endswith('.m4a'):
                file_path = os.path.join(recordings_dir, file)
                file_age_days = (current_time - os.path.getmtime(file_path)) / (60 * 60 * 24)
                
                if file_age_days > MAX_RECORDING_AGE_DAYS:
                    os.remove(file_path)
                    count += 1
                    
        if count > 0:
            print(f"Cleaned up {count} old recording{'s' if count > 1 else ''}")
    except Exception as e:
        print(f"Error during cleanup: {e}")

def main():
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
    
    # Register hotkey
    keyboard.add_hotkey(HOTKEY, toggle_recording)
    
    # Start the recording stream
    with stream:
        try:
            # Keep the program running
            print("Waiting for hotkey press...")
            keyboard.wait('esc')  # Wait until ESC is pressed to exit
        except KeyboardInterrupt:
            pass
        finally:
            # Clean up
            if is_recording:
                stop_recording()
            keyboard.unhook_all()
            print("Service stopped.")

if __name__ == "__main__":
    main() 
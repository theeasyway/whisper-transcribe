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
from win10toast import ToastNotifier
from dotenv import load_dotenv

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
        "distil-large-v3", "large-v3-turbo", "turbo"
    ]
    
    # Look for existing model files
    found_models = []
    try:
        # Check for models in the Hugging Face cache format
        for root, dirs, files in os.walk(LOCAL_MODEL_PATH):
            if "model.bin" in files:
                # Try to extract model size from path or folder name
                path_lower = root.lower()
                
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
        
        # Check if our specified model exists in the found models
        if DEFAULT_MODEL_SIZE in found_models:
            # Use the specified model
            local_model_name = DEFAULT_MODEL_SIZE
            print(f"Using specified model: {DEFAULT_MODEL_SIZE}")
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
                    local_model = WhisperModel(local_model_name, device="cuda", compute_type="float16", download_root=LOCAL_MODEL_PATH)
                else:
                    print("CUDA not available, falling back to CPU")
                    local_model = WhisperModel(local_model_name, device="cpu", compute_type="int8", download_root=LOCAL_MODEL_PATH)
            except Exception as e:
                print(f"GPU acceleration failed, falling back to CPU: {e}")
                local_model = WhisperModel(local_model_name, device="cpu", compute_type="int8", download_root=LOCAL_MODEL_PATH)
        else:
            # Directly use CPU
            local_model = WhisperModel(local_model_name, device="cpu", compute_type="int8", download_root=LOCAL_MODEL_PATH)
            print("Using CPU for inference (GPU disabled in config)")
            
        print("Model loaded successfully")
    except Exception as e:
        raise Exception(f"Failed to load model: {e}")

# Specify the directory where your recordings are saved
recordings_dir = os.path.expanduser("~/Documents/Sound Recordings")

# Global toaster instance to prevent garbage collection issues
toaster = ToastNotifier()

# Global variables for recording
is_recording = False
recording_data = []
current_recording_file = None

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

def show_toast(title, message, notification_type=None):
    """Show Windows toast notification with emojis for visual differentiation"""
    try:
        # Add appropriate emoji prefix based on notification type
        if notification_type == "recording":
            emoji_title = "🔴 " + title  # Red circle for recording
        elif notification_type == "transcription":
            emoji_title = "✅ " + title  # Green checkmark for completion
        elif notification_type == "error":
            emoji_title = "❌ " + title  # Red X for errors
        else:
            emoji_title = title
            
        toaster.show_toast(emoji_title, message, duration=5, threaded=True)
    except Exception as e:
        print(f"Notification error: {str(e)}")

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
    
    # Start recording
    is_recording = True
    print("Recording started... Press", HOTKEY, "again to stop.")
    show_toast("Recording", "Recording started. Press the same key again to stop.", notification_type="recording")

def stop_recording():
    """Stop recording audio and save file"""
    global is_recording, recording_data, current_recording_file
    
    if not is_recording:
        return
    
    # Stop recording
    is_recording = False
    print("Recording stopped.")
    
    if not recording_data:
        print("No audio data recorded.")
        show_toast("Recording Error", "No audio data recorded.")
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
        
        show_toast("Transcription Complete", 
          "The transcription has been pasted at cursor position.", 
          notification_type="transcription")
    except Exception as e:
        print(f"Error transcribing: {str(e)}\n")
        show_toast("Transcription Error", "Error transcribing recording", notification_type="error")

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
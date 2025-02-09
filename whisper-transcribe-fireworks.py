import os
import time
import requests
import win32clipboard
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from win10toast import ToastNotifier
import threading
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up the Fireworks AI API key
api_key = os.getenv("FIREWORKS_API_KEY")
if not api_key:
    raise ValueError("FIREWORKS_API_KEY not found in .env file")

# Specify the directory where your recordings are saved
recordings_dir = os.path.expanduser("~/Documents/Sound Recordings")

def transcribe_audio(file_path):
    with open(file_path, "rb") as audio_file:
        response = requests.post(
            "https://audio-turbo.us-virginia-1.direct.fireworks.ai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
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

def copy_to_clipboard(text):
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text)
    win32clipboard.CloseClipboard()

# Global toaster instance to prevent garbage collection issues
toaster = ToastNotifier()

def show_toast(title, message):
    try:
        # Use the global toaster instance
        toaster.show_toast(title, message, duration=5, threaded=True)
    except Exception as e:
        print(f"Notification error: {str(e)}")  # Just log the error and continue

class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.m4a'):
            filename = os.path.basename(event.src_path)
            if "autosaved" not in filename.lower():
                print(f"New recording detected: {filename}")
                
                # Wait and check if file size has stabilized
                last_size = -1
                current_size = 0
                while last_size != current_size:
                    last_size = current_size
                    time.sleep(1)
                    try:
                        current_size = os.path.getsize(event.src_path)
                    except:
                        continue
                
                try:
                    transcription = transcribe_audio(event.src_path)
                    print(f"Transcription: {transcription}\n")
                    copy_to_clipboard(transcription)
                    show_toast("Transcription Complete", 
                             "The transcription has been copied to your clipboard.")
                except Exception as e:
                    print(f"Error transcribing {filename}: {str(e)}\n")
                    show_toast("Transcription Error", 
                             f"Error transcribing {filename}")

def main():
    # Create recordings directory if it doesn't exist
    os.makedirs(recordings_dir, exist_ok=True)
    
    event_handler = NewFileHandler()
    observer = Observer()
    observer.schedule(event_handler, recordings_dir, recursive=False)
    observer.start()
    print(f"Watching for new recordings in {recordings_dir}...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main() 
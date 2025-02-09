import os
import time
from openai import OpenAI
import win32clipboard
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from win10toast import ToastNotifier
import threading
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up the OpenAI client with API key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY not found in .env file")
client = OpenAI(api_key=api_key)

# Specify the directory where your recordings are saved
recordings_dir = os.path.expanduser("~/Documents/Sound Recordings")

def transcribe_audio(file_path):
    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    return transcript.text

def copy_to_clipboard(text):
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text)
    win32clipboard.CloseClipboard()

def show_toast(title, message):
    def show_toast_thread():
        try:
            toaster = ToastNotifier()
            toaster.show_toast(title, message, duration=5, threaded=True)
        except Exception as e:
            print(f"Notification error: {str(e)}")  # Just log the error and continue

    # Run the toast notification in a separate thread
    threading.Thread(target=show_toast_thread, daemon=True).start()  # Make it daemon thread

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
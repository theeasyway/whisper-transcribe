# Voice-to-Text Transcription Tool

A streamlined audio transcription tool that uses hotkeys to record and automatically transcribe voice to text using local Whisper models.

## Features

- 🎙️ **Hotkey Recording**: Press a customizable hotkey to start/stop recording
- 🤖 **Local Whisper Models**: Free, offline transcription with no API costs
- 📋 **Automatic Pasting**: Transcriptions are automatically pasted at cursor position
- 🔔 **Desktop Notifications**: Visual feedback on recording/transcription status
- 🌐 **No Internet Required**: Works completely offline
- 🧹 **Auto-cleanup**: Manages recording files to save disk space

## Quick Start

1. Install requirements:
   ```
   pip install -r requirements.txt
   ```

2. Create a `.env` file (copy from `.env.example`) or use default settings

3. Run the script:
   ```
   python audio_transcription.py
   ```

4. Press F9 (default) to start recording
5. Press F9 again to stop recording and trigger transcription
6. The transcription will be pasted at your cursor position

The first time you run with local mode, it will automatically download a small English model (~500MB).

## Using Local Models

The script uses local Whisper models by default, giving you:
- Free transcription (no API costs)
- Complete privacy (your audio never leaves your computer)
- Excellent accuracy
- Fast performance even on CPU

Available model sizes for automatic download:
- `tiny.en` (~75MB) - Very fast, less accurate
- `base.en` (~150MB) - Fast, moderate accuracy
- `small.en` (~500MB) - Good balance (default)
- `medium.en` (~1.5GB) - Higher accuracy, slower
- `large-v3` (~3GB) - Best accuracy, slowest

For English-only tasks, the `.en` models provide better performance.

## Configuration Options

All configuration is done through environment variables (`.env` file):

| Variable | Description | Default |
|----------|-------------|---------|
| `TRANSCRIPTION_MODEL` | The transcription backend to use | `"local"` |
| `DEFAULT_MODEL_SIZE` | Which model to download if none found | `"small.en"` |
| `RECORDING_HOTKEY` | Hotkey to start/stop recording | `"f9"` |
| `DELETE_RECORDINGS` | Whether to auto-delete old recordings | `"true"` |
| `MAX_RECORDING_AGE_DAYS` | How old recordings must be to delete | `"7"` |
| `LOCAL_MODEL_PATH` | Directory for local models | `"models"` |
| `USE_GPU` | Enable GPU acceleration (requires CUDA) | `"false"` |
| `FIREWORKS_API_KEY` | API key for Fireworks AI | |
| `OPENAI_API_KEY` | API key for OpenAI | |

## Using Local Models

When using the local model option:

1. Set `TRANSCRIPTION_MODEL="local"` in your `.env` file
2. The script will:
   - Look for model files in the `LOCAL_MODEL_PATH` directory
   - If found, use the first model file it sees
   - If not found, automatically download the model specified by `DEFAULT_MODEL_SIZE`

Available model sizes for automatic download:
- `tiny.en` (~75MB) - Very fast, less accurate
- `base.en` (~150MB) - Fast, moderate accuracy
- `small.en` (~500MB) - Good balance (default)
- `medium.en` (~1.5GB) - Higher accuracy, slower
- `large-v3` (~3GB) - Best accuracy, slowest

For English-only tasks, the `.en` models provide better performance.

### Automatic File Management

To prevent accumulating large numbers of recording files, the script:
1. Automatically deletes recordings older than 7 days by default
2. You can adjust this behavior with:
   - `DELETE_RECORDINGS="false"` - Keep all recordings
   - `MAX_RECORDING_AGE_DAYS="30"` - Keep recordings for 30 days

### GPU Acceleration (Optional)

By default, the script uses CPU mode which works well for most users. If you have a CUDA-compatible GPU and want to use it:

1. Ensure you have CUDA and cuDNN properly installed
2. Set `USE_GPU="true"` in your `.env` file

### Cloud API Options (Alternative)

While local models are recommended, the script still supports cloud APIs as alternatives:

1. Set `TRANSCRIPTION_MODEL="openai"` or `TRANSCRIPTION_MODEL="fireworks"` 
2. Add the corresponding API key to your `.env` file

This can be useful if you need the highest accuracy or support for many languages.

## Exit the Application

Press ESC to exit the application.

## Dependencies

- `faster-whisper`: Local Whisper model implementation
- `sounddevice` & `wavio`: Audio recording
- `keyboard`: Hotkey support
- `pyautogui`: Auto-pasting functionality
- `openai` & `requests`: API clients for cloud services
- `win10toast`: Windows notifications
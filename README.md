# Audio Transcription Scripts For Windows Using OpenAI Whisper

Automatic audio transcription scripts designed to work seamlessly with Windows Sound Recorder, providing a lightweight solution for quick voice-to-text on Windows. The scripts watch for new recordings and transcribe them using either OpenAI's Whisper or Whisper Turbo model. The transcriptions are automatically copied to your clipboard and a notification is shown when complete.

## Quick Start with Windows Sound Recorder

1. Press `Windows + R`, type `windowssoundrecorder`, and press Enter to open Windows Sound Recorder
2. Start the transcription script: `python whisper-transcribe-combined.py`
3. Record your audio in Windows Sound Recorder and stop recording (Windows Sound Recorder will automatically save to `\Users\[YourUsername]\Documents\Sound Recordings`)
4. The transcription will automatically appear in your clipboard!

This provides a very lightweight way to get high-quality transcription Whisper-based working on Windows without needing to install complex apps or services.

## Features

- 🎯 **Auto-Detection**: Automatically detects new `.m4a` audio recordings
- 📋 **Clipboard Integration**: Transcriptions are automatically copied to clipboard
- 🔔 **Desktop Notifications**: Shows Windows toast notifications for completion/errors
- 🔄 **Two Model Options**: 
  - OpenAI Whisper via OpenAI API (slightly higher accuracy)
  - OpenAI Whisper Turbo via Fireworks AI API (significantly faster processing, cheaper) << RECOMMENDED & DEFAULT

## Prerequisites

- Python 3.7+
- Windows OS (for toast notifications and clipboard functionality)
- API key for either OpenAI or Fireworks AI (or both)

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <repository-name>
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root and add your API key(s):
   ```env
   # Required: At least one of these API keys
   FIREWORKS_API_KEY="your-fireworks-api-key"
   OPENAI_API_KEY="your-openai-api-key"
   
   # Optional: Choose which model to use (defaults to "fireworks" if not set)
   # TRANSCRIPTION_MODEL="fireworks"  # Use Fireworks AI's Whisper Turbo (faster, cheaper)
   # TRANSCRIPTION_MODEL="openai"     # Use OpenAI's Whisper (slightly more accurate)
   ```

## Usage

Run the script:
```bash
python whisper-transcribe-combined.py
```

The script will:
1. Watch the "Sound Recordings" folder in your Documents
2. Detect new `.m4a` files
3. Transcribe the audio using your chosen model (Fireworks Turbo by default)
4. Copy the transcription to your clipboard
5. Show a notification when complete

## Directory Structure

```
.
├── .env                           # API keys and configuration (not in repo)
├── .gitignore                     # Git ignore file
├── README.md                      # This file
├── requirements.txt               # Python dependencies
└── whisper-transcribe-combined.py # Main script
```

## Configuration

By default, the scripts watch `\Users\[YourUsername]\Documents\Sound Recordings` for new `.m4a` files. This is the default save location for Windows Sound Recorder, so everything works seamlessly without any configuration. The directory is created automatically if it doesn't exist.

## Dependencies

- `openai`: OpenAI API client
- `requests`: HTTP client for Fireworks AI
- `watchdog`: File system events monitoring
- `win10toast`: Windows notifications
- `pywin32`: Windows clipboard operations
- `python-dotenv`: Environment variable management

## Error Handling

- The scripts will show notifications for both successful transcriptions and errors
- File system errors and API errors are caught and reported
- Transcription errors won't crash the script - it will continue watching for new files

## Security Notes

- Keep your `.env` file secure and never commit it to version control
- The `.gitignore` file is configured to exclude sensitive files
- API keys are loaded securely from environment variables

## Contributing

Feel free to open issues or submit pull requests for improvements. 
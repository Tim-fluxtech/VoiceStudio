# Twelve Twelve Labs: modification notice

Twelve Twelve Labs is a modified version of **VoiceStudio**, created by
Palash Debnath and the VoiceStudio contributors
(https://github.com/debpalash/VoiceStudio), and is distributed under the
**GNU Affero General Public License v3.0** (see `LICENSE`). The original
copyright and licence notices are preserved. This notice records the
modifications, as AGPL-3.0 section 5(a) requires.

Modified from VoiceStudio 0.5.7-beta.2 on 2026-10-25:

- Product name and app identifier changed to "Twelve Twelve Labs"
  (`config/app.json`, user-interface strings in all locale files).
- Default speech engine on Apple Silicon changed from OmniVoice to the
  Apache-licensed MLX engines (Kokoro and CSM), because the OmniVoice weights
  are licensed for non-commercial use only
  (`backend/services/tts_backend.py`).
- Kokoro preset voices are now selectable through `POST /generate`
  (`backend/services/tts_backend.py`).
- MLX Whisper falls back to the installed Turbo model when large-v3 is not
  installed (`backend/services/asr_backend.py`).
- Added `tools/twelve_speak.py`: sentence-by-sentence voice cloning with an
  automatic speech-to-text check.

Model weights keep their own licences. This application's licence does not
grant rights under those terms; review each model's licence before commercial
use. Note: the OmniVoice weights are non-commercial.

If you offer a modified version of this program to others over a network, AGPL-3.0
section 13 requires you to offer them the corresponding source code.

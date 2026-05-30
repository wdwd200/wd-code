# Mini CLI Assistant

A minimal command line assistant demo that talks to an OpenAI-compatible chat completions API.

## Usage

Edit `model_config.json` first:

```json
{
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "model": "gpt-4.1-mini"
}
```

Then run from the project directory in Windows cmd:

```cmd
wdcode
```

In PowerShell, Windows requires the current-directory prefix:

```powershell
.\wdcode
```

You can still run directly with command line config:

```powershell
python .\src\wdcode\cli\main.py --base-url https://api.openai.com/v1 --api-key sk-... --model gpt-4.1-mini
```

Or use environment variables:

```powershell
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_MODEL="gpt-4.1-mini"
python .\src\wdcode\cli\main.py
```

Save config back to `model_config.json`:

```powershell
python .\src\wdcode\cli\main.py --base-url https://api.openai.com/v1 --api-key sk-... --model gpt-4.1-mini --save-config
```

Inside the CLI, type `/exit` or `/quit` to stop.

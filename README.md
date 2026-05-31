# claude-code-print-skill

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill for printing PDF files to Windows printers with automatic duplex and color control.

## Features

- **Auto-discovery** of physical printers (filters out virtual printers like PDF, XPS, Fax)
- **Capability detection** — queries each printer for duplex and color support
- **Triple-layer duplex/color control** via .NET API + Win32 DevMode + DefaultPageSettings
- **Image-based rendering** — converts PDF pages to PNG via PyMuPDF, then prints images through the Windows spooler (avoids raw-byte garbled output)
- **CLI and Skill modes** — usable standalone or as a Claude Code skill

## Prerequisites

- Windows 10/11
- Python 3.10+ with `pymupdf` and `Pillow`
- .NET Framework 4.x (provides `csc.exe`)
- At least one physical printer installed

## Install

```bash
pip install pymupdf Pillow
```

## Usage

### CLI

```bash
# List available printers with capabilities
python scripts/print.py --list

# Print with defaults (auto-detect printer, duplex vertical, mono)
python scripts/print.py document.pdf

# Print to specific printer with custom settings
python scripts/print.py document.pdf --printer "HP M401dn" --duplex vertical --color mono

# High-quality rendering
python scripts/print.py document.pdf --dpi 300 --color color
```

### Claude Code Skill

Copy or symlink this directory into your Claude Code skills folder:

```bash
# Option 1: Symlink
mklink /D "%USERPROFILE%\.claude\skills\print" "<path-to-this-repo>"

# Option 2: Copy
xcopy /E /I "<path-to-this-repo>" "%USERPROFILE%\.claude\skills\print"
```

Then in Claude Code, type `/print` or say "打印这个PDF".

## How It Works

```
PDF → pymupdf (render @200 DPI) → PNG images → PrintEngine.cs (compiled) → Windows Print Spooler → Printer
```

The triple-layer setting ensures duplex and color preferences are respected:

1. **.NET API**: `PrinterSettings.Duplex` / `SupportsColor`
2. **Win32 DevMode**: `DocumentProperties()` with `dmDuplex` and `dmColor` fields
3. **Confirmation**: `DefaultPageSettings.PrinterSettings.Duplex` reapplied

## Options

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--printer, -p` | Printer name | Auto-detect | Target printer |
| `--duplex, -d` | `simplex`, `vertical`, `horizontal` | `vertical` | Duplex mode |
| `--color, -c` | `mono`, `color` | `mono` | Color mode |
| `--dpi` | Integer | `200` | Render resolution |
| `--list` | — | — | List printers and exit |

## Troubleshooting

- **Garbled output**: Should not occur with this tool (uses image-based printing, not raw bytes)
- **Single-sided despite duplex setting**: Ensure printer hardware supports auto-duplex; check with `--list`
- **Printer not found**: Add it via Windows Settings or `Add-PrinterPort` + `Add-Printer`

## License

MIT

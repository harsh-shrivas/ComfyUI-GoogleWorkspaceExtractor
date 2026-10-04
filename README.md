# ComfyUI-GoogleWorkspaceExtractor

An AI-powered data extraction and production pipeline node for ComfyUI that parses Google Docs and Google Sheets into clean, structured deliverables using the official Google Gemini API.

Built for creative studios, VFX pipelines, and content automation teams to bridge live client production tracking sheets and briefs directly into ComfyUI node graphs without manual copy-pasting.

---

## Features

- **Dual Workspace Ingestion:** Direct support for both Google Docs tables/text exports and Google Sheets grid data.
- **AI-Driven Data Structuring:** Leverages Google Gemini (`google-genai` SDK) to parse complex brief tables, identify deliverable types (Carousels, Statics, UGC/Reels), count slides, and map upload dates.
- **Deep Anchor & Hyperlink Resolution:** Extracts live cell URLs, heading anchors (`#heading=...`), and internal bookmark IDs so every item links directly to its section in the source document.
- **Automated Production Summary:** Generates a structured overview header tallying total deliverables, post formats, and total slide counts before the itemized breakdown.
- **Pipeline-Ready Output:** Outputs pure Markdown-formatted lists compatible with downstream LLMs, prompt generators, and documentation pushers.

---

## Installation

1. Navigate to your ComfyUI custom nodes directory: `cd ComfyUI/custom_nodes`
2. Clone this repository: `git clone https://github.com/harsh-shrivas/ComfyUI-GoogleWorkspaceExtractor.git`
3. Install required dependencies: `pip install google-genai`
4. Restart ComfyUI.

---

## Usage

- **Category:** `Automation/Data Extraction`
- **Node Name:** `Google Workspace Extractor Node`
- **Workflow:**
  1. Set your Google Doc or Google Sheet link sharing to **"Anyone with the link can view"**.
  2. Paste the URL into `google_link`.
  3. Enter your Gemini API Key in `gemini_api_key`.
  4. Specify the target section header or sheet tab in `target_tab` (defaults to `Grid Reference [For Design Team]`).
  5. Click **Queue Prompt**. The node will parse the document, run extraction via Gemini, and output the formatted report.

---

## Inputs & Outputs

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **google_link** | `STRING` (Input) | `""` | Public Google Doc or Google Sheet URL |
| **gemini_api_key** | `STRING` (Input) | `""` | Google Gemini API Key |
| **target_tab** | `STRING` (Optional) | `Grid Reference [For Design Team]` | Section header or sheet tab name to parse |
| **extracted_content** | `STRING` (Output) | — | Structured summary and itemized markdown list |

---

## License

MIT License. Free to use, adapt, and deploy across automated pipelines and studio workflows.

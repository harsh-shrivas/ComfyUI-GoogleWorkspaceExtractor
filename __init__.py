import re
import json
import time
import zipfile
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from io import BytesIO
from html.parser import HTMLParser
from google import genai

class DocHTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.current_cell = []
        self.current_href = ""
        self.current_anchor = ""
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag in ["td", "th"]:
            self.in_cell = True
            self.current_cell = []
            if "id" in attr_dict:
                self.current_anchor = attr_dict["id"]
        elif tag == "a":
            if "href" in attr_dict:
                href = attr_dict["href"]
                # Clean up Google's redirect proxy wrappers if present
                if "/url?q=" in href:
                    href = href.split("/url?q=")[1].split("&")[0]
                self.current_href = href
            if "name" in attr_dict and not self.current_anchor:
                self.current_anchor = attr_dict["name"]
            elif "id" in attr_dict and not self.current_anchor:
                self.current_anchor = attr_dict["id"]

    def handle_endtag(self, tag):
        if tag in ["td", "th"]:
            self.in_cell = False
            cell_text = " ".join(self.current_cell).strip()
            self.current_row.append({
                "text": cell_text,
                "href": self.current_href,
                "anchor": self.current_anchor
            })
            self.current_cell = []
            self.current_href = ""
            self.current_anchor = ""
        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
                self.current_row = []

    def handle_data(self, data):
        if self.in_cell:
            text = data.strip()
            if text:
                self.current_cell.append(text)


class GoogleWorkspaceExtractorNode:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "google_link": ("STRING", {"default": "", "multiline": False}),
                "gemini_api_key": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "target_tab": ("STRING", {"default": "Grid Reference [For Design Team]", "multiline": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("extracted_content",)
    FUNCTION = "process_workspace_link"
    OUTPUT_NODE = True
    CATEGORY = "Automation/Data Extraction"

    def process_workspace_link(self, google_link, gemini_api_key, target_tab="Grid Reference [For Design Team]"):
        try:
            clean_link = google_link.strip()
            if not clean_link:
                return ("No Google Workspace link provided.",)

            api_key = gemini_api_key.strip()
            if not api_key:
                return ("Please provide a valid Gemini API Key.",)

            client = genai.Client(api_key=api_key)

            if "docs.google.com/document" in clean_link:
                return self._process_google_doc(clean_link, client, target_tab)
            elif "docs.google.com/spreadsheets" in clean_link:
                return self._process_google_sheet(clean_link)
            else:
                return ("Invalid Google Workspace link provided.",)
        except Exception as top_e:
            return (f"Execution Failed: {str(top_e)}",)

    def _get_active_models(self, client):
        try:
            live_models = [m.name.replace("models/", "") for m in client.models.list() if "generateContent" in getattr(m, "supported_generation_methods", ["generateContent"])]
            preferred_order = [
                "gemini-3.1-flash-lite",
                "gemini-3.6-flash",
                "gemini-3.8-flash",
                "gemini-2.5-flash",
                "gemini-flash-latest"
            ]
            ordered = [m for m in preferred_order if m in live_models]
            for m in live_models:
                if m not in ordered:
                    ordered.append(m)
            return ordered if ordered else ["gemini-3.1-flash-lite"]
        except Exception:
            return ["gemini-3.1-flash-lite", "gemini-2.5-flash"]

    def _clean_title_string(self, text):
        if not text:
            return ""
        clean = str(text).replace("\r", " ").replace("\n", " ")
        clean = re.sub(r'\s*-\s*', ' - ', clean)
        clean = re.sub(r'[ \t]+', ' ', clean)
        return clean.strip()

    def _call_gemini_bulletproof(self, client, prompt):
        active_models = self._get_active_models(client)
        last_exception = None

        for model in active_models:
            for attempt in range(3):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config={"response_mime_type": "application/json"}
                    )
                    raw_text = response.text.strip()
                    raw_text = re.sub(r'^```(?:json)?', '', raw_text, flags=re.MULTILINE)
                    raw_text = re.sub(r'```$', '', raw_text, flags=re.MULTILINE).strip()
                    return json.loads(raw_text)
                except Exception as e:
                    last_exception = e
                    err_msg = str(e)
                    if "503" in err_msg or "UNAVAILABLE" in err_msg or "429" in err_msg:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    elif "404" in err_msg or "NOT_FOUND" in err_msg:
                        break
                    else:
                        break

        raise last_exception if last_exception else Exception("All active Gemini models failed.")

    def _build_summary_header(self, raw_items):
        counts = {
            "Carousels": 0,
            "Statics": 0,
            "UGC / Reels": 0,
            "Founder Content": 0,
            "Breaks": 0,
            "Other": 0
        }
        total_slides = 0

        for item in raw_items:
            title = str(item.get("short_title", "")).lower()
            slides = int(item.get("slide_count", 1))
            total_slides += slides

            if "founder" in title:
                counts["Founder Content"] += 1
            elif "ugc" in title or "reel" in title or "video" in title:
                counts["UGC / Reels"] += 1
            elif "break" in title:
                counts["Breaks"] += 1
            elif "carousel" in title:
                counts["Carousels"] += 1
            elif "static" in title:
                counts["Statics"] += 1
            else:
                counts["Other"] += 1

        total_deliverables = len(raw_items)

        header = (
            "==================================================\n"
            "📊 SHEET CONTENT SUMMARY\n"
            "==================================================\n"
            f"• Total Deliverables : {total_deliverables}\n"
            f"• Carousels          : {counts['Carousels']}\n"
            f"• Statics            : {counts['Statics']}\n"
            f"• UGC / Reels        : {counts['UGC / Reels']}\n"
            f"• Founder Content    : {counts['Founder Content']}\n"
            f"• Breaks             : {counts['Breaks']}\n"
            f"• Total Images/Slides: {total_slides}\n"
            "==================================================\n"
        )
        return header

    def _fetch_doc_html(self, doc_id):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        urls_to_try = [
            f"https://docs.google.com/document/d/{doc_id}/mobilebasic",
            f"https://docs.google.com/document/d/{doc_id}/pub",
            f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        ]

        for url in urls_to_try:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw_bytes = resp.read()
                    
                    # Handle zip downloads if format=html returns zip archive
                    if raw_bytes[:4] == b'PK\x03\x04':
                        with zipfile.ZipFile(BytesIO(raw_bytes)) as z:
                            html_files = [f for f in z.namelist() if f.endswith('.html')]
                            if html_files:
                                content = z.read(html_files[0]).decode('utf-8', errors='ignore')
                            else:
                                continue
                    else:
                        content = raw_bytes.decode('utf-8', errors='ignore')

                    if "<table" in content.lower():
                        parser = DocHTMLTableParser()
                        parser.feed(content)
                        if parser.rows:
                            return "html", parser.rows
                    elif len(content) > 50:
                        return "text", content
            except Exception:
                continue

        return None, None

    def _process_google_doc(self, doc_url, client, target_tab):
        doc_id_match = re.search(r'/d/([a-zA-Z0-9-_]+)', doc_url)
        if not doc_id_match:
            return ("Invalid Google Doc URL.",)

        doc_id = doc_id_match.group(1)
        base_doc_url = re.sub(r'/(edit|view|mobilebasic|pub).*$', '', doc_url)

        content_type, doc_data = self._fetch_doc_html(doc_id)
        if not doc_data:
            return ("Error fetching Google Doc. Ensure link access is set to 'Anyone with the link can view'.",)

        if content_type == "html":
            doc_context = json.dumps(doc_data[:150], indent=2)
            prompt = f"""
You are an expert social media production manager analyzing Google Document table structure.

GOAL:
Extract ALL deliverables listed under section: "{target_tab}".

CRITICAL EXTRACTION RULES:
1. Extract EVERY deliverable listed from top to bottom.
2. DATES: Identify dates aligned above or beside posts (e.g., 09.11.26, 10.11.26, 13.11.26). Format output as DD/MM/YYYY.
3. TITLE & SLIDE COUNT: Format short_title cleanly (e.g. "Age Arrest - Post Video", "Hydrating - Carousel"). Determine slide_count (x1, x5, x7).
4. HYPERLINKS & ANCHORS:
   - Extract exact direct URLs from cell "href" fields if available.
   - If "href" is empty, copy internal element "anchor" IDs if available.

Parsed HTML Context:
{doc_context}

Return strictly a JSON array of objects:
[
  {{
    "upload_date": "09/11/2026",
    "short_title": "Age Arrest - Post Video",
    "slide_count": 1,
    "direct_url": "",
    "anchor_id": "h.30j0zll"
  }}
]
"""
        else:
            prompt = f"""
You are an expert social media production manager analyzing a Google Document text export.

GOAL:
Extract ALL deliverables listed under section: "{target_tab}".

CRITICAL EXTRACTION RULES:
1. Extract EVERY deliverable in order top to bottom.
2. DATES: Match items to their respective upload dates.
3. TITLE & SLIDES: Extract short_title cleanly and count slides.

Document Text Content:
{doc_data[:100000]}

Return strictly a JSON array of objects:
[
  {{
    "upload_date": "09/11/2026",
    "short_title": "Age Arrest - Post Video",
    "slide_count": 1
  }}
]
"""

        try:
            items = self._call_gemini_bulletproof(client, prompt)
        except Exception as e:
            return (f"Extraction error: {str(e)}",)

        summary_header = self._build_summary_header(items)

        output_lines = []
        for item in items:
            date_str = str(item.get("upload_date", "")).replace(".", "/")
            short_title = self._clean_title_string(item.get("short_title", "Deliverable"))
            slides = int(item.get("slide_count", 1))
            direct_url = str(item.get("direct_url", "")).strip()
            anchor_id = str(item.get("anchor_id", "")).strip()

            if direct_url and direct_url.startswith("http"):
                final_url = direct_url
            elif anchor_id:
                if anchor_id.startswith("h."):
                    final_url = f"{base_doc_url}/edit#heading={anchor_id}"
                elif anchor_id.startswith("id."):
                    final_url = f"{base_doc_url}/edit#bookmark={anchor_id}"
                else:
                    final_url = f"{base_doc_url}/edit#bookmark=id.{anchor_id}"
            else:
                final_url = f"{base_doc_url}/edit"

            if date_str:
                line = f"{date_str} - [{short_title} x{slides}]({final_url})"
            else:
                line = f"[{short_title} x{slides}]({final_url})"

            output_lines.append(line)

        final_output = summary_header + "\n" + "\n".join(output_lines)
        return (final_output,)

    def _process_google_sheet(self, sheet_url):
        sheet_id_match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not sheet_id_match:
            return ("Invalid Google Sheet URL.",)

        sheet_id = sheet_id_match.group(1)
        gid_match = re.search(r'[?&]gid=([0-9]+)', sheet_url)
        gid_param = f"&gid={gid_match.group(1)}" if gid_match else ""
        xlsx_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx{gid_param}"

        try:
            req = urllib.request.Request(xlsx_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                xlsx_bytes = resp.read()

            parsed_grid = self._parse_xlsx_hyperlinks(xlsx_bytes)
            if not parsed_grid:
                return ("Could not extract sheet grid.",)

            raw_items = []
            output_lines = []

            for row in parsed_grid:
                row_text = " ".join([c["text"] for c in row if c["text"]])
                row_url = next((c["url"] for c in row if c["url"]), sheet_url)

                if not row_text:
                    continue

                clean_text = self._clean_title_string(row_text)

                slide_match = re.search(r'x(\d+)|(\d+)\s*slides?', clean_text, re.IGNORECASE)
                slides = int(slide_match.group(1) or slide_match.group(2)) if slide_match else 1

                raw_items.append({"short_title": clean_text, "slide_count": slides})
                output_lines.append(f"[{clean_text} x{slides}]({row_url})")

            summary_header = self._build_summary_header(raw_items)
            final_output = summary_header + "\n" + "\n".join(output_lines)

            return (final_output,)

        except Exception as e:
            return (f"Sheet error: {str(e)}",)

    def _parse_xlsx_hyperlinks(self, xlsx_bytes):
        with zipfile.ZipFile(BytesIO(xlsx_bytes)) as z:
            shared_strings = []
            if "xl/sharedStrings.xml" in z.namelist():
                tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for elem in tree.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                    text_parts = [t.text for t in elem.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t") if t.text]
                    shared_strings.append("".join(text_parts))

            rel_map = {}
            rels_path = "xl/worksheets/_rels/sheet1.xml.rels"
            if rels_path in z.namelist():
                rel_tree = ET.fromstring(z.read(rels_path))
                for rel in rel_tree.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                    rel_id = rel.attrib.get("Id")
                    target = rel.attrib.get("Target")
                    if rel_id and target:
                        rel_map[rel_id] = target

            sheet_tree = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))

            cell_links = {}
            hyperlinks_elem = sheet_tree.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}hyperlinks")
            if hyperlinks_elem is not None:
                for hl in hyperlinks_elem.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}hyperlink"):
                    ref = hl.attrib.get("ref")
                    r_id = hl.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                    if ref and r_id in rel_map:
                        cell_links[ref] = rel_map[r_id]

            grid_rows = []
            sheet_data = sheet_tree.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData")
            if sheet_data is not None:
                for row in sheet_data.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
                    row_cells = []
                    for c in row.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                        cell_ref = c.attrib.get("r")
                        cell_type = c.attrib.get("t")
                        v_elem = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                        cell_text = ""
                        if v_elem is not None and v_elem.text:
                            if cell_type == "s":
                                idx = int(v_elem.text)
                                cell_text = shared_strings[idx] if idx < len(shared_strings) else ""
                            else:
                                cell_text = v_elem.text

                        cell_url = cell_links.get(cell_ref, None)
                        row_cells.append({"text": cell_text.strip(), "url": cell_url})

                    if any(c["text"] for c in row_cells):
                        grid_rows.append(row_cells)

            return grid_rows


NODE_CLASS_MAPPINGS = {"GoogleWorkspaceReader": GoogleWorkspaceExtractorNode}
NODE_DISPLAY_NAME_MAPPINGS = {"GoogleWorkspaceReader": "Google Workspace Extractor Node"}

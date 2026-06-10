import sys
import re
import json
import fitz  # PyMuPDF
HAS_PYMUPDF = True
from pathlib import Path

class StructuredAnalyzer:
    """
    Patent Structured Analyzer with Dual-Pass logic, Mermaid visualization, and Drawing-only Figure Extraction.
    """
    
    def __init__(self):
        self.anchors = []

    def extract_text_from_pdf(self, pdf_path):
        doc = fitz.open(pdf_path)
        full_text = ""
        for page in doc:
            full_text += page.get_text("text") + "\n"
        return full_text

    def extract_claim_tree(self, claims_text):
        claim_blocks = re.split(r'(?:\n|\r\n|^)\s*(?:\d+\.|\(\d+\)|Claim\s+\d+\.?)', claims_text)
        tree = {}
        for i, block in enumerate(claim_blocks):
            if not block.strip() or i == 0: continue
            claim_num = str(i)
            deps = re.findall(r'(?:claim|claims|reivindicaci\u00f3n|revendication)\s*(\d+)', block, re.IGNORECASE)
            if deps:
                tree[claim_num] = sorted(list(set(deps)), key=int)
        return tree

    def extract_definitions(self, description):
        glossary = {}
        patterns = [
            r"term\s+['\"]([^'\"]+)['\"]\s+(?:means|is\s+defined\s+as|refers\s+to)\s+([^.]+)\.",
            r"['\"]([^'\"]+)['\"]\s+as\s+used\s+herein\s+(?:means|refers\s+to)\s+([^.]+)\.",
            r"definition\s+of\s+['\"]([^'\"]+)['\"]\s+is\s+([^.]+)\."
        ]
        for pattern in patterns:
            matches = re.finditer(pattern, description, re.IGNORECASE)
            for m in matches:
                term = m.group(1).strip()
                definition = m.group(2).strip()
                glossary[term] = definition
        return glossary

    def extract_figure_image(self, pdf_path, fig_label, output_dir="."):
        """
        Refined extraction: Priority given to pages WITH drawings (no/low text density).
        """
        if not HAS_PYMUPDF: return None
        doc = fitz.open(pdf_path)
        img_path = None
        search_term = fig_label.replace("Figure", "FIG.").upper()
        
        # Candidate pages (those that look like drawings)
        drawing_pages = []
        for i in range(len(doc)):
            page = doc[i]
            text = page.get_text("text")
            # Drawing pages usually have low word count (< 200 words) compared to Col pages
            if len(text.split()) < 200:
                drawing_pages.append(i)
        
        # Search for FIG label within those drawing-heavy pages first
        for i in drawing_pages:
            page = doc[i]
            if page.search_for(search_term):
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                filename = f"{Path(pdf_path).stem}_{fig_label.replace(' ', '')}_FIXED.png"
                img_path = str(Path(output_dir) / filename)
                pix.save(img_path)
                print(f"[IMAGE] Extracted {fig_label} from DRAWING page {i+1}")
                doc.close()
                return img_path
        
        doc.close()
        return None

    def sanitize_mermaid_label(self, label: str) -> str:
        """Escape brackets and quotes for Mermaid node labels."""
        if not label: return "node"
        return label.replace("[", "(").replace("]", ")").replace("\"", "'")

    def generate_mermaid(self, structured_data, graph_type="claim_tree"):
        """
        Generate human-readable Mermaid syntax.
        """
        if graph_type == "claim_tree":
            mermaid = "```mermaid\ngraph LR\n"
            tree = structured_data.get("claim_tree", {})
            if not tree: return ""
            for claim, deps in tree.items():
                for dep in deps:
                    mermaid += f'    Claim{dep}["Claim {dep}"] --> Claim{claim}["Claim {claim}"]\n'
            return mermaid + "\n```"

        # Default component structure
        mermaid = "```mermaid\ngraph TD\n"
        components = structured_data.get("components", [])
        
        for comp in components:
            cid = comp.get("id", "Unknown")
            name = self.sanitize_mermaid_label(comp.get("name", "Component"))
            mermaid += f'    Comp{cid}["{name} {cid}"]\n'
            
            # Relationships
            for sub in comp.get("sub_components", []):
                sid = sub.get("id")
                sname = self.sanitize_mermaid_label(sub.get("name", "Sub-component"))
                mermaid += f'    Comp{cid} --> Comp{sid}["{sname} {sid}"]\n'
        
        return mermaid + "\n```"

    def run_analysis_pipeline(self, pdf_path, claims_text):
        full_text = self.extract_text_from_pdf(pdf_path)
        claim_tree = self.extract_claim_tree(claims_text)
        glossary = self.extract_definitions(full_text)
        
        # Find top 2 mentioned FIGs in CLAIMS or early DESCRIPTION
        fig_refs = re.findall(r'FIG\.\s*(\d+)', claims_text + full_text[:5000])
        top_figs = sorted(list(set(fig_refs)), key=lambda x: fig_refs.count(x), reverse=True)[:2]
        if not top_figs: top_figs = ["1"] # Default to Fig 1

        extracted_images = {}
        for fnum in top_figs:
            flabel = f"FIG. {fnum}"
            path = self.extract_figure_image(pdf_path, flabel, output_dir=str(Path(pdf_path).parent))
            if path:
                extracted_images[flabel] = path

        return {
            "claim_tree": claim_tree,
            "claim_tree_mermaid": self.generate_mermaid({"claim_tree": claim_tree}),
            "glossary": glossary,
            "extracted_images": extracted_images
        }

if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(1)
    pdf = sys.argv[1]
    with open(sys.argv[2], "r", encoding="utf-8") as f: claims = f.read()
    analyzer = StructuredAnalyzer()
    result = analyzer.run_analysis_pipeline(pdf, claims)
    print(json.dumps(result, ensure_ascii=False, indent=2))

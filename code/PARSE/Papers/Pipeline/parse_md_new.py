#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

# Clear DYLD_LIBRARY_PATH to avoid SSL library conflicts
if "DYLD_LIBRARY_PATH" in os.environ:
    del os.environ["DYLD_LIBRARY_PATH"]

import re, html, argparse, xml.etree.ElementTree as ET
from hashlib import md5
from urllib.parse import quote
from typing import Dict, List, Tuple, Set

import markdown
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS, DC, XSD, OWL, SKOS
import utils

# --------------------------------------------------------------------------- #
# Namespaces
ASKG_DATA = Namespace("https://www.anu.edu.au/data/scholarly/")
ASKG_ONTO = Namespace("https://www.anu.edu.au/onto/scholarly#")
DOMO      = Namespace("http://example.org/domo/")

NUMBER_OF_SENTENCES = "numberOfSentences"
HAS_CITATION        = "hasCitation"

# --------------------------------------------------------------------------- #
# MEANINGFUL_TYPES 保持完全不变
MEANINGFUL_TYPES = {
    # People and Organizations
    "Person",
    "Researcher",
    "Scientist",
    "Author",
    "Organization",
    "Institution",
    "University",
    "Company",
    "Research Group",
    # Academic Concepts
    "Algorithm",
    "Method",
    "Technique",
    "Framework",
    "Model",
    "Dataset",
    "Database",
    "Corpus",
    "Research Field",
    "Research Area",
    "Domain",
    "Theory",
    "Concept",
    "Paradigm",
    # Research Artifacts
    "Paper",
    "Publication",
    "Article",
    "Study",
    "Experiment",
    "Result",
    "Finding",
    "System",
    "Tool",
    "Software",
    "Platform",
    # Scientific Terms
    "Protein",
    "Gene",
    "Molecule",
    "Cell Type",
    "Disease",
    "Condition",
    "Symptom",
    "Technology",
    "Device",
    "Equipment",
    # Metrics and Measurements
    "Metric",
    "Measure",
    "Score",
    "Rate",
    "Index",
}

# --------------------------------------------------------------------------- #
# === 引用 / 参考文献辅助 ======================================================
_ref_head_pat = re.compile(
    r"^(#{1,6})\s*(references?|bibliography|works\s+cited)\s*$",
    re.I | re.M
)
_ref_line_lead = re.compile(r"^\s*(\[\d+\]|\d+[.)])\s*")
_num_pat  = re.compile(r"\[(\d+(?:\s*[\u2013\u2014\-]\s*\d+)?(?:\s*,\s*\d+(?:\s*[\u2013\u2014\-]\s*\d+)?)*)\]")
_auth_pat = re.compile(r"(?:^|\W)([A-Z][A-Za-z\-]+).*?(\d{4})")

def _expand_range(tok: str) -> List[str]:
    if re.search(r"[\u2013\u2014\-]", tok):
        a, b = re.split(r"[\u2013\u2014\-]", tok)
        return [str(i) for i in range(int(a), int(b) + 1)]
    return [tok]

def extract_citations(text: str) -> List[str]:
    cites, seen = [], set()
    for m in _num_pat.finditer(text):
        for part in m.group(1).split(","):
            part = part.strip()
            for n in _expand_range(part):
                if n not in seen:
                    cites.append(n); seen.add(n)
    for m in _auth_pat.finditer(text):
        key = f"{m.group(1).lower()}_{m.group(2)}"
        if key not in seen:
            cites.append(key); seen.add(key)
    return cites

def extract_reference_block(md: str) -> str:
    for m in _ref_head_pat.finditer(md):
        start_line_end = md.find("\n", m.start())
        if start_line_end == -1:
            start_line_end = len(md)
        rest = md[start_line_end + 1:]
        nxt  = re.search(r"^#{1,6}\s", rest, re.M)
        end  = start_line_end + 1 + (nxt.start() if nxt else len(rest))
        return md[start_line_end + 1 : end].strip()
    return ""

def parse_reference_lines(block: str) -> List[Dict]:
    refs = []
    for ln in block.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        idx = None
        m = _ref_line_lead.match(ln)
        if m:
            idx = re.sub(r"[^\d]", "", m.group(1))
            ln  = ln[m.end():].strip()
        m_year = re.search(r"\((\d{4})\)", ln)
        year = m_year.group(1) if m_year else ""
        before = ln[:m_year.start()].strip() if m_year else ln
        after  = ln[m_year.end():].strip()   if m_year else ""
        authors = before.rstrip(".")
        title   = after.split(".")[0].strip() or after
        refs.append({"idx": idx, "authors": authors, "year": year, "title": title})
    return refs

# --------------------------------------------------------------------------- #
# === 原清洗/分段/分句函数 =====================================================
def clean_text(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def split_into_paragraphs(content):
    return [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]

def split_into_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_text(text)) if s.strip()]

def parse_markdown_structure(md_content):
    lines = md_content.split("\n")
    sections, cur, buf = [], None, []
    for ln in lines:
        m = re.match(r"^(#{1,6})\s+(.+)$", ln)
        if m:
            if cur:
                cur["content"] = "\n".join(buf).strip(); sections.append(cur)
            cur = {"level": len(m.group(1)), "title": m.group(2).strip(), "index": len(sections) + 1}
            buf = []
        elif cur: buf.append(ln)
    if cur:
        cur["content"] = "\n".join(buf).strip(); sections.append(cur)
    return sections

# --------------------------------------------------------------------------- #
# === build_document_structure（增 numberOfSentences & citation 标签）=========
def build_document_structure(md_content):
    doc = ET.Element("section")
    for sec in parse_markdown_structure(md_content):
        sec_el = ET.SubElement(doc,"section",ID=str(sec["index"]),
                               index=str(sec["index"]),level=str(sec["level"]))
        ET.SubElement(sec_el,"heading").text = sec["title"]

        sec_sent_cnt = 0
        for pi, para in enumerate(split_into_paragraphs(sec["content"]), 1):
            para_el = ET.SubElement(sec_el,"paragraph",ID=f"{sec['index']}.{pi}",index=str(pi))
            ET.SubElement(para_el,"text").text = clean_text(para)

            # 标注段落级引用
            for cit in extract_citations(para):
                ET.SubElement(para_el,"citation").text = cit

            para_sent_cnt = 0
            for si, sent in enumerate(split_into_sentences(para), 1):
                sent_el = ET.SubElement(para_el,"sentence",ID=f"{sec['index']}.{pi}.{si}",
                                        index=str(si))
                ET.SubElement(sent_el,"text").text = sent
                for cit in extract_citations(sent):
                    ET.SubElement(sent_el,"citation").text = cit
                para_sent_cnt += 1

            para_el.set(NUMBER_OF_SENTENCES, str(para_sent_cnt))
            sec_sent_cnt += para_sent_cnt
        sec_el.set(NUMBER_OF_SENTENCES, str(sec_sent_cnt))
    return doc

# --------------------------------------------------------------------------- #
# === Helper =================================================================
def _clean_uri(text: str, max_len: int = 80) -> str:
    base = re.sub(r"[^\w\s-]", "", text).lower().replace(" ", "_")
    base = quote(base)[:max_len]
    return base or md5(text.encode()).hexdigest()[:12]

def _citation_literal(raw: str, num_idx: Dict, ay_idx: Dict, existing: Dict) -> str:
    if raw.isdigit():
        ref = num_idx.get(raw)
        if not ref: return f"[{raw}]"
    else:
        ref = ay_idx.get(raw)
        if not ref: return raw.replace("_", " ")
    pid = None
    for k, info in existing.items():
        if info["title"].lower() == ref["title"].lower() and info.get("year") == ref.get("year"):
            pid = k; break
    title, authors = ref["title"], ref["authors"]
    return f"{pid} ⟂ {title} ⟂ {authors}" if pid else f"{title} ⟂ {authors}"

# --------------------------------------------------------------------------- #
# === generate_ttl（重写） =====================================================
def generate_ttl(doc, output_file, paper_id, md_content, existing_papers=None):
    g = Graph()
    for p, ns in [("askg-data", ASKG_DATA), ("askg-onto", ASKG_ONTO), ("domo", DOMO)]:
        g.bind(p, ns)
    g.bind("rdfs", RDFS); g.bind("xsd", XSD)

    # Predicates
    idx_p   = URIRef(ASKG_ONTO + "index")
    lvl_p   = URIRef(ASKG_ONTO + "level")
    n_sent_p= URIRef(ASKG_ONTO + NUMBER_OF_SENTENCES)
    has_cit_p=URIRef(ASKG_ONTO + HAS_CITATION)
    mentions_p = URIRef(ASKG_ONTO + "mentions")
    in_sent_p  = URIRef(ASKG_ONTO + "inSentence")
    ent_type_p = URIRef(ASKG_ONTO + "entityType")

    clean_pid = _clean_uri(paper_id)
    paper_uri = URIRef(ASKG_DATA + f"Paper-{clean_pid}")
    paper_title = next((ln[2:].strip() for ln in md_content.splitlines()
                        if ln.startswith("# ")), paper_id)
    g.add((paper_uri, RDF.type, ASKG_ONTO.Paper))
    g.add((paper_uri, DC.title, Literal(paper_title, lang="en")))
    g.add((paper_uri, RDFS.label, Literal(paper_title, lang="en")))

    # 引用索引
    num_idx, ay_idx = {}, {}
    for r in parse_reference_lines(extract_reference_block(md_content)):
        if r["idx"]: num_idx[r["idx"]] = r
        if r["authors"] and r["year"]:
            key=f"{r['authors'].split(',')[0].split()[-1].lower()}_{r['year']}"
            ay_idx[key] = r
    existing_papers = existing_papers or {}

    # 遍历 XML
    for sec in doc.findall("./section"):
        sid = sec.get("ID")
        sec_uri = URIRef(ASKG_DATA + f"Paper-{clean_pid}-Section-{sid}")
        g.add((sec_uri, RDF.type, ASKG_ONTO.Section))
        g.add((paper_uri, ASKG_ONTO.hasSection, sec_uri))
        g.add((sec_uri, RDFS.label, Literal(f"Section {sid}", lang="en")))
        g.add((sec_uri, idx_p, Literal(sid, datatype=XSD.int)))
        g.add((sec_uri, lvl_p, Literal(sec.get("level"), datatype=XSD.int)))
        g.add((sec_uri, n_sent_p, Literal(sec.get(NUMBER_OF_SENTENCES), datatype=XSD.positiveInteger)))
        hd = sec.find("heading")
        if hd is not None:
            g.add((sec_uri, DOMO.Text, Literal(hd.text, lang="en")))

        sec_cits: Set[str] = set()

        for para in sec.findall("paragraph"):
            pid = para.get("ID")
            para_uri = URIRef(
                ASKG_DATA + f"Paper-{clean_pid}-Section-{sid}-Paragraph-{_clean_uri(pid)}")
            g.add((para_uri, RDF.type, ASKG_ONTO.Paragraph))
            g.add((sec_uri, ASKG_ONTO.hasParagraph, para_uri))
            g.add((para_uri, RDFS.label, Literal(f"Paragraph {para.get('index')}", lang="en")))
            g.add((para_uri, idx_p, Literal(para.get("index"), datatype=XSD.int)))
            g.add((para_uri, n_sent_p, Literal(para.get(NUMBER_OF_SENTENCES), datatype=XSD.positiveInteger)))
            p_txt_el = para.find("text")
            if p_txt_el is not None:
                g.add((para_uri, DOMO.Text, Literal(p_txt_el.text, lang="en")))
            para_cits: Set[str] = set()

            # 段落引用
            for cit_el in para.findall("citation"):
                lit = _citation_literal(cit_el.text, num_idx, ay_idx, existing_papers)
                if lit not in para_cits:
                    g.add((para_uri, has_cit_p, Literal(lit))); para_cits.add(lit)
                if lit not in sec_cits:
                    g.add((sec_uri, has_cit_p, Literal(lit))); sec_cits.add(lit)

            for sent in para.findall("sentence"):
                sid_full = sent.get("ID")
                sent_uri = URIRef(
                    ASKG_DATA + f"Paper-{clean_pid}-Section-{sid}-Paragraph-{_clean_uri(pid)}-Sentence-{_clean_uri(sid_full)}"
                )
                g.add((sent_uri, RDF.type, ASKG_ONTO.Sentence))
                g.add((para_uri, ASKG_ONTO.hasSentence, sent_uri))
                g.add((sent_uri, RDFS.label, Literal(f"Sentence {sent.get('index')}", lang="en")))
                g.add((sent_uri, idx_p, Literal(sent.get("index"), datatype=XSD.int)))
                s_txt = sent.find("text").text
                g.add((sent_uri, DOMO.Text, Literal(s_txt, lang="en")))

                for cit_el in sent.findall("citation"):
                    lit = _citation_literal(cit_el.text, num_idx, ay_idx, existing_papers)
                    if lit not in para_cits:
                        g.add((sent_uri, has_cit_p, Literal(lit)))
                        g.add((para_uri, has_cit_p, Literal(lit)))
                        para_cits.add(lit)
                    if lit not in sec_cits:
                        g.add((sec_uri, has_cit_p, Literal(lit))); sec_cits.add(lit)

                # 保留实体抽取
                try:
                    ents, has_ents = utils.get_entities(s_txt)
                    g.add((sent_uri, in_sent_p, Literal(s_txt, datatype=XSD.string)))
                    if has_ents:
                        for e in ents:
                            if e.head_type in MEANINGFUL_TYPES:
                                h_uri = URIRef(ASKG_DATA + f"Entity-{_clean_uri(e.head)}")
                                g.add((sent_uri, mentions_p, h_uri))
                                g.add((h_uri, RDFS.label, Literal(e.head, lang="en")))
                                g.add((h_uri, ent_type_p, Literal(e.head_type, lang="en")))
                            if e.tail_type in MEANINGFUL_TYPES:
                                t_uri = URIRef(ASKG_DATA + f"Entity-{_clean_uri(e.tail)}")
                                g.add((sent_uri, mentions_p, t_uri))
                                g.add((t_uri, RDFS.label, Literal(e.tail, lang="en")))
                                g.add((t_uri, ent_type_p, Literal(e.tail_type, lang="en")))
                except Exception as e:
                    print("Entity extraction error:", e)

    g.serialize(destination=output_file, format="turtle")
    print("✓ TTL saved:", output_file)

# --------------------------------------------------------------------------- #
# 其余流程保持不变 -------------------------------------------------------------
def process_markdown_file(input_file, output_ttl, paper_id=None, existing_papers=None):
    with open(input_file, "r", encoding="utf-8") as f:
        md_content = f.read()
    if paper_id is None:
        paper_id = os.path.splitext(os.path.basename(input_file))[0]
    doc = build_document_structure(md_content)
    generate_ttl(doc, output_ttl, paper_id, md_content, existing_papers)

def process_all_markdown_files(input_dir="./markdown", output_dir="./output"):
    os.makedirs(output_dir, exist_ok=True)
    md_files = [f for f in os.listdir(input_dir) if f.endswith(".md")]
    if not md_files:
        print(f"No markdown files found in {input_dir}"); return
    for md_file in md_files:
        in_path = os.path.join(input_dir, md_file)
        out_path= os.path.join(output_dir, f"{os.path.splitext(md_file)[0]}.ttl")
        process_markdown_file(in_path, out_path)

# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input_dir", default="./markdown")
    parser.add_argument("-o", "--output_dir", default="./output")
    args = parser.parse_args()
    process_all_markdown_files(args.input_dir, args.output_dir)
